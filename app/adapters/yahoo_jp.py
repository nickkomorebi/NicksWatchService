import logging
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from app.adapters.base import AdapterError, BaseAdapter, RawListing

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)

YAHOO_AUCTION_URL = "https://auctions.yahoo.co.jp/search/search"


def _build_query(watch: "Watch") -> str:
    refs = [r.strip() for r in (watch.references_csv or "").split(",") if r.strip()]
    if refs:
        return f"{watch.brand} {watch.model} {refs[0]}"
    return f"{watch.brand} {watch.model}"


class YahooJpAdapter(BaseAdapter):
    name = "yahoo_jp"

    async def search(self, watch: "Watch") -> list[RawListing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise AdapterError("playwright not installed; run: pip install playwright && playwright install chromium")

        query = _build_query(watch)
        url = f"{YAHOO_AUCTION_URL}?p={quote_plus(query)}&auccat=&tab_ex=commerce&ei=utf-8&aq=-1&oq=&sc_i=&fr=auc_top&x=0&y=0&istatus=1"

        results = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector("li.Product", timeout=15000)

                items = await page.query_selector_all("li.Product")
                for item in items[:40]:
                    title_el = await item.query_selector(".Product__title")
                    title = (await title_el.inner_text()).strip() if title_el else ""

                    link_el = await item.query_selector("a.Product__titleLink")
                    href = await link_el.get_attribute("href") if link_el else ""

                    price_el = await item.query_selector(".Product__price")
                    price_text = (await price_el.inner_text()).strip() if price_el else ""
                    try:
                        price = float(price_text.replace(",", "").replace("円", "").strip())
                    except (ValueError, TypeError):
                        price = None

                    img_el = await item.query_selector("img.Product__imageData")
                    img_src = await img_el.get_attribute("src") if img_el else None

                    if href:
                        results.append(
                            RawListing(
                                source=self.name,
                                url=href,
                                title=title,
                                price_amount=price,
                                currency="JPY",
                                condition=None,
                                seller_location="Japan",
                                image_url=img_src,
                                extra_data={},
                            )
                        )

                await browser.close()
        except Exception as exc:
            raise AdapterError(f"Yahoo JP scrape failed: {exc}") from exc

        logger.debug("%s: %d results for '%s'", self.name, len(results), query)
        return results
