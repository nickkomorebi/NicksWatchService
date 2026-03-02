import logging
from typing import TYPE_CHECKING

import httpx

from app.adapters.base import AdapterError, BaseAdapter, RawListing, build_queries
from app.config import settings

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"


class WebSearchAdapter(BaseAdapter):
    name = "web_search"

    async def search(self, watch: "Watch") -> list[RawListing]:
        if not settings.serper_api_key:
            raise AdapterError("SERPER_API_KEY not configured")

        headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
        seen: set[str] = set()
        results: list[RawListing] = []

        async with httpx.AsyncClient(timeout=20) as client:
            for query in build_queries(watch):
                q = f"{query} used for sale"
                try:
                    resp = await client.post(SERPER_URL, json={"q": q, "num": 20}, headers=headers)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise AdapterError(f"Serper request failed: {exc}") from exc

                for item in resp.json().get("organic", []):
                    url = item.get("link", "")
                    if url in seen:
                        continue
                    seen.add(url)
                    results.append(RawListing(
                        source=self.name,
                        url=url,
                        title=item.get("title", ""),
                        price_amount=None,
                        currency=None,
                        condition=None,
                        seller_location=None,
                        image_url=None,
                        extra_data={"snippet": item.get("snippet", "")},
                    ))
                logger.debug("%s: query='%s' total=%d", self.name, q, len(results))

        return results
