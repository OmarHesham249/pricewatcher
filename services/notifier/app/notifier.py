import json
import logging
import os
import time

import boto3
import httpx
from prometheus_client import Counter, start_http_server
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notifier")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sarak:sarak_secret_pass@postgres:5432/sarak_db")
AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
ALERT_QUEUE_NAME = os.getenv("SQS_ALERT_QUEUE_NAME", "sarak-alert-queue")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "dummy_token_for_now")

ALERTS_SENT = Counter("sarak_alerts_sent_total", "Total Telegram price alerts sent", ["store"])

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def send_telegram_alert(chat_id: str, title: str, price: float, target: float, url: str):
    message = (
        f"🎯 *تنبيه انخفاض سعر من سِعرك (Sa'rak)!*\n\n"
        f"📦 *المنتج:* {title}\n"
        f"💰 *السعر الحالي:* {price:,.2f} ج.م\n"
        f"🎯 *سعرك المستهدف:* {target:,.2f} ج.م\n\n"
        f"🔗 [افتح صفحة المنتج الآن]({url})"
    )
    if TELEGRAM_BOT_TOKEN == "dummy_token_for_now" or not chat_id:
        logger.info("[DRY-RUN Telegram Alert] To=%s: %s", chat_id, message.replace("\n", " "))
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            api_url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
        )
        resp.raise_for_status()


def process_alert(alert: dict):
    watch_id = alert["watch_id"]
    price = float(alert["current_price"])

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT last_alerted_price FROM watches WHERE id = :id"),
            {"id": watch_id},
        ).mappings().first()

        if not row:
            return
        last_alerted = float(row["last_alerted_price"]) if row["last_alerted_price"] is not None else None
        if last_alerted is not None and price >= last_alerted:
            logger.info("Skipping duplicate alert for watch_id=%s at price=%s", watch_id, price)
            return

        send_telegram_alert(
            chat_id=alert.get("telegram_chat_id", ""),
            title=alert["title"],
            price=price,
            target=float(alert["target_price"]),
            url=alert["url"],
        )

        conn.execute(
            text("UPDATE watches SET last_alerted_price = :price WHERE id = :id"),
            {"price": price, "id": watch_id},
        )
        ALERTS_SENT.labels(store=alert.get("store", "unknown")).inc()


def main():
    start_http_server(9102)
    logger.info("Notifier started; Prometheus metrics on :9102")
    sqs = boto3.client("sqs", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)

    while True:
        try:
            alert_q = sqs.get_queue_url(QueueName=ALERT_QUEUE_NAME)["QueueUrl"]
            break
        except Exception as exc:
            logger.warning("Waiting for alert queue: %s", exc)
            time.sleep(3)

    while True:
        resp = sqs.receive_message(QueueUrl=alert_q, MaxNumberOfMessages=5, WaitTimeSeconds=10)
        for msg in resp.get("Messages", []):
            try:
                process_alert(json.loads(msg["Body"]))
                sqs.delete_message(QueueUrl=alert_q, ReceiptHandle=msg["ReceiptHandle"])
            except Exception as exc:
                logger.error("Alert processing error: %s", exc)


if __name__ == "__main__":
    main()
