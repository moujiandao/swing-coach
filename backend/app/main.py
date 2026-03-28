import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import analysis, health, pro_references, upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("SwingCoach backend starting up")
    logger.info("Allowed origins: %s", settings.allowed_origins_list)
    yield
    logger.info("SwingCoach backend shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="SwingCoach API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(upload.router, prefix="/api")
    app.include_router(analysis.router, prefix="/api")
    app.include_router(pro_references.router, prefix="/api")

    # In local dev (no S3), serve uploaded videos and keyframes over HTTP so the
    # frontend can load them.  The StaticFiles mount must come after API routers
    # so that /api/* routes are not shadowed.
    if not settings.s3_bucket:
        uploads_dir = Path("uploads")
        uploads_dir.mkdir(exist_ok=True)
        app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
        logger.info("Local dev — serving /uploads from %s", uploads_dir.resolve())

    return app


app = create_app()
