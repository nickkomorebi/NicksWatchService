import logging
from typing import TYPE_CHECKING

import httpx

from app.adapters.base import AdapterError, BaseAdapter, AvailabilityResult, RawListing
from app.config import settings

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

EBAY_AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

_token_cache: dict = {}


async def _get_ebay_token() -> str:
    """Fetch or return cached eBay app-level OAuth token."""
    import base64
    import time

    if _token_cache.get("expires_at", 0) > time.time() + 60:
        return _token_cache["token"]

    credentials = base64.b64encode(
        f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            EBAY_AUTH_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        )
        resp.raise_for_status()

    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 7200))
    return _token_cache["token"]


def _build_queries(watch: "Watch") -> list[str]:
    """Build eBay search queries. Uses brand+ref for each reference (more precise
    than brand+model+ref which often matches nothing), falling back to brand+model."""
    refs = [r.strip() for r in (watch.references_csv or "").split(",") if r.strip()]
    terms = [t.strip() for t in (watch.query_terms or "").split(",") if t.strip()]
    queries = []
    for ref in refs:
        queries.append(f"{watch.brand} {ref}")
    for term in terms:
        queries.append(term)
    if not queries:
        queries.append(f"{watch.brand} {watch.model}")
    seen: set[str] = set()
    return [q for q in queries if not (q in seen or seen.add(q))]


class EbayAdapter(BaseAdapter):
    name = "ebay"

    async def search(self, watch: "Watch") -> list[RawListing]:
        if not settings.ebay_client_id or not settings.ebay_client_secret:
            raise AdapterError("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not configured")

        try:
            token = await _get_ebay_token()
        except httpx.HTTPError as exc:
            raise AdapterError(f"eBay auth failed: {exc}") from exc

        seen_urls: set[str] = set()
        all_results: list[RawListing] = []

        for query in _build_queries(watch):
            params = {
                "q": query,
                "category_ids": "281",  # Watches category
                "filter": "conditions:{USED}",
                "limit": "50",
                "sort": "newlyListed",
            }

            async with httpx.AsyncClient(timeout=20) as client:
                try:
                    resp = await client.get(
                        EBAY_BROWSE_URL,
                        params=params,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                        },
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise AdapterError(f"eBay Browse API failed: {exc}") from exc

            for item in resp.json().get("itemSummaries", []):
                url = item.get("itemWebUrl", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                price_info = item.get("price", {})
                try:
                    price = float(price_info.get("value", 0))
                except (TypeError, ValueError):
                    price = None
                all_results.append(
                    RawListing(
                        source=self.name,
                        url=url,
                        title=item.get("title", ""),
                        price_amount=price,
                        currency=price_info.get("currency"),
                        condition=item.get("condition"),
                        seller_location=item.get("itemLocation", {}).get("country"),
                        image_url=(item.get("image") or {}).get("imageUrl"),
                        extra_data={"itemId": item.get("itemId")},
                    )
                )

        logger.debug("%s: %d results for '%s'", self.name, len(all_results), watch.brand)
        return all_results

    async def check_availability(self, url: str) -> AvailabilityResult:
        # eBay item URLs contain itemId; we rely on last_seen_at staleness in job_runner
        return AvailabilityResult(is_active=True)
