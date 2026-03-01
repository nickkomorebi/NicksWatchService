import asyncio
import base64
import logging
from urllib.parse import urljoin

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
    "Accept-Language": "en-US,en;q=0.9",
}

# Patterns that indicate icon/logo/tracker images — skip these
# Keep patterns long enough to avoid false positives (e.g. "ad" also matches "uploads")
SKIP_PATTERNS = [
    "logo", "icon", "avatar", "pixel", "tracking", "sprite",
    "banner", "/ads/", "badge", "button", "spacer", "blank",
    "privacy", "consent", "cookie",
]

# Domains that only host watch/clock content — skip Claude vision check
# because any image from these domains is guaranteed to be watch-related
TRUSTED_WATCH_DOMAINS = {
    "everywatch.com",
    "img.everywatch.com",
    "chrono24.com",
    "watchcharts.com",
    "watchuseek.com",
    "watchrecon.com",
    "watchexchange.com",
    "reddit.com",      # [WTS]/[WTB] posts are watch listings
    "preview.redd.it", # Reddit preview images
    "i.redd.it",       # Reddit inline images
}


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
        if not src or src.startswith("data:"):
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(base_url, src)
        if not _is_valid_image_url(src):
            continue
        try:
            if img.get("width") and int(img["width"]) < 100:
                continue
            if img.get("height") and int(img["height"]) < 100:
                continue
        except ValueError:
            pass
        return src

    return None


async def _fetch_with_httpx(url: str) -> str | None:
    """Try fetching the page with plain httpx."""
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=HEADERS) as client:
        resp = await client.get(url)
        if resp.status_code == 200 and "html" in resp.headers.get("content-type", ""):
            return resp.text
    return None


async def _fetch_with_playwright(url: str) -> str | None:
    """Fallback: render page with a real browser to bypass bot detection."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:
        logger.debug("Playwright fetch failed for %s: %s", url, exc)
        return None


async def fetch_listing_image(url: str) -> str | None:
    """Fetch a listing page and extract the best candidate image URL.
    Falls back to Playwright for pages that block plain HTTP."""
    async with _fetch_semaphore:
        try:
            html = await _fetch_with_httpx(url)
            if html is None:
                # Blocked or non-200 — try Playwright
                logger.debug("httpx blocked for %s, trying Playwright", url)
                html = await _fetch_with_playwright(url)
            if html is None:
                return None
            return _extract_image_from_html(html, url)
        except Exception as exc:
            logger.debug("Image fetch failed for %s: %s", url, exc)
            return None


async def verify_watch_image(image_url: str) -> bool:
    """Download image and ask Claude Haiku if it looks like a watch.

    Skips the LLM check entirely for images from trusted watch-specific domains,
    since those pages only ever show watches.
    """
    from app.config import settings

    # Fast-path: trust images from known watch-only platforms
    from urllib.parse import urlparse
    host = urlparse(image_url).netloc.lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in TRUSTED_WATCH_DOMAINS):
        logger.debug("Trusted domain — skipping vision check for %s", image_url)
        return True

    if not settings.anthropic_api_key:
        return True

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(image_url)
            if resp.status_code != 200:
                logger.debug("Image download got %d for %s", resp.status_code, image_url)
                return False
            content_type = resp.headers.get("content-type", "image/jpeg")
            if "image" not in content_type:
                return False
            # Cap at 2 MB to avoid huge base64 payloads
            if len(resp.content) > 2 * 1024 * 1024:
                return True  # too large to verify, assume ok
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
                        "source": {"type": "base64", "media_type": media_type, "data": image_data},
                    },
                    {
                        "type": "text",
                        "text": "Does this image show a watch or clock? Reply with only YES or NO.",
                    },
                ],
            }],
        )
        answer = message.content[0].text.strip().upper()
        passed = answer.startswith("YES")
        logger.debug("Vision check for %s: %s", image_url, answer)
        return passed
    except Exception as exc:
        logger.debug("Vision check failed for %s: %s", image_url, exc)
        return True  # on error, don't discard
