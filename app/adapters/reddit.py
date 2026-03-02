import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from app.adapters.base import AdapterError, BaseAdapter, RawListing, build_queries

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

REDDIT_SEARCH_URL = "https://www.reddit.com/r/watchexchange/search.json"
USER_AGENT = "python:nickswatch:v1.0"
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)


def _is_wts(post: dict) -> bool:
    flair = (post.get("link_flair_text") or "").upper()
    title = (post.get("title") or "").upper()
    return "WTS" in flair or title.startswith("[WTS")


def _parse_price(title: str) -> float | None:
    m = _PRICE_RE.search(title)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


class RedditAdapter(BaseAdapter):
    name = "reddit"

    async def search(self, watch: "Watch") -> list[RawListing]:
        seen: set[str] = set()
        results: list[RawListing] = []
        headers = {"User-Agent": USER_AGENT}

        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            for i, query in enumerate(build_queries(watch)):
                if i > 0:
                    await asyncio.sleep(7)  # stay under 10 req/min

                try:
                    resp = await client.get(
                        REDDIT_SEARCH_URL,
                        params={"q": query, "restrict_sr": "1", "sort": "new", "limit": 100},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise AdapterError(f"Reddit request failed: {exc}") from exc

                for child in resp.json().get("data", {}).get("children", []):
                    post = child.get("data", {})
                    if not _is_wts(post):
                        continue

                    url = f"https://www.reddit.com{post.get('permalink', '')}"
                    if url in seen:
                        continue
                    seen.add(url)

                    created_utc = post.get("created_utc")
                    listed_at = (
                        datetime.fromtimestamp(created_utc, tz=timezone.utc)
                        if created_utc else None
                    )

                    title = post.get("title", "")
                    price = _parse_price(title)
                    results.append(RawListing(
                        source=self.name,
                        url=url,
                        title=title,
                        price_amount=price,
                        currency="USD" if price else None,
                        condition=None,
                        seller_location=None,
                        image_url=None,
                        listed_at=listed_at,
                        extra_data={
                            "author": post.get("author"),
                            "flair": post.get("link_flair_text"),
                            "score": post.get("score"),
                        },
                    ))

                logger.debug("reddit: query='%s' total=%d", query, len(results))

        return results
