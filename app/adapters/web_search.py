import logging
from typing import TYPE_CHECKING

import httpx

from app.adapters.base import AdapterError, BaseAdapter, RawListing
from app.config import settings

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"


def _build_query(watch: "Watch") -> str:
    refs = [r.strip() for r in (watch.references_csv or "").split(",") if r.strip()]
    parts = [f"{watch.brand} {watch.model}"]
    if refs:
        parts.append(refs[0])
    if watch.query_terms:
        parts.append(watch.query_terms)
    parts.append("used for sale")
    return " ".join(parts)


class WebSearchAdapter(BaseAdapter):
    name = "web_search"

    async def search(self, watch: "Watch") -> list[RawListing]:
        if not settings.serper_api_key:
            raise AdapterError("SERPER_API_KEY not configured")

        query = _build_query(watch)
        payload = {"q": query, "num": 20}
        headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.post(SERPER_URL, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise AdapterError(f"Serper request failed: {exc}") from exc

        data = resp.json()
        results = []
        for item in data.get("organic", []):
            results.append(
                RawListing(
                    source=self.name,
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    price_amount=None,
                    currency=None,
                    condition=None,
                    seller_location=None,
                    image_url=None,
                    extra_data={"snippet": item.get("snippet", "")},
                )
            )
        logger.debug("%s: %d results for '%s'", self.name, len(results), query)
        return results
