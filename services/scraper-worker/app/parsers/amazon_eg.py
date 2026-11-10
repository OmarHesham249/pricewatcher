import re
from bs4 import BeautifulSoup
from app.parsers.base import BaseStoreParser, ScrapedProduct, ParserLayoutChangedError


class AmazonEgParser(BaseStoreParser):
    store_name = "amazon"

    def parse(self, html: str) -> ScrapedProduct:
        soup = BeautifulSoup(html, "html.parser")

        if (
            soup.select_one("form[action*='validateCaptcha']")
            or "api-services-support@amazon.com" in html
        ):
            raise ParserLayoutChangedError(
                "Amazon.eg returned a CAPTCHA challenge page instead of product HTML"
            )

        title_el = soup.select_one("#productTitle") or soup.select_one("#title")
        title = title_el.get_text(strip=True) if title_el else None
        if not title and soup.title and soup.title.string:
            raw_t = soup.title.string.split(":")[0].strip()
            if "amazon.eg" not in raw_t.lower() and "captcha" not in raw_t.lower():
                title = raw_t

        if not title:
            raise ParserLayoutChangedError("Amazon.eg missing product title")

        arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        price = None

        price_selectors = [
            "#corePriceDisplay_desktop_feature_div .priceToPay .a-price-whole",
            "#corePrice_feature_div .priceToPay .a-price-whole",
            "#apex_desktop .priceToPay .a-price-whole",
            ".priceToPay .a-price-whole",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            "#corePrice_feature_div .a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            ".a-price-whole",
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True).translate(arabic_digits)
                m = re.search(r"([\d,]+(?:\.\d+)?)", txt.replace("٬", ","))
                if m:
                    val = float(m.group(1).replace(",", ""))
                    if val > 0:
                        price = val
                        break

        if price is None:
            json_price = re.search(r'"priceAmount"\s*:\s*(\d+(?:\.\d+)?)', html)
            if json_price and float(json_price.group(1)) > 0:
                price = float(json_price.group(1))

        if price is None or price <= 0:
            raise ParserLayoutChangedError("Amazon.eg could not parse valid numeric price")

        return ScrapedProduct(title=title, price=price)