import json
import re
from bs4 import BeautifulSoup
from app.parsers.base import BaseStoreParser, ScrapedProduct, ParserLayoutChangedError


class NoonEgParser(BaseStoreParser):
    store_name = "noon"

    def parse(self, html: str) -> ScrapedProduct:
        soup = BeautifulSoup(html, "html.parser")

        # 1. فحص Next.js Data JSON (أدق مصدر في نون)
        next_script = soup.select_one("script#__NEXT_DATA__")
        if next_script and next_script.string:
            try:
                data = json.loads(next_script.string)
                page_props = data.get("props", {}).get("pageProps", {})
                product = (
                    page_props.get("catalog", {}).get("product")
                    or page_props.get("product")
                    or page_props.get("productData")
                )
                if product:
                    title = product.get("name") or product.get("title")
                    price = product.get("sale_price") or product.get("price")
                    if title and price:
                        return ScrapedProduct(title=str(title).strip(), price=float(price))
            except Exception:
                pass

        # 2. فحص JSON-LD
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "{}")
                if data.get("@type") == "Product" and "offers" in data:
                    title = data.get("name", "").strip()
                    offers = data.get("offers", {})
                    price = offers.get("price") or offers.get("lowPrice")
                    if title and price:
                        return ScrapedProduct(title=title, price=float(price))
            except Exception:
                continue

        # 3. فحص الـ Selectors العادية
        title_el = soup.select_one('h1[data-qa="pdp-name"]') or soup.select_one("h1")
        price_el = (
            soup.select_one('[data-qa="div-price-now"]')
            or soup.select_one(".priceNow")
            or soup.select_one('[class*="priceNow"]')
            or soup.select_one('[class*="sellingPrice"]')
        )

        if not title_el or not price_el:
            raise ParserLayoutChangedError(
                "Noon.com layout changed: missing product title or price element"
            )

        title = title_el.get_text(strip=True)
        raw_price = re.sub(r"[^\d.]", "", price_el.get_text(strip=True).replace(",", ""))
        if not raw_price:
            raise ParserLayoutChangedError("Noon.com could not extract numeric price")

        return ScrapedProduct(title=title, price=float(raw_price))