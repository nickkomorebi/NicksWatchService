"""Chrono24 adapter.

Primary path:  FlareSolverr (http://localhost:8191) → full HTML scrape.
Fallback path: Serper site:chrono24.com search (fewer results, no images).

FlareSolverr bypasses Cloudflare so we get the real rendered page with
images, prices, and ~120 listings per query — the same set a browser sees.
"""
import logging
import re
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import AdapterError, BaseAdapter, RawListing, build_queries
from app.config import settings

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

FLARESOLVERR_URL = "http://localhost:8191/v1"  # overridden at call-time by settings
CHRONO24_BASE = "https://www.chrono24.com"
SERPER_URL = "https://google.serper.dev/search"
PAGE_SIZE = 120

_LISTING_RE = re.compile(r"--id\d+")
_PRICE_RE = re.compile(
    r"^(C\$|US\$|A\$|HK\$|\$|€|£|¥|CHF\s?)([\d,]+(?:\.\d+)?)$"
)
_CURRENCY_MAP = {
    "$": "USD", "us$": "USD", "c$": "CAD", "a$": "AUD",
    "hk$": "HKD", "€": "EUR", "£": "GBP", "¥": "JPY", "chf": "CHF",
}

# Serper fallback helpers (kept from previous implementation)
_SNIPPET_PRICE_RE = re.compile(
    r"(?:Listing\s*:\s*|Price[,\s]+)?"
    r"(C\$|US\$|A\$|HK\$|\$|€|£|¥|CHF\s?)"
    r"([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_GENERIC_WORDS = {
    "used", "new", "watch", "watches", "automatic", "manual", "quartz",
    "gold", "steel", "silver", "leather", "bracelet", "strap", "set",
    "for", "sale", "and", "with", "the", "a", "an",
}


# ── FlareSolverr helpers ──────────────────────────────────────────────────────

def _parse_price_text(text: str) -> tuple[float | None, str | None]:
    m = _PRICE_RE.match(text.strip())
    if not m:
        return None, None
    sym = m.group(1).strip().lower()
    try:
        amount = float(m.group(2).replace(",", ""))
    except ValueError:
        return None, None
    return amount, _CURRENCY_MAP.get(sym, "USD")


def _parse_card(card) -> RawListing | None:
    """Extract a RawListing from a single Chrono24 search-result div."""
    link = card.find("a", href=_LISTING_RE)
    if not link:
        return None

    href = link.get("href", "")
    url = href if href.startswith("http") else CHRONO24_BASE + href

    # First non-lazy CDN image
    img_url = None
    for img in card.find_all("img", src=re.compile(r"img\.chrono24\.com")):
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            img_url = src
            break

    # Text lines (skip carousel nav labels)
    lines = [
        t for t in card.get_text(separator="\n", strip=True).split("\n")
        if t and "go to slide" not in t.lower()
    ]

    # First two lines are brand-family + model descriptor → full title
    title = " ".join(lines[:2]) if len(lines) >= 2 else (lines[0] if lines else "")

    price, currency, location = None, None, None
    for line in lines[2:]:
        if price is None:
            p, c = _parse_price_text(line)
            if p is not None:
                price, currency = p, c
                continue
        if re.match(r"^[A-Z]{2}$", line):
            location = line

    return RawListing(
        source="chrono24",
        url=url,
        title=title,
        price_amount=price,
        currency=currency,
        condition="Pre-owned",
        seller_location=location,
        image_url=img_url,
        extra_data={},
    )


async def _search_via_flaresolverr(watch: "Watch") -> list[RawListing]:
    """Fetch Chrono24 search via FlareSolverr for each query, return deduplicated listings."""
    seen: set[str] = set()
    results: list[RawListing] = []

    async with httpx.AsyncClient(timeout=90) as client:
        for query in build_queries(watch):
            search_url = (
                f"{CHRONO24_BASE}/search/index.htm"
                f"?dosearch=true&query={query.replace(' ', '+')}"
                f"&usedOrNew=used&sortorder=5&pageSize={PAGE_SIZE}&showPage=1"
            )
            try:
                resp = await client.post(
                    f"{settings.flaresolverr_url}/v1",
                    json={"cmd": "request.get", "url": search_url, "maxTimeout": 60000},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(f"FlareSolverr request failed: {exc}") from exc

            data = resp.json()
            if data.get("status") != "ok":
                raise RuntimeError(f"FlareSolverr returned status={data.get('status')}")

            html = data["solution"]["response"]
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("[class*='wt-search-result']")
            logger.debug("chrono24 FlareSolverr: %d cards for '%s'", len(cards), query)

            for card in cards:
                listing = _parse_card(card)
                if listing and listing.url not in seen:
                    seen.add(listing.url)
                    results.append(listing)

    return results


# ── Serper fallback helpers ───────────────────────────────────────────────────

def _core_model(model: str) -> str:
    model = model.split("(")[0].strip()
    words = model.split()
    core = []
    for w in words:
        if w.lower() in _GENERIC_WORDS:
            break
        core.append(w)
        if len(core) >= 2:
            break
    return " ".join(core) if core else (words[0] if words else model)


def _brand_variants(brand: str) -> list[str]:
    hyphenated = brand.replace(" ", "-")
    return [hyphenated] if hyphenated == brand else [hyphenated, brand]


def _build_serper_queries(watch: "Watch") -> list[str]:
    brand = _brand_variants(watch.brand)[0]
    core = _core_model(watch.model)
    queries: list[str] = [f'site:chrono24.com "{brand}" "{core}"']
    for q in build_queries(watch)[1:]:  # skip brand+model (already covered above)
        queries.append(f'site:chrono24.com "{brand}" "{q}"')
    seen: set[str] = set()
    return [q for q in queries if not (q in seen or seen.add(q))]


def _parse_snippet_price(snippet: str) -> tuple[float | None, str | None]:
    m = _SNIPPET_PRICE_RE.search(snippet)
    if not m:
        return None, None
    sym = m.group(1).strip().lower()
    try:
        amount = float(m.group(2).replace(",", ""))
    except ValueError:
        return None, None
    return amount, _CURRENCY_MAP.get(sym, "USD")


async def _search_via_serper(watch: "Watch") -> list[RawListing]:
    """Fallback: find Chrono24 individual listings via Serper site: search."""
    if not settings.serper_api_key:
        return []

    seen: set[str] = set()
    results: list[RawListing] = []
    headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=20) as client:
        for query in _build_serper_queries(watch):
            try:
                resp = await client.post(SERPER_URL, json={"q": query, "num": 20}, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError:
                continue

            for item in resp.json().get("organic", []):
                url = item.get("link", "")
                if not _LISTING_RE.search(url) or url in seen:
                    continue
                seen.add(url)
                snippet = item.get("snippet", "")
                price, currency = _parse_snippet_price(snippet)
                results.append(RawListing(
                    source="chrono24",
                    url=url,
                    title=item.get("title", ""),
                    price_amount=price,
                    currency=currency,
                    condition="Pre-owned",
                    seller_location=None,
                    image_url=None,
                    extra_data={"snippet": snippet},
                ))

    logger.debug("chrono24 Serper fallback: %d listings for '%s %s'",
                 len(results), watch.brand, watch.model)
    return results


# ── Adapter ───────────────────────────────────────────────────────────────────

class Chrono24WebAdapter(BaseAdapter):
    name = "chrono24"

    async def search(self, watch: "Watch") -> list[RawListing]:
        # Try FlareSolverr first
        try:
            results = await _search_via_flaresolverr(watch)
            if results:
                return results
            logger.debug("chrono24: FlareSolverr returned 0 results, trying Serper fallback")
        except Exception as exc:
            logger.info("chrono24: FlareSolverr unavailable (%s), falling back to Serper", exc)

        # Fallback to Serper site: search
        if not settings.serper_api_key:
            raise AdapterError("FlareSolverr unavailable and SERPER_API_KEY not configured")
        return await _search_via_serper(watch)
