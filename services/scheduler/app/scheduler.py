import json
import logging
import os
import time

import boto3
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scheduler")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sarak:sarak_secret_pass@postgres:5432/sarak_db")
AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
SCRAPE_QUEUE_NAME = os.getenv("SQS_SCRAPE_QUEUE_NAME", "sarak-scrape-queue")
RUN_MODE = os.getenv("RUN_MODE", "loop")
INTERVAL_SECONDS = int(os.getenv("SCHEDULE_INTERVAL_SECONDS", "900"))

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def enqueue_due_products():
    sqs = boto3.client("sqs", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)
    queue_url = sqs.get_queue_url(QueueName=SCRAPE_QUEUE_NAME)["QueueUrl"]

    query = (
        "SELECT DISTINCT p.id, p.url, p.store "
        "FROM products p JOIN watches w ON w.product_id = p.id "
        "WHERE w.active = true "
        "AND (p.last_checked_at IS NULL OR p.last_checked_at <= NOW() - INTERVAL '15 minutes')"
    )
    with engine.connect() as conn:
        rows = conn.execute(text(query)).mappings().all()

    for r in rows:
        job = {"product_id": r["id"], "url": r["url"], "store": r["store"]}
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(job))

    logger.info("Enqueued %d products due for price check", len(rows))


def main():
    if RUN_MODE == "once":
        enqueue_due_products()
        return

    while True:
        try:
            enqueue_due_products()
        except Exception as exc:
            logger.warning("Scheduler cycle error: %s", exc)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
