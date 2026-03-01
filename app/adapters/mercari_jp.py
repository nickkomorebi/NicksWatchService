import logging
from typing import TYPE_CHECKING

from app.adapters.base import AdapterError, BaseAdapter, RawListing

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)


def _build_query(watch: "Watch") -> str:
    refs = [r.strip() for r in (watch.references_csv or "").split(",") if r.strip()]
    if refs:
        return f"{watch.brand} {watch.model} {refs[0]}"
    return f"{watch.brand} {watch.model}"


class MercariJpAdapter(BaseAdapter):
    name = "mercari_jp"

    async def search(self, watch: "Watch") -> list[RawListing]:
        try:
            from mercapi import Mercapi
        except ImportError:
            raise AdapterError("mercapi package not installed; run: pip install mercapi")

        query = _build_query(watch)
        try:
            m = Mercapi()
            response = await m.search(query)
        except Exception as exc:
            raise AdapterError(f"Mercari JP search failed: {exc}") from exc

        results = []
        for item in response.items:
            try:
                price = float(item.price) if item.price else None
            except (TypeError, ValueError):
                price = None

            url = f"https://jp.mercari.com/item/{item.id}" if item.id else ""
            results.append(
                RawListing(
                    source=self.name,
                    url=url,
                    title=item.name or "",
                    price_amount=price,
                    currency="JPY",
                    condition=str(item.status) if item.status else None,
                    seller_location=None,
                    image_url=item.thumbnails[0] if item.thumbnails else None,
                    extra_data={"item_id": item.id},
                )
            )

        logger.debug("%s: %d results for '%s'", self.name, len(results), query)
        return results
