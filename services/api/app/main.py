import json
import logging
import re
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timezone
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Depends, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from app.database import Base, engine, get_db
from app.models import User, Product, Watch, PriceHistory
from app.schemas import ProductCreate, ProductResponse, HistoryPointResponse
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sarak-api")

app = FastAPI(title="Sa'rak API (سعرك)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_REQUESTS = Counter(
    "sarak_api_requests_total",
    "Total HTTP requests processed by Sa'rak API",
    ["method", "endpoint", "status"],
)
PRODUCTS_ADDED = Counter(
    "sarak_products_created_total",
    "Total products registered for price tracking",
    ["store"],
)
API_LATENCY = Histogram(
    "sarak_api_request_latency_seconds",
    "API request latency in seconds",
    ["endpoint"],
)

SUPPORTED_STORES = {
    "amazon.eg": "amazon",
    "www.amazon.eg": "amazon",
    "noon.com": "noon",
    "www.noon.com": "noon",
}

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
    "Referer": "https://www.amazon.eg/",
    "Upgrade-Insecure-Requests": "1",
}


def clean_url(url: str) -> str:
    parsed = urlparse(url.strip())
    asin_match = re.search(r"/(dp|gp/product)/([A-Z0-9]{10})", parsed.path)
    if asin_match and "amazon.eg" in (parsed.hostname or ""):
        clean_path = f"/-/en/dp/{asin_match.group(2)}"
        return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", ""))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def extract_slug_title(url: str, store: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p and p != "p"]
    if store == "noon":
        if len(parts) >= 2:
            return parts[-2].replace("-", " ")[:45]
        elif parts:
            return parts[-1].replace("-", " ")[:45]
    elif parts:
        return parts[-1][:45]
    return "منتج جديد"


def parse_amazon_html(html: str, soup: BeautifulSoup) -> tuple[str | None, float | None]:
    title_el = soup.select_one("#productTitle") or soup.select_one("#title")
    title = title_el.get_text(strip=True) if title_el else None

    if not title and soup.title and soup.title.string:
        raw_t = soup.title.string.split(":")[0].strip()
        if "amazon.eg" not in raw_t.lower() and "captcha" not in raw_t.lower():
            title = raw_t

    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

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
                    return title, val

    json_price = re.search(r'"priceAmount"\s*:\s*(\d+(?:\.\d+)?)', html)
    if json_price and float(json_price.group(1)) > 0:
        return title, float(json_price.group(1))

    return title, None


def parse_noon_html(html: str, soup: BeautifulSoup) -> tuple[str | None, float | None]:
    title = None
    price = None

    h1_el = soup.select_one('h1[data-qa="pdp-name"]') or soup.select_one("h1")
    og_title = soup.select_one('meta[property="og:title"]')
    if h1_el and h1_el.get_text(strip=True):
        title = h1_el.get_text(strip=True)
    elif og_title and og_title.get("content"):
        title = og_title["content"].split("|")[0].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.split("|")[0].strip()

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "{}")
            if data.get("@type") == "Product":
                if not title and data.get("name"):
                    title = str(data["name"]).strip()
                offers = data.get("offers", {})
                if isinstance(offers, list) and offers:
                    offers = offers[0]
                p = offers.get("price") or offers.get("lowPrice")
                if p and float(p) > 0:
                    return title, float(p)
        except Exception:
            pass

    sale_match = re.search(r'"sale_price"\s*:\s*(\d+(?:\.\d+)?)', html)
    if sale_match and float(sale_match.group(1)) > 0:
        return title, float(sale_match.group(1))

    price_json_match = re.search(r'"price"\s*:\s*(\d{3,7}(?:\.\d+)?)', html)
    if price_json_match and float(price_json_match.group(1)) > 0:
        return title, float(price_json_match.group(1))

    text_content = soup.get_text(" ", strip=True)
    egp_match = re.search(r"(?:EGP|ج\.م|جنيه)\s*([\d,]+(?:\.\d+)?)", text_content)
    if egp_match:
        cleaned = egp_match.group(1).replace(",", "")
        if cleaned and float(cleaned) > 0:
            return title, float(cleaned)

    return title, price


def quick_scrape_product(url: str, store: str) -> tuple[str | None, float | None]:
    profiles = ["chrome124", "safari17_0", "edge101"]
    for profile in profiles:
        try:
            with curl_requests.Session(impersonate=profile) as session:
                resp = session.get(
                    url,
                    headers=BROWSER_HEADERS,
                    timeout=15,
                    allow_redirects=True,
                )
                logger.info(
                    "Scraped %s [%s] (profile=%s) -> HTTP %s (bytes=%d)",
                    store, url, profile, resp.status_code, len(resp.text),
                )
                if resp.status_code != 200:
                    continue

                if store == "amazon" and (
                    "validateCaptcha" in resp.text
                    or "api-services-support@amazon.com" in resp.text
                ):
                    logger.warning("Amazon CAPTCHA detected with profile %s, retrying...", profile)
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                if store == "amazon":
                    title, price = parse_amazon_html(resp.text, soup)
                else:
                    title, price = parse_noon_html(resp.text, soup)

                if title or price is not None:
                    return title, price
        except Exception as exc:
            logger.warning("Quick scrape attempt (%s) error for %s: %s", profile, url, exc)

    return None, None


def detect_store(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Invalid URL")
        host = parsed.hostname.lower()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الرابط غير صالح. يرجى إدخال رابط منتج صحيح يبدأ بـ https://",
        )

    for domain, store_name in SUPPORTED_STORES.items():
        if host == domain or host.endswith("." + domain):
            return store_name

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="عفواً، هذا المتجر غير مدعوم حالياً. المتاجر المدعومة هي Amazon.eg و Noon.com فقط.",
    )


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.email == settings.default_user_email).first()
    if not user:
        user = User(
            email=settings.default_user_email,
            password_hash="not_used_in_demo",
            telegram_chat_id=settings.default_telegram_chat_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "sarak-api"}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/products", response_model=list[ProductResponse])
def list_products(db: Session = Depends(get_db)):
    with API_LATENCY.labels(endpoint="/api/products").time():
        user = get_or_create_default_user(db)
        watches = (
            db.query(Watch)
            .filter(Watch.user_id == user.id, Watch.active.is_(True))
            .order_by(Watch.id.desc())
            .all()
        )
        results = []
        for w in watches:
            p = w.product
            hist_prices = [float(h.price) for h in p.history[-20:]]
            if not hist_prices and p.last_price:
                hist_prices = [float(p.last_price)]
            results.append(
                ProductResponse(
                    id=p.id,
                    url=p.url,
                    store=p.store,
                    title=p.title,
                    current_price=float(p.last_price),
                    target_price=float(w.target_price),
                    history=hist_prices,
                )
            )
        API_REQUESTS.labels(method="GET", endpoint="/api/products", status="200").inc()
        return results


@app.post("/api/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    store = detect_store(payload.url)
    normalized_url = clean_url(payload.url)
    user = get_or_create_default_user(db)

    product = db.query(Product).filter(Product.url == normalized_url).first()
    now = datetime.now(timezone.utc)

    if not product:
        scraped_title, scraped_price = quick_scrape_product(normalized_url, store)
        store_title = "Amazon.eg" if store == "amazon" else "Noon.com"
        slug_fallback = extract_slug_title(normalized_url, store)

        final_title = scraped_title or f"منتج من {store_title} ({slug_fallback})"
        final_price = scraped_price if scraped_price is not None else round(float(payload.target_price) * 1.10, 2)

        product = Product(
            url=normalized_url,
            store=store,
            title=final_title[:500],
            last_price=final_price,
            last_checked_at=now if scraped_price is not None else None,
        )
        db.add(product)
        db.flush()

        db.add(PriceHistory(product_id=product.id, price=final_price, checked_at=now))
        PRODUCTS_ADDED.labels(store=store).inc()

    watch = (
        db.query(Watch)
        .filter(Watch.user_id == user.id, Watch.product_id == product.id)
        .first()
    )
    if watch:
        watch.target_price = payload.target_price
        watch.active = True
    else:
        watch = Watch(
            user_id=user.id,
            product_id=product.id,
            target_price=payload.target_price,
            active=True,
        )
        db.add(watch)

    db.commit()
    db.refresh(product)

    hist_prices = [float(h.price) for h in product.history[-20:]]
    API_REQUESTS.labels(method="POST", endpoint="/api/products", status="201").inc()
    return ProductResponse(
        id=product.id,
        url=product.url,
        store=product.store,
        title=product.title,
        current_price=float(product.last_price),
        target_price=float(watch.target_price),
        history=hist_prices,
    )


@app.delete("/api/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="المنتج غير موجود")
    db.delete(product)
    db.commit()
    API_REQUESTS.labels(method="DELETE", endpoint="/api/products/{id}", status="204").inc()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/products/{product_id}/history", response_model=list[HistoryPointResponse])
def get_product_history(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="المنتج غير موجود")
    return [
        HistoryPointResponse(t=h.checked_at, price=float(h.price))
        for h in product.history
    ]