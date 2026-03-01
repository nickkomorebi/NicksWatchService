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


class Chrono24Adapter(BaseAdapter):
    name = "chrono24"

    async def search(self, watch: "Watch") -> list[RawListing]:
        try:
            import chrono24
        except ImportError:
            raise AdapterError("chrono24 package not installed; run: pip install chrono24")

        query = _build_query(watch)
        try:
            listings = chrono24.query(query)
        except Exception as exc:
            raise AdapterError(f"Chrono24 query failed: {exc}") from exc

        results = []
        for item in listings:
            try:
                price = float(item.get("price", 0) or 0) or None
            except (TypeError, ValueError):
                price = None

            results.append(
                RawListing(
                    source=self.name,
                    url=item.get("url", ""),
                    title=item.get("title") or item.get("name", ""),
                    price_amount=price,
                    currency=item.get("currency"),
                    condition=item.get("condition"),
                    seller_location=item.get("location") or item.get("sellerLocation"),
                    image_url=item.get("imageUrl") or item.get("image"),
                    extra_data={
                        k: v
                        for k, v in item.items()
                        if k not in ("url", "title", "name", "price", "currency", "condition", "imageUrl", "image")
                    },
                )
            )

        logger.debug("%s: %d results for '%s'", self.name, len(results), query)
        return results
