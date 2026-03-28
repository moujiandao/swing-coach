"""
Migrate static .npz pro reference files into the pro_references DB table.

For each .npz in backend/app/pro_references/data/, creates a ProReference
record with status=ready and is_builtin=True. Idempotent — skips files whose
derived player_slug already exists in the DB.

Usage:
    cd /path/to/swing-coach-mvp
    python scripts/migrate_static_references.py

Set DATABASE_URL env var to target a non-default DB; defaults to the SQLite
dev.db used by alembic.ini.
"""
import asyncio
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Make backend/app importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, ProReference, ProReferenceStatus, StrokeType, slugify

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "backend" / "app" / "pro_references" / "data"

# Map filename stems to StrokeType values. Extend as new static files are added.
_STROKE_ALIASES: dict[str, str] = {
    "forehand": "forehand",
    "backhand_one": "backhand_one",
    "backhand_two": "backhand_two",
    "serve_flat": "serve_flat",
    "serve_kick": "serve_kick",
    "serve_slice": "serve_slice",
    "volley": "volley",
}


def _parse_filename(stem: str) -> tuple[str, StrokeType] | None:
    """
    Derive (player_name, StrokeType) from an .npz filename stem.

    Expected patterns:
      "federer_forehand"        -> ("Federer", forehand)
      "synthetic_forehand"      -> ("Synthetic", forehand)
      "alcaraz_serve_flat"      -> ("Alcaraz", serve_flat)

    Returns None if no recognised stroke suffix is found.
    """
    stem = stem.lower()
    for suffix, stroke_value in sorted(_STROKE_ALIASES.items(), key=lambda x: -len(x[0])):
        if stem.endswith(f"_{suffix}"):
            player_raw = stem[: -(len(suffix) + 1)]
            player_name = player_raw.replace("_", " ").title()
            return player_name, StrokeType(stroke_value)
    logger.warning("Could not parse stroke type from filename: %s — skipping", stem)
    return None


async def _unique_slug(session, base_slug: str) -> str:
    """Return base_slug if unused, otherwise append -2, -3, etc. until unique."""
    candidate = base_slug
    counter = 2
    while True:
        result = await session.execute(
            select(ProReference).where(ProReference.player_slug == candidate)
        )
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base_slug}-{counter}"
        counter += 1


async def migrate(db_url: str) -> None:
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Ensure tables exist (safe to call repeatedly — CREATE TABLE IF NOT EXISTS)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    npz_files = sorted(DATA_DIR.glob("*.npz"))
    if not npz_files:
        logger.warning("No .npz files found in %s — nothing to migrate", DATA_DIR)
        await engine.dispose()
        return

    logger.info("Found %d .npz file(s) in %s", len(npz_files), DATA_DIR)
    created = skipped = 0

    async with factory() as session:
        for npz_path in npz_files:
            parsed = _parse_filename(npz_path.stem)
            if parsed is None:
                skipped += 1
                continue

            player_name, stroke_type = parsed
            base_slug = f"{slugify(player_name)}-{stroke_type.value.replace('_', '-')}"

            # Check whether this exact (slug pattern) already exists
            existing = await session.execute(
                select(ProReference).where(
                    ProReference.npz_path == str(npz_path)
                )
            )
            if existing.scalar_one_or_none() is not None:
                logger.info("Already migrated: %s — skipping", npz_path.name)
                skipped += 1
                continue

            slug = await _unique_slug(session, base_slug)

            record = ProReference(
                id=uuid.uuid4(),
                player_name=player_name,
                player_slug=slug,
                stroke_type=stroke_type,
                npz_path=str(npz_path),
                status=ProReferenceStatus.ready,
                is_builtin=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(record)
            logger.info("Creating record: %s (%s) → %s", player_name, stroke_type.value, slug)
            created += 1

        await session.commit()

    logger.info("Migration complete — created: %d, skipped: %d", created, skipped)
    await engine.dispose()


if __name__ == "__main__":
    db_url = os.environ.get(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'backend' / 'dev.db'}",
    )
    logger.info("Targeting DB: %s", db_url.split("?")[0])
    asyncio.run(migrate(db_url))
