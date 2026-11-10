import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from curl_cffi import requests as curl_requests
import redis
from prometheus_client import Counter, Histogram, start_http_server
from sqlalchemy import create_engine, text

from app.parsers.base import ParserLayoutChangedError
from app.parsers.registry import get_parser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scraper-worker")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sarak:sarak_secret_pass@postgres:5432/sarak_db")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
SCRAPE_QUEUE_NAME = os.getenv("SQS_SCRAPE_QUEUE_NAME", "sarak-scrape-queue")
ALERT_QUEUE_NAME = os.getenv("SQS_ALERT_QUEUE_NAME", "sarak-alert-queue")

SCRAPE_SUCCESS = Counter("sarak_scrape_success_total", "Successful product scrapes", ["store"])
PARSER_FAILURES = Counter("sarak_parser_failures_total", "Loud parser failures", ["store", "reason"])
CHECK_LATENCY = Histogram("sarak_check_latency_seconds", "Scrape latency in seconds", ["store"])

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def get_sqs_client():
    return boto3.client("sqs", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)


def respect_store_rate_limit(store: str, min_interval_sec: int = 4):
    key = f"sarak:ratelimit:{store}"
    while not redis_client.set(key, "1", nx=True, ex=min_interval_sec):
        time.sleep(0.5)


def fetch_page(url: str, store: str) -> str:
    cache_key = f"sarak:pagecache:{url}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    respect_store_rate_limit(store)
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
        "Referer": "https://www.amazon.eg/",
    }
    resp = curl_requests.get(
        url,
        impersonate="chrome124",
        headers=headers,
        timeout=15,
        allow_redirects=True,
    )
    if resp.status_code in (403, 429, 503):
        PARSER_FAILURES.labels(store=store, reason=f"http_{resp.status_code}").inc()
        raise RuntimeError(f"Store returned HTTP {resp.status_code} for {url}")
    resp.raise_for_status()
    redis_client.setex(cache_key, 300, resp.text)
    return resp.text


def process_job(sqs, alert_queue_url: str, job: dict):
    product_id = job["product_id"]
    url = job["url"]
    store = job["store"]
    parser = get_parser(store)

    with CHECK_LATENCY.labels(store=store).time():
        try:
            html = fetch_page(url, store)
            scraped = parser.parse(html)
        except ParserLayoutChangedError as exc:
            PARSER_FAILURES.labels(store=store, reason="layout_changed").inc()
            logger.error("LOUD PARSER FAILURE for store=%s url=%s: %s", store, url, exc)
            return

    now = datetime.now(timezone.utc)
    sql_watches = (
        "SELECT w.id, w.target_price, w.last_alerted_price, u.telegram_chat_id "
        "FROM watches w JOIN users u ON u.id = w.user_id "
        "WHERE w.product_id = :id AND w.active = true"
    )
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE products SET title = :title, last_price = :price, last_checked_at = :now WHERE id = :id"),
            {"title": scraped.title, "price": scraped.price, "now": now, "id": product_id},
        )
        conn.execute(
            text("INSERT INTO price_history (product_id, price, checked_at) VALUES (:id, :price, :now)"),
            {"id": product_id, "price": scraped.price, "now": now},
        )
        watches = conn.execute(text(sql_watches), {"id": product_id}).mappings().all()

    SCRAPE_SUCCESS.labels(store=store).inc()

    for w in watches:
        target = float(w["target_price"])
        last_alerted = float(w["last_alerted_price"]) if w["last_alerted_price"] is not None else None
        if scraped.price <= target and (last_alerted is None or scraped.price < last_alerted):
            alert_payload = {
                "watch_id": w["id"],
                "product_id": product_id,
                "title": scraped.title,
                "url": url,
                "store": store,
                "current_price": scraped.price,
                "target_price": target,
                "telegram_chat_id": w["telegram_chat_id"],
            }
            sqs.send_message(QueueUrl=alert_queue_url, MessageBody=json.dumps(alert_payload))
            logger.info("Published price drop alert for product_id=%s at %s EGP", product_id, scraped.price)


def main():
    start_http_server(9101)
    logger.info("Scraper worker started; Prometheus metrics on :9101")
    sqs = get_sqs_client()

    while True:
        try:
            scrape_q = sqs.get_queue_url(QueueName=SCRAPE_QUEUE_NAME)["QueueUrl"]
            alert_q = sqs.get_queue_url(QueueName=ALERT_QUEUE_NAME)["QueueUrl"]
            break
        except Exception as exc:
            logger.warning("Waiting for SQS queues to be ready: %s", exc)
            time.sleep(3)

    while True:
        resp = sqs.receive_message(QueueUrl=scrape_q, MaxNumberOfMessages=5, WaitTimeSeconds=10)
        for msg in resp.get("Messages", []):
            try:
                body = json.loads(msg["Body"])
                process_job(sqs, alert_q, body)
                sqs.delete_message(QueueUrl=scrape_q, ReceiptHandle=msg["ReceiptHandle"])
            except Exception as exc:
                logger.error("Failed processing message: %s", exc)


if __name__ == "__main__":
    main()