import asyncio
import base64
import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Limit concurrent page fetches to avoid hammering sites
_fetch_semaphore = asyncio.Semaphore(5)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Image extensions to accept
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Patterns that indicate icon/logo/tracker images to skip
SKIP_PATTERNS = [
    "logo", "icon", "avatar", "pixel", "tracking", "sprite",
    "banner", "ad", "badge", "button", "spacer", "blank",
]


def _is_valid_image_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    lower = url.lower()
    if any(p in lower for p in SKIP_PATTERNS):
        return False
    return True


def _extract_image_from_html(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # 1. og:image — most reliable for listing pages
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og and og.get("content"):
        url = og["content"].strip()
        if _is_valid_image_url(url):
            return url

    # 2. twitter:image
    tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
    if tw and tw.get("content"):
        url = tw["content"].strip()
        if _is_valid_image_url(url):
            return url

    # 3. First <img> with a decent src (skip tiny icons)
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if not src:
            continue
        # Make absolute
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(base_url, src)
        if not _is_valid_image_url(src):
            continue
        # Skip data URIs
        if src.startswith("data:"):
            continue
        # Prefer images with product-like dimensions in attributes
        width = img.get("width", "")
        height = img.get("height", "")
        try:
            if width and int(width) < 100:
                continue
            if height and int(height) < 100:
                continue
        except ValueError:
            pass
        return src

    return None


async def fetch_listing_image(url: str) -> str | None:
    """Fetch a listing page and extract the best candidate image URL."""
    async with _fetch_semaphore:
        try:
            async with httpx.AsyncClient(
                timeout=8,
                follow_redirects=True,
                headers=HEADERS,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                content_type = resp.headers.get("content-type", "")
                if "html" not in content_type:
                    return None
                return _extract_image_from_html(resp.text, url)
        except Exception as exc:
            logger.debug("Image fetch failed for %s: %s", url, exc)
            return None


async def verify_watch_image(image_url: str) -> bool:
    """Download image and ask Claude if it looks like a watch. Returns True if it passes."""
    from app.config import settings

    if not settings.anthropic_api_key:
        return True  # can't verify, assume ok

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(image_url)
            if resp.status_code != 200:
                return False
            content_type = resp.headers.get("content-type", "image/jpeg")
            if "image" not in content_type:
                return False
            image_data = base64.standard_b64encode(resp.content).decode()
            media_type = content_type.split(";")[0].strip()
            if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                media_type = "image/jpeg"
    except Exception as exc:
        logger.debug("Image download failed for %s: %s", image_url, exc)
        return False

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=16,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Does this image show a watch or clock? Reply with only YES or NO.",
                    },
                ],
            }],
        )
        answer = message.content[0].text.strip().upper()
        return answer.startswith("YES")
    except Exception as exc:
        logger.debug("Vision check failed for %s: %s", image_url, exc)
        return True  # on error, don't discard the image
