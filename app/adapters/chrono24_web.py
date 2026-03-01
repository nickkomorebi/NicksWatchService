"""Chrono24 adapter that sources listings via Serper site:chrono24.com search.

The official chrono24 PyPI package is blocked by Cloudflare.  This adapter
uses the Serper Google-search API to find individual Chrono24 listing pages
(URLs containing '--id<number>') and parses price from the snippet text.
"""
import logging
import re
from typing import TYPE_CHECKING

import httpx

from app.adapters.base import AdapterError, BaseAdapter, RawListing
from app.config import settings

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"

# Regex: URL must contain --id followed by digits to be an individual listing
_LISTING_RE = re.compile(r"--id\d+")

# Price extraction patterns from Chrono24 snippet text
# e.g. "Listing: $32,500", "Price, €4,800", "$10,447.", "C$15,950"
_PRICE_RE = re.compile(
    r"(?:Listing\s*:\s*|Price[,\s]+)?"      # optional prefix
    r"(C\$|US\$|A\$|HK\$|\$|€|£|¥|CHF\s*)"  # currency symbol
    r"([\d,]+(?:\.\d+)?)",                   # amount
    re.IGNORECASE,
)
_CURRENCY_MAP = {
    "$": "USD", "us$": "USD", "c$": "CAD", "a$": "AUD",
    "hk$": "HKD", "€": "EUR", "£": "GBP", "¥": "JPY", "chf": "CHF",
}


def _parse_price(snippet: str) -> tuple[float | None, str | None]:
    """Extract the first price and currency from a Chrono24 snippet."""
    m = _PRICE_RE.search(snippet)
    if not m:
        return None, None
    sym = m.group(1).strip().lower()
    amount_str = m.group(2).replace(",", "")
    try:
        amount = float(amount_str)
    except ValueError:
        return None, None
    currency = _CURRENCY_MAP.get(sym, "USD")
    return amount, currency


_GENERIC_WORDS = {
    "used", "new", "watch", "watches", "automatic", "manual", "quartz",
    "gold", "steel", "silver", "leather", "bracelet", "strap", "set",
    "for", "sale", "and", "with", "the", "a", "an",
}


def _core_model(model: str) -> str:
    """Return the first meaningful word(s) of a model name, stripping generic descriptors.

    E.g. "Reverso Gold Bracelet" → "Reverso"
         "Polaris II (cranberry red color)" → "Polaris II"
         "Speedbeat GT" → "Speedbeat GT"
    """
    # Drop everything from first parenthesis
    model = model.split("(")[0].strip()
    words = model.split()
    core = []
    for w in words:
        if w.lower() in _GENERIC_WORDS:
            break
        core.append(w)
        if len(core) >= 2:
            break
    return " ".join(core) if core else words[0]


def _brand_variants(brand: str) -> list[str]:
    """Return both the space-separated and hyphen-separated forms of a brand name."""
    hyphenated = brand.replace(" ", "-")
    variants = [hyphenated]
    if hyphenated != brand:
        variants.append(brand)
    return variants


def _build_queries(watch: "Watch") -> list[str]:
    """Build up to 2 site:chrono24.com queries for a watch."""
    refs = [r.strip() for r in (watch.references_csv or "").split(",") if r.strip()]
    core = _core_model(watch.model)
    queries: list[str] = []

    for brand in _brand_variants(watch.brand):
        if refs:
            # Reference + brand is the most targeted query
            queries.append(f'site:chrono24.com "{brand}" "{refs[0]}"')
        else:
            queries.append(f'site:chrono24.com "{brand}" "{core}"')
        if len(queries) >= 2:
            break

    # If only one variant, add a core-model fallback as a second query
    if len(queries) == 1 and refs:
        queries.append(f'site:chrono24.com "{_brand_variants(watch.brand)[0]}" "{core}"')

    return queries[:2]


class Chrono24WebAdapter(BaseAdapter):
    name = "chrono24"  # Same source name as old adapter for deduplication

    async def search(self, watch: "Watch") -> list[RawListing]:
        if not settings.serper_api_key:
            raise AdapterError("SERPER_API_KEY not configured")

        seen_urls: set[str] = set()
        results: list[RawListing] = []

        headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=20) as client:
            for query in _build_queries(watch):
                payload = {"q": query, "num": 20}
                try:
                    resp = await client.post(SERPER_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise AdapterError(f"Serper request failed: {exc}") from exc

                for item in resp.json().get("organic", []):
                    url = item.get("link", "")
                    # Only individual listing pages — skip category / magazine pages
                    if not _LISTING_RE.search(url):
                        continue
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    snippet = item.get("snippet", "")
                    price, currency = _parse_price(snippet)

                    results.append(
                        RawListing(
                            source=self.name,
                            url=url,
                            title=item.get("title", ""),
                            price_amount=price,
                            currency=currency,
                            condition="Pre-owned",
                            seller_location=None,
                            image_url=None,
                            extra_data={"snippet": snippet},
                        )
                    )

        logger.debug("chrono24_web: %d listings for '%s %s'", len(results), watch.brand, watch.model)
        return results
