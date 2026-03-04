import asyncio
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
SERPER_IMAGES_URL = "https://google.serper.dev/images"
_CACHE: dict[str, tuple[dict, float]] = {}  # key → (data, expires_at)
TTL = 3600  # 1 hour


def _cache_key(watch: dict) -> str:
    brand = watch.get("Brand") or watch.get("brand", "")
    model = watch.get("Model") or watch.get("model", "")
    ref = watch.get("Reference") or watch.get("reference", "")
    return f"{brand}|{model}|{ref}".lower()


async def enrich_watch(watch: dict) -> dict:
    """Return enriched info dict for one owned watch (memory-cached 1h)."""
    key = _cache_key(watch)
    cached, expires = _CACHE.get(key, ({}, 0.0))
    if time.time() < expires:
        return cached

    brand = watch.get("Brand") or watch.get("brand", "")
    model = watch.get("Model") or watch.get("model", "")
    ref = watch.get("Reference") or watch.get("reference", "")
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

            # Image search if no knowledgeGraph image
            if not info.get("image_url"):
                ir = await client.post(
                    SERPER_IMAGES_URL, json={"q": q, "num": 3}, headers=headers
                )
                if ir.status_code == 200:
                    imgs = ir.json().get("images", [])
                    if imgs:
                        info["image_url"] = imgs[0].get("imageUrl", "")
    except Exception as exc:
        logger.warning("Watch enrichment failed for %s: %s", q, exc)
        return {}

    _CACHE[key] = (info, time.time() + TTL)
    return info


async def enrich_watches(watches: list[dict]) -> list[tuple[dict, dict]]:
    """Return [(watch_row, enriched_info), ...] for all owned watches."""
    results = await asyncio.gather(*[enrich_watch(w) for w in watches], return_exceptions=True)
    return [
        (w, r if isinstance(r, dict) else {})
        for w, r in zip(watches, results)
    ]
