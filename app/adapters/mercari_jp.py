import logging
from typing import TYPE_CHECKING

from app.adapters.base import AdapterError, BaseAdapter, RawListing, build_queries

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)


class MercariJpAdapter(BaseAdapter):
    name = "mercari_jp"

    async def search(self, watch: "Watch") -> list[RawListing]:
        try:
            from mercapi import Mercapi
        except ImportError:
            raise AdapterError("mercapi package not installed; run: pip install mercapi")

        seen: set[str] = set()
        results: list[RawListing] = []
        m = Mercapi()

        for query in build_queries(watch):
            try:
                response = await m.search(query)
            except Exception as exc:
                raise AdapterError(f"Mercari JP search failed: {exc}") from exc

            for item in response.items:
                item_id = getattr(item, "id_", None) or getattr(item, "id", None)
                url = f"https://jp.mercari.com/item/{item_id}" if item_id else ""
                if url in seen:
                    continue
                seen.add(url)
                try:
                    price = float(item.price) if item.price else None
                except (TypeError, ValueError):
                    price = None
                results.append(RawListing(
                    source=self.name,
                    url=url,
                    title=item.name or "",
                    price_amount=price,
                    currency="JPY",
                    condition=str(item.status) if item.status else None,
                    seller_location=None,
                    image_url=item.thumbnails[0] if item.thumbnails else None,
                    extra_data={"item_id": item_id},
                ))
            logger.debug("%s: query='%s' total=%d", self.name, query, len(results))

        return results
