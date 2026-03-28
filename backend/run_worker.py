"""
Start the RQ worker.

Usage (from backend/):
    uv run python run_worker.py
"""
import logging
import platform

from redis import Redis
from rq import Queue, SimpleWorker, Worker

from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# macOS: use SimpleWorker (no fork) to avoid Obj-C runtime crash in forked processes
WorkerClass = SimpleWorker if platform.system() == "Darwin" else Worker

settings = get_settings()
redis = Redis.from_url(settings.redis_url)
queue = Queue(connection=redis)
worker = WorkerClass([queue], connection=redis)

if __name__ == "__main__":
    logging.getLogger(__name__).info(
        "Starting RQ worker — redis=%s", settings.redis_url
    )
    worker.work()
