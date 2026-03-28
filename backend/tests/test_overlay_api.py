"""
Tests for Task 4.2 overlay API endpoints.

GET /api/analysis/{id}/overlay
GET /api/pro-references/{id}/preview

Uses in-memory SQLite and FastAPI dependency_overrides — same pattern as
test_upload_and_analysis.py.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models import (
    Analysis,
    AnalysisStatus,
    Base,
    LANDMARK_CONNECTIONS,
    ProReference,
    ProReferenceStatus,
    StrokeType,
)
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


def _fake_landmarks(n_frames: int = 30) -> list:
    """Build a (n_frames, 33, 3) nested list with dummy coords."""
    return np.random.rand(n_frames, 33, 3).astype(np.float32).tolist()


def _fake_frame_deviations() -> list:
    return [
        {
            "frame_index": 5,
            "deviating_joints": [
                {
                    "joint_name": "elbow_angle",
                    "landmark_indices": [13, 14],
                    "user_angle": 95.5,
                    "pro_angle": 80.0,
                    "diff_degrees": 15.5,
                    "direction": "too_wide",
                }
            ],
            "phase": "backswing",
            "severity": "moderate",
        }
    ]


@pytest.fixture
async def completed_analysis(db_engine) -> Analysis:
    """Insert a completed Analysis with full overlay data."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    n_frames = 30
    analysis = Analysis(
        id=uuid.uuid4(),
        status=AnalysisStatus.completed,
        stroke_type=StrokeType.forehand,
        pro_reference="federer",
        video_s3_key="uploads/test/video.mp4",
        pose_data=_fake_landmarks(n_frames),
        aligned_pro_landmarks=_fake_landmarks(n_frames),
        frame_mapping=list(range(n_frames)),
        frame_deviations=_fake_frame_deviations(),
        phase_boundaries={
            "backswing": {
                "phase_name": "backswing",
                "user_start": 0, "user_end": 14,
                "pro_start": 0, "pro_end": 14,
                "user_duration_frames": 15,
                "pro_duration_frames": 15,
                "tempo_ratio": 1.0,
            }
        },
        fps=30.0,
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(analysis)
        await session.commit()
    return analysis


@pytest.fixture
async def pending_analysis(db_engine) -> Analysis:
    """Insert a pending Analysis (overlay not available)."""
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


@pytest.fixture
async def ready_pro_reference(db_engine, tmp_path) -> ProReference:
    """Insert a ready ProReference with a real .npz file containing _landmarks."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    n_frames = 20
    landmarks = np.random.rand(n_frames, 33, 3).astype(np.float32)
    phase_keys = np.array(["preparation", "backswing", "forward_swing", "contact", "follow_through"])
    phase_values = np.array([
        [0, 3], [4, 9], [10, 14], [15, 16], [17, 19]
    ], dtype=np.int32)

    npz_path = str(tmp_path / "test_ref.npz")
    np.savez(
        npz_path,
        _landmarks=landmarks,
        _phase_keys=phase_keys,
        _phase_values=phase_values,
        _fps=np.float64(30.0),
        _frame_count=np.int64(n_frames),
        _player="Test Player",
        _stroke_type="forehand",
    )

    ref = ProReference(
        id=uuid.uuid4(),
        player_name="Test Player",
        player_slug="test-player-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.ready,
        npz_path=npz_path,
        fps=30.0,
        frame_count=n_frames,
        is_builtin=False,
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()
    return ref


@pytest.fixture
async def processing_pro_reference(db_engine) -> ProReference:
    """Insert a ProReference that is still processing (no .npz yet)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(),
        player_name="In Progress",
        player_slug="in-progress-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.processing,
        is_builtin=False,
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()
    return ref


# ---------------------------------------------------------------------------
# LANDMARK_CONNECTIONS validity
# ---------------------------------------------------------------------------

class TestLandmarkConnections:
    def test_all_indices_less_than_33(self):
        for pair in LANDMARK_CONNECTIONS:
            for idx in pair:
                assert idx < 33, f"Index {idx} >= 33 in {pair}"

    def test_all_indices_non_negative(self):
        for pair in LANDMARK_CONNECTIONS:
            for idx in pair:
                assert idx >= 0

    def test_each_connection_is_a_pair(self):
        for pair in LANDMARK_CONNECTIONS:
            assert len(pair) == 2

    def test_no_self_connections(self):
        for pair in LANDMARK_CONNECTIONS:
            assert pair[0] != pair[1]

    def test_covers_major_body_parts(self):
        # Shoulders, elbows, wrists, hips, knees, ankles all connected
        all_indices = {idx for pair in LANDMARK_CONNECTIONS for idx in pair}
        expected = {11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28}
        assert expected.issubset(all_indices)


# ---------------------------------------------------------------------------
# GET /api/analysis/{id}/overlay
# ---------------------------------------------------------------------------

class TestOverlayEndpoint:
    async def test_returns_200_for_completed_analysis(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        assert r.status_code == 200

    async def test_response_has_required_keys(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        assert "user_landmarks" in body
        assert "pro_landmarks" in body
        assert "frame_mapping" in body
        assert "frame_deviations" in body
        assert "phase_boundaries" in body
        assert "fps" in body
        assert "landmark_connections" in body

    async def test_user_landmarks_shape(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        user_lm = body["user_landmarks"]
        assert len(user_lm) == 30         # 30 frames
        assert len(user_lm[0]) == 33      # 33 landmarks
        assert len(user_lm[0][0]) == 3    # x, y, z

    async def test_pro_landmarks_same_length_as_user(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        assert len(body["pro_landmarks"]) == len(body["user_landmarks"])

    async def test_coords_rounded_to_4_decimal_places(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        for frame in body["user_landmarks"]:
            for lm in frame:
                for coord in lm:
                    # At most 4 decimal places
                    assert round(coord, 4) == coord

    async def test_landmark_connections_returned(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        assert body["landmark_connections"] == LANDMARK_CONNECTIONS

    async def test_fps_returned(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        assert body["fps"] == 30.0

    async def test_404_for_pending_analysis(self, client, pending_analysis):
        r = await client.get(f"/api/analysis/{pending_analysis.id}/overlay")
        assert r.status_code == 404

    async def test_404_for_unknown_id(self, client):
        r = await client.get(f"/api/analysis/{uuid.uuid4()}/overlay")
        assert r.status_code == 404

    async def test_cache_control_header_set(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        assert "cache-control" in r.headers
        assert "immutable" in r.headers["cache-control"]

    async def test_frame_deviations_returned(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        assert isinstance(body["frame_deviations"], list)
        assert len(body["frame_deviations"]) == 1
        assert body["frame_deviations"][0]["frame_index"] == 5

    async def test_phase_boundaries_returned(self, client, completed_analysis):
        r = await client.get(f"/api/analysis/{completed_analysis.id}/overlay")
        body = r.json()
        assert "backswing" in body["phase_boundaries"]


# ---------------------------------------------------------------------------
# GET /api/pro-references/{id}/preview
# ---------------------------------------------------------------------------

class TestProPreviewEndpoint:
    async def test_returns_200_for_ready_reference(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        assert r.status_code == 200

    async def test_response_has_required_keys(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        assert "landmarks" in body
        assert "phases" in body
        assert "fps" in body
        assert "frame_count" in body
        assert "landmark_connections" in body

    async def test_landmarks_shape(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        lm = body["landmarks"]
        assert len(lm) == 20        # 20 frames
        assert len(lm[0]) == 33     # 33 landmarks
        assert len(lm[0][0]) == 3   # x, y, z

    async def test_coords_rounded_to_4_decimal_places(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        for frame in body["landmarks"]:
            for lm in frame:
                for coord in lm:
                    assert round(coord, 4) == coord

    async def test_phases_returned(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        assert "preparation" in body["phases"]
        assert "backswing" in body["phases"]

    async def test_fps_value(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        assert body["fps"] == 30.0

    async def test_frame_count_matches(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        assert body["frame_count"] == 20

    async def test_landmark_connections_returned(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        body = r.json()
        assert body["landmark_connections"] == LANDMARK_CONNECTIONS

    async def test_404_for_processing_reference(self, client, processing_pro_reference):
        r = await client.get(f"/api/pro-references/{processing_pro_reference.id}/preview")
        assert r.status_code == 404

    async def test_404_for_unknown_id(self, client):
        r = await client.get(f"/api/pro-references/{uuid.uuid4()}/preview")
        assert r.status_code == 404

    async def test_cache_control_header_set(self, client, ready_pro_reference):
        r = await client.get(f"/api/pro-references/{ready_pro_reference.id}/preview")
        assert "cache-control" in r.headers
        assert "immutable" in r.headers["cache-control"]
