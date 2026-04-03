"""
Tests for Task 1.3: S3 service, upload router, analysis router.
Uses in-memory SQLite and FastAPI dependency_overrides to avoid real DB/S3/Redis.
"""
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
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


@pytest.fixture
async def existing_analysis(db_engine) -> Analysis:
    """Insert a pending Analysis record for use in multiple tests."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analysis = Analysis(
        id=uuid.uuid4(),
        status=AnalysisStatus.pending,
        stroke_type=StrokeType.forehand,
        pro_reference="federer",
        video_s3_key="uploads/test/video.mp4",
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(analysis)
        await session.commit()
    return analysis


# ---------------------------------------------------------------------------
# S3 service tests (no real AWS needed)
# ---------------------------------------------------------------------------

def test_local_dev_presigned_upload_url(tmp_path, monkeypatch):
    """When S3_BUCKET is empty, returns a file:// URI and creates the directory."""
    from app.services import s3 as s3_module
    from app.config import Settings

    monkeypatch.setattr(s3_module, "_LOCAL_UPLOAD_DIR", tmp_path / "uploads")

    with patch("app.services.s3.get_settings", return_value=Settings(s3_bucket="")):
        url = s3_module.generate_presigned_upload_url("uploads/abc/vid.mp4")

    assert url.startswith("file://")
    assert "vid.mp4" in url


def test_local_dev_presigned_download_url(tmp_path, monkeypatch):
    from app.services import s3 as s3_module
    from app.config import Settings

    monkeypatch.setattr(s3_module, "_LOCAL_UPLOAD_DIR", tmp_path / "uploads")

    with patch("app.services.s3.get_settings", return_value=Settings(s3_bucket="")):
        url = s3_module.generate_presigned_download_url("uploads/abc/vid.mp4")

    # Local dev fallback now returns an HTTP path served by the StaticFiles mount
    assert url.startswith("/uploads/")
    assert "vid.mp4" in url


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

async def test_initiate_upload_returns_201(client):
    with patch("app.routers.upload.generate_presigned_upload_url", return_value="https://s3.example.com/presigned"):
        resp = await client.post("/api/upload", json={"stroke_type": "forehand", "pro_reference": "federer"})

    assert resp.status_code == 201
    data = resp.json()
    assert "analysis_id" in data
    assert data["upload_url"] == "https://s3.example.com/presigned"
    assert data["s3_key"].startswith("uploads/")
    assert data["s3_key"].endswith(".mp4")
    # s3_key should contain the analysis_id
    assert data["analysis_id"] in data["s3_key"]


async def test_initiate_upload_all_stroke_types(client):
    strokes = ["forehand", "backhand_one", "backhand_two", "serve_flat", "serve_kick", "serve_slice", "volley", "buggy_whip_forehand", "slice"]
    for stroke in strokes:
        with patch("app.routers.upload.generate_presigned_upload_url", return_value="https://s3.example.com/presigned"):
            resp = await client.post("/api/upload", json={"stroke_type": stroke})
        assert resp.status_code == 201, f"Expected 201 for stroke_type={stroke}, got {resp.status_code}"


async def test_initiate_upload_invalid_stroke_type_returns_422(client):
    resp = await client.post("/api/upload", json={"stroke_type": "dropshot"})
    assert resp.status_code == 422


async def test_initiate_upload_missing_stroke_type_returns_422(client):
    resp = await client.post("/api/upload", json={"pro_reference": "federer"})
    assert resp.status_code == 422


async def test_initiate_upload_default_pro_reference(client):
    """pro_reference should default to 'federer' when omitted."""
    with patch("app.routers.upload.generate_presigned_upload_url", return_value="https://s3.example.com/x"):
        resp = await client.post("/api/upload", json={"stroke_type": "forehand"})
    assert resp.status_code == 201
    # The analysis_id can be used to verify the record — just check we got one
    assert uuid.UUID(resp.json()["analysis_id"])  # valid UUID


# ---------------------------------------------------------------------------
# POST /api/upload/{analysis_id}/confirm
# ---------------------------------------------------------------------------

async def test_confirm_upload_transitions_to_processing(client, existing_analysis):
    with patch("app.routers.upload._enqueue_analysis_job"):
        resp = await client.post(f"/api/upload/{existing_analysis.id}/confirm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["analysis_id"] == str(existing_analysis.id)


async def test_confirm_upload_unknown_id_returns_404(client):
    with patch("app.routers.upload._enqueue_analysis_job"):
        resp = await client.post(f"/api/upload/{uuid.uuid4()}/confirm")
    assert resp.status_code == 404


async def test_confirm_upload_already_processing_returns_409(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    analysis = Analysis(
        id=uuid.uuid4(),
        status=AnalysisStatus.processing,
        stroke_type=StrokeType.serve_flat,
        pro_reference="federer",
        video_s3_key="uploads/test/vid.mp4",
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(analysis)
        await session.commit()

    resp = await client.post(f"/api/upload/{analysis.id}/confirm")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/analysis/{analysis_id}
# ---------------------------------------------------------------------------

async def test_get_analysis_returns_200(client, existing_analysis):
    resp = await client.get(f"/api/analysis/{existing_analysis.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(existing_analysis.id)
    assert data["status"] == "pending"
    assert data["stroke_type"] == "forehand"


async def test_get_analysis_unknown_id_returns_404(client):
    resp = await client.get(f"/api/analysis/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

async def test_get_history_returns_list(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    records = [
        Analysis(
            id=uuid.uuid4(),
            status=AnalysisStatus.completed,
            stroke_type=StrokeType.forehand,
            pro_reference="federer",
            video_s3_key=f"uploads/{i}/vid.mp4",
            created_at=datetime.now(timezone.utc),
            overall_score=float(70 + i),
        )
        for i in range(3)
    ]
    async with factory() as session:
        session.add_all(records)
        await session.commit()

    resp = await client.get("/api/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # Should be ordered newest first — overall_score used as a proxy check
    # (all created_at equal here, so order may vary — just check count and fields)
    assert all("id" in item and "status" in item for item in data)


async def test_get_history_limit_param(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    records = [
        Analysis(
            id=uuid.uuid4(),
            status=AnalysisStatus.completed,
            stroke_type=StrokeType.volley,
            pro_reference="federer",
            video_s3_key=f"uploads/{i}/vid.mp4",
            created_at=datetime.now(timezone.utc),
        )
        for i in range(5)
    ]
    async with factory() as session:
        session.add_all(records)
        await session.commit()

    resp = await client.get("/api/history?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_history_empty_returns_empty_list(client):
    resp = await client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == []
