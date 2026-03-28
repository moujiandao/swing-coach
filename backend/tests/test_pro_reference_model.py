"""
Tests for ProReference model, slug utilities, ProReferenceDB DB-backed methods,
and the migrate_static_references script.

Acceptance criteria covered:
- ProReference CRUD with async SQLAlchemy
- Slug generation and uniqueness
- ProReferenceDB.list_available_from_db / get_by_id
- Migration script creates correct records from existing .npz files
"""
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Base,
    ProReference,
    ProReferenceCreate,
    ProReferenceListItem,
    ProReferenceResponse,
    ProReferenceStatus,
    StrokeType,
    slugify,
)
from app.pro_references.loader import ProReferenceDB

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def make_engine():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def sample_pro_reference(**kwargs) -> ProReference:
    defaults = dict(
        id=uuid.uuid4(),
        player_name="Roger Federer",
        player_slug="roger-federer-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.ready,
        is_builtin=True,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return ProReference(**defaults)


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def test_slugify_basic():
    assert slugify("Roger Federer") == "roger-federer"


def test_slugify_special_chars():
    assert slugify("Carlos Alcaraz") == "carlos-alcaraz"


def test_slugify_multiple_spaces():
    assert slugify("Rafael  Nadal") == "rafael-nadal"


def test_slugify_already_slug():
    assert slugify("federer") == "federer"


def test_slugify_mixed_case():
    assert slugify("NOVAK DJOKOVIC") == "novak-djokovic"


async def test_slug_uniqueness_appends_counter():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        r1 = sample_pro_reference(player_slug="roger-federer-forehand")
        session.add(r1)
        await session.commit()

    # Simulate what the migration script does: find a unique slug
    async with factory() as session:
        base_slug = "roger-federer-forehand"
        candidate = base_slug
        counter = 2
        while True:
            result = await session.execute(
                select(ProReference).where(ProReference.player_slug == candidate)
            )
            if result.scalar_one_or_none() is None:
                break
            candidate = f"{base_slug}-{counter}"
            counter += 1

        assert candidate == "roger-federer-forehand-2"

    await engine.dispose()


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

async def test_create_and_query_pro_reference():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_pro_reference()
    async with factory() as session:
        session.add(record)
        await session.commit()
        ref_id = record.id

    async with factory() as session:
        result = await session.execute(select(ProReference).where(ProReference.id == ref_id))
        fetched = result.scalar_one()

    assert fetched.id == ref_id
    assert fetched.player_name == "Roger Federer"
    assert fetched.player_slug == "roger-federer-forehand"
    assert fetched.stroke_type == StrokeType.forehand
    assert fetched.status == ProReferenceStatus.ready
    assert fetched.is_builtin is True
    await engine.dispose()


async def test_update_status_to_failed():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_pro_reference(status=ProReferenceStatus.processing)
    async with factory() as session:
        session.add(record)
        await session.commit()
        ref_id = record.id

    async with factory() as session:
        result = await session.execute(select(ProReference).where(ProReference.id == ref_id))
        fetched = result.scalar_one()
        fetched.status = ProReferenceStatus.failed
        fetched.error_message = "ffmpeg crashed"
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(ProReference).where(ProReference.id == ref_id))
        updated = result.scalar_one()

    assert updated.status == ProReferenceStatus.failed
    assert updated.error_message == "ffmpeg crashed"
    await engine.dispose()


async def test_nullable_fields_default_none():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_pro_reference()
    async with factory() as session:
        session.add(record)
        await session.commit()
        ref_id = record.id

    async with factory() as session:
        result = await session.execute(select(ProReference).where(ProReference.id == ref_id))
        fetched = result.scalar_one()

    for field in ("video_s3_key", "thumbnail_s3_key", "npz_path", "error_message",
                  "frame_count", "fps", "duration_seconds", "metadata_json", "processed_at"):
        assert getattr(fetched, field) is None, f"Expected {field} to be None"
    await engine.dispose()


async def test_player_slug_unique_constraint():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    slug = "unique-test-forehand"
    r1 = sample_pro_reference(id=uuid.uuid4(), player_slug=slug)
    r2 = sample_pro_reference(id=uuid.uuid4(), player_slug=slug)

    async with factory() as session:
        session.add(r1)
        await session.commit()

    from sqlalchemy.exc import IntegrityError
    async with factory() as session:
        session.add(r2)
        with pytest.raises(IntegrityError):
            await session.flush()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

def test_pro_reference_create_schema():
    schema = ProReferenceCreate(player_name="Roger Federer", stroke_type=StrokeType.forehand)
    assert schema.player_name == "Roger Federer"
    assert schema.stroke_type == StrokeType.forehand
    assert schema.metadata_json is None


def test_pro_reference_response_from_orm():
    record = sample_pro_reference()
    response = ProReferenceResponse.model_validate(record)
    data = response.model_dump()
    assert isinstance(data["id"], str)
    assert data["player_name"] == "Roger Federer"
    assert data["status"] == "ready"


def test_pro_reference_list_item_from_orm():
    record = sample_pro_reference()
    item = ProReferenceListItem.model_validate(record)
    assert item.player_slug == "roger-federer-forehand"
    assert item.is_builtin is True
    assert item.thumbnail_s3_key is None


# ---------------------------------------------------------------------------
# ProReferenceDB — DB-backed methods
# ---------------------------------------------------------------------------

async def test_list_available_from_db_returns_ready_only():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    ready = sample_pro_reference(id=uuid.uuid4(), player_slug="ready-ref-forehand", status=ProReferenceStatus.ready)
    pending = sample_pro_reference(id=uuid.uuid4(), player_slug="pending-ref-forehand", status=ProReferenceStatus.pending)

    async with factory() as session:
        session.add(ready)
        session.add(pending)
        await session.commit()

    db = ProReferenceDB()
    async with factory() as session:
        items = await db.list_available_from_db(session)

    assert len(items) == 1
    assert items[0].player_slug == "ready-ref-forehand"
    await engine.dispose()


async def test_get_by_id_loads_npz(tmp_path):
    """get_by_id should load .npz from npz_path and return the reference dict."""
    # Build a minimal .npz in tmp_path
    joint_angles = {"elbow_angle": np.linspace(10, 90, 30)}
    phases = {"backswing": (0, 10), "forward_swing": (11, 25), "contact": (26, 28), "follow_through": (29, 29)}

    phase_keys = list(phases.keys())
    phase_values = np.array([list(v) for v in phases.values()], dtype=np.int32)
    save_dict = {
        "_player": "TestPlayer",
        "_stroke_type": "forehand",
        "_phase_keys": np.array(phase_keys),
        "_phase_values": phase_values,
        "angle_elbow_angle": joint_angles["elbow_angle"],
    }
    npz_path = tmp_path / "testplayer_forehand.npz"
    np.savez(npz_path, **save_dict)

    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_pro_reference(
        player_name="TestPlayer",
        player_slug="testplayer-forehand",
        npz_path=str(npz_path),
    )
    async with factory() as session:
        session.add(record)
        await session.commit()
        ref_id = record.id

    db = ProReferenceDB()
    async with factory() as session:
        ref = await db.get_by_id(session, ref_id)

    assert ref is not None
    assert ref["player"] == "TestPlayer"
    assert ref["stroke_type"] == "forehand"
    assert "elbow_angle" in ref["joint_angles"]
    await engine.dispose()


async def test_get_by_id_returns_none_for_missing():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    db = ProReferenceDB()
    async with factory() as session:
        ref = await db.get_by_id(session, uuid.uuid4())
    assert ref is None
    await engine.dispose()


async def test_get_by_id_returns_none_for_non_ready():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_pro_reference(status=ProReferenceStatus.pending)
    async with factory() as session:
        session.add(record)
        await session.commit()
        ref_id = record.id

    db = ProReferenceDB()
    async with factory() as session:
        ref = await db.get_by_id(session, ref_id)
    assert ref is None
    await engine.dispose()


def test_list_available_deprecated_warning():
    db = ProReferenceDB()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        db.list_available()
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()


# ---------------------------------------------------------------------------
# Migration script
# ---------------------------------------------------------------------------

async def test_migration_script_creates_records(tmp_path):
    """migrate() should create one ready is_builtin record per .npz file."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    from migrate_static_references import migrate

    # Point migration at the real data dir (has synthetic_forehand.npz)
    db_url = "sqlite+aiosqlite:///:memory:"

    # The migrate() function calls Base.metadata.create_all so tables exist
    await migrate(db_url)

    # Verify by connecting to the same URL — but since it's :memory: we can't
    # reconnect to the same instance. Re-run against a file-based DB instead.
    db_path = tmp_path / "migrate_test.db"
    file_db_url = f"sqlite+aiosqlite:///{db_path}"
    await migrate(file_db_url)

    engine = create_async_engine(file_db_url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(ProReference).where(
                ProReference.status == ProReferenceStatus.ready,
                ProReference.is_builtin.is_(True),
            )
        )
        records = result.scalars().all()

    assert len(records) >= 1, "Expected at least one migrated record"
    assert all(r.npz_path is not None for r in records)
    assert all(r.is_builtin for r in records)
    await engine.dispose()


async def test_migration_script_is_idempotent(tmp_path):
    """Running migrate() twice should not create duplicate records."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    from migrate_static_references import migrate

    db_path = tmp_path / "idempotent_test.db"
    file_db_url = f"sqlite+aiosqlite:///{db_path}"

    await migrate(file_db_url)
    await migrate(file_db_url)

    engine = create_async_engine(file_db_url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(ProReference))
        records = result.scalars().all()

    # No duplicates — count should match first run
    npz_paths = [r.npz_path for r in records]
    assert len(npz_paths) == len(set(npz_paths)), "Duplicate npz_path records found"
    await engine.dispose()
