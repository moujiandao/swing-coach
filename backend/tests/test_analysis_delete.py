"""
Tests for DELETE /api/analysis/{id} and POST /api/analysis/bulk-delete.
"""
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models import Analysis, AnalysisStatus, Base, StrokeType
from app.services.db import get_db

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _make_analysis(**overrides) -> Analysis:
    defaults = dict(
        id=uuid.uuid4(),
        status=AnalysisStatus.completed,
        stroke_type=StrokeType.forehand,
        pro_reference="federer",
        video_s3_key="uploads/test/video.mp4",
        keyframe_s3_keys={"contact": "analyses/test/keyframes/phase_contact.jpg"},
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Analysis(**defaults)


@pytest.fixture
async def sample_analysis(db_engine) -> Analysis:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analysis = _make_analysis()
    async with factory() as session:
        session.add(analysis)
        await session.commit()
    return analysis


# ---------------------------------------------------------------------------
# DELETE /api/analysis/{analysis_id}
# ---------------------------------------------------------------------------

async def test_delete_analysis_returns_204(client, sample_analysis):
    with patch("app.routers.analysis.delete_object"):
        resp = await client.delete(f"/api/analysis/{sample_analysis.id}")
    assert resp.status_code == 204


async def test_delete_analysis_removes_db_record(client, sample_analysis, db_engine):
    with patch("app.routers.analysis.delete_object"):
        await client.delete(f"/api/analysis/{sample_analysis.id}")

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == sample_analysis.id)
        )
        assert result.scalar_one_or_none() is None


async def test_delete_analysis_calls_s3_delete(client, sample_analysis):
    with patch("app.routers.analysis.delete_object") as mock_delete:
        await client.delete(f"/api/analysis/{sample_analysis.id}")

    # Should delete video + keyframe
    deleted_keys = [call.args[0] for call in mock_delete.call_args_list]
    assert sample_analysis.video_s3_key in deleted_keys
    assert "analyses/test/keyframes/phase_contact.jpg" in deleted_keys


async def test_delete_analysis_unknown_id_returns_404(client):
    resp = await client.delete(f"/api/analysis/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_analysis_no_keyframes_still_works(client, db_engine):
    """Analysis without keyframe_s3_keys should still delete cleanly."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analysis = _make_analysis(keyframe_s3_keys=None)
    async with factory() as session:
        session.add(analysis)
        await session.commit()

    with patch("app.routers.analysis.delete_object"):
        resp = await client.delete(f"/api/analysis/{analysis.id}")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# POST /api/analysis/bulk-delete
# ---------------------------------------------------------------------------

async def test_bulk_delete_returns_count(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analyses = [_make_analysis() for _ in range(3)]
    async with factory() as session:
        session.add_all(analyses)
        await session.commit()

    ids = [str(a.id) for a in analyses]
    with patch("app.routers.analysis.delete_object"):
        resp = await client.post("/api/analysis/bulk-delete", json={"ids": ids})

    assert resp.status_code == 200
    assert resp.json()["deleted"] == 3


async def test_bulk_delete_skips_missing_ids(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analysis = _make_analysis()
    async with factory() as session:
        session.add(analysis)
        await session.commit()

    ids = [str(analysis.id), str(uuid.uuid4())]
    with patch("app.routers.analysis.delete_object"):
        resp = await client.post("/api/analysis/bulk-delete", json={"ids": ids})

    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


async def test_bulk_delete_empty_list(client):
    resp = await client.post("/api/analysis/bulk-delete", json={"ids": []})
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


async def test_bulk_delete_removes_db_records(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analyses = [_make_analysis() for _ in range(2)]
    async with factory() as session:
        session.add_all(analyses)
        await session.commit()

    ids = [str(a.id) for a in analyses]
    with patch("app.routers.analysis.delete_object"):
        await client.post("/api/analysis/bulk-delete", json={"ids": ids})

    async with factory() as session:
        for a in analyses:
            result = await session.execute(
                select(Analysis).where(Analysis.id == a.id)
            )
            assert result.scalar_one_or_none() is None
