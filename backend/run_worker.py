"""
Start the RQ worker.

Usage (from backend/):
    uv run python run_worker.py
"""
import logging

from redis import Redis
from rq import Queue, Worker

from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

settings = get_settings()
redis = Redis.from_url(settings.redis_url)
queue = Queue(connection=redis)
worker = Worker([queue], connection=redis)

if __name__ == "__main__":
    logging.getLogger(__name__).info(
        "Starting RQ worker — redis=%s", settings.redis_url
    )
    worker.work()
