import asyncio
import base64
import json
import logging
import os
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
SERPER_IMAGES_URL = "https://google.serper.dev/images"

_DISK_CACHE_PATH = "data/watch_enrichment_cache.json"
_COLLECTION_IMG_DIR = "app/static/img/collection"
_mem: dict[str, dict] = {}  # runtime mirror of disk cache


def _load_disk_cache() -> None:
    global _mem
    if os.path.exists(_DISK_CACHE_PATH):
        try:
            with open(_DISK_CACHE_PATH) as f:
                _mem = json.load(f)
        except Exception as exc:
            logger.warning("Could not load enrichment cache: %s", exc)
            _mem = {}


def _save_disk_cache() -> None:
    os.makedirs(os.path.dirname(_DISK_CACHE_PATH), exist_ok=True)
    try:
        with open(_DISK_CACHE_PATH, "w") as f:
            json.dump(_mem, f, indent=2)
    except Exception as exc:
        logger.warning("Could not save enrichment cache: %s", exc)


_load_disk_cache()


_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def _download_image_locally(url: str, key: str) -> str:
    """Download an image from url and save it to the static collection dir.

    Returns the local static path (e.g. /static/img/collection/xxx.jpg)
    or empty string on failure.
    """
    os.makedirs(_COLLECTION_IMG_DIR, exist_ok=True)
    safe_key = re.sub(r"[^a-z0-9_-]", "_", key)[:80]
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return ""
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        ext = _EXT_MAP.get(content_type, ".jpg")
        filename = f"{safe_key}{ext}"
        filepath = os.path.join(_COLLECTION_IMG_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(resp.content)
        logger.debug("Saved collection image: %s", filepath)
        return f"/static/img/collection/{filename}"
    except Exception as exc:
        logger.debug("Failed to download image %s: %s", url, exc)
        return ""


async def _find_verified_image(candidates: list[dict], brand: str, model: str) -> str:
    """Try image candidates in order; return first one Claude confirms shows the right watch."""
    if not candidates:
        return ""

    if not settings.anthropic_api_key:
        return candidates[0].get("imageUrl", "")

    import anthropic
    llm = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    for img in candidates[:8]:
        url = img.get("imageUrl", "")
        if not url or not url.startswith("http"):
            continue
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as hc:
                resp = await hc.get(url)
            if resp.status_code != 200 or "image" not in resp.headers.get("content-type", ""):
                continue
            if len(resp.content) > 2 * 1024 * 1024:
                return url  # too large to verify, assume ok
            media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                media_type = "image/jpeg"
            image_data = base64.standard_b64encode(resp.content).decode()
        except Exception as exc:
            logger.debug("Image download failed for %s: %s", url, exc)
            continue

        try:
            msg = await llm.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=16,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                        {"type": "text", "text": "Does this image show a single wristwatch clearly (not multiple watches, not a catalog page, not being worn on a wrist)? Reply YES or NO only."},
                    ],
                }],
            )
            if msg.content[0].text.strip().upper().startswith("YES"):
                logger.debug("Image verified for %s %s: %s", brand, model, url)
                return url
            else:
                logger.debug("Image rejected for %s %s: %s", brand, model, url)
        except Exception as exc:
            logger.debug("Vision check failed for %s: %s", url, exc)
            continue

    # Fall back to first candidate if none verified
    logger.debug("No verified image found for %s %s, using first candidate", brand, model)
    return candidates[0].get("imageUrl", "")


def _cache_key(watch: dict) -> str:
    brand = watch.get("Brand") or watch.get("brand", "")
    model = watch.get("Name") or watch.get("Model") or watch.get("name") or watch.get("model", "")
    ref = watch.get("Reference") or watch.get("reference", "")
    return f"{brand}|{model}|{ref}".lower()


async def enrich_watch(watch: dict) -> dict:
    """Return enriched info dict for one owned watch (persisted indefinitely on disk)."""
    key = _cache_key(watch)
    if key in _mem:
        cached = _mem[key]
        img = cached.get("image_url", "")
        # If cached image is a remote URL (not yet persisted locally), download it now
        if img and img.startswith("http"):
            local = await _download_image_locally(img, key)
            if local:
                cached["image_url"] = local
                _mem[key] = cached
                _save_disk_cache()
        return _mem[key]

    brand = watch.get("Brand") or watch.get("brand", "")
    model = watch.get("Name") or watch.get("Model") or watch.get("name") or watch.get("model", "")
    ref = watch.get("Reference") or watch.get("reference", "")
    search_kw = watch.get("search keywords") or watch.get("Search Keywords", "")
    custom_photo = watch.get("Photo") or watch.get("photo") or watch.get("Image URL") or watch.get("image_url") or ""
    if search_kw:
        q = f"{search_kw} watch specifications"
    else:
        q = " ".join(filter(None, [brand, model, ref, "watch specifications"]))

    if not settings.serper_api_key:
        logger.warning("SERPER_API_KEY not configured; skipping watch enrichment")
        return {}

    headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
    info: dict = {}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Specs search
            r = await client.post(SERPER_URL, json={"q": q, "num": 5}, headers=headers)
            r.raise_for_status()
            data = r.json()

            kg = data.get("knowledgeGraph", {})
            if kg:
                info["description"] = kg.get("description", "")
                info["image_url"] = kg.get("imageUrl", "")
                info["attributes"] = kg.get("attributes", {})
                info["source_url"] = kg.get("descriptionLink", "")
                info["source_title"] = kg.get("descriptionSource", "")
            elif data.get("answerBox"):
                ab = data["answerBox"]
                info["description"] = ab.get("answer") or ab.get("snippet", "")
                info["source_url"] = ab.get("link", "")
                info["source_title"] = ab.get("title", "")
            elif data.get("organic"):
                top = data["organic"][0]
                info["description"] = top.get("snippet", "")
                info["source_url"] = top.get("link", "")
                info["source_title"] = top.get("title", "")

            # Custom photo from sheet takes priority
            if custom_photo:
                local = await _download_image_locally(custom_photo, key)
                info["image_url"] = local or custom_photo
            # Persist knowledgeGraph image locally
            elif info.get("image_url"):
                local = await _download_image_locally(info["image_url"], key)
                if local:
                    info["image_url"] = local
            # Image search if still no image
            else:
                image_q = search_kw or " ".join(filter(None, [brand, model, ref]))
                ir = await client.post(
                    SERPER_IMAGES_URL, json={"q": image_q, "num": 10}, headers=headers
                )
                if ir.status_code == 200:
                    imgs = ir.json().get("images", [])
                    if imgs:
                        remote_url = await _find_verified_image(imgs, brand, model)
                        if remote_url:
                            local = await _download_image_locally(remote_url, key)
                            info["image_url"] = local or remote_url
    except Exception as exc:
        logger.warning("Watch enrichment failed for %s: %s", q, exc)
        return {}

    _mem[key] = info
    _save_disk_cache()
    return info


async def enrich_watches(watches: list[dict]) -> list[tuple[dict, dict]]:
    """Return [(watch_row, enriched_info), ...] for all owned watches."""
    results = await asyncio.gather(*[enrich_watch(w) for w in watches], return_exceptions=True)
    return [
        (w, r if isinstance(r, dict) else {})
        for w, r in zip(watches, results)
    ]
