"""
Tests for Task 4.3: keyframe extraction, batch presigned URL generation,
and video_url / keyframe_urls in analysis and overlay endpoints.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import cv2
import numpy as np
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


def _fake_landmarks(n_frames: int = 30) -> list:
    return np.random.rand(n_frames, 33, 3).astype(np.float32).tolist()


@pytest.fixture
async def analysis_with_keyframes(db_engine) -> Analysis:
    """Insert a completed Analysis that has keyframe_s3_keys populated."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    n = 30
    analysis = Analysis(
        id=uuid.uuid4(),
        status=AnalysisStatus.completed,
        stroke_type=StrokeType.forehand,
        pro_reference="federer",
        video_s3_key="uploads/test/video.mp4",
        pose_data=_fake_landmarks(n),
        aligned_pro_landmarks=_fake_landmarks(n),
        frame_mapping=list(range(n)),
        frame_deviations=[],
        phase_boundaries={
            "backswing": {
                "phase_name": "backswing", "user_start": 0, "user_end": 14,
                "pro_start": 0, "pro_end": 14,
                "user_duration_frames": 15, "pro_duration_frames": 15, "tempo_ratio": 1.0,
            }
        },
        fps=30.0,
        keyframe_s3_keys={
            "preparation": "analyses/test-id/keyframes/phase_preparation.jpg",
            "backswing": "analyses/test-id/keyframes/phase_backswing.jpg",
            "forward_swing": "analyses/test-id/keyframes/phase_forward_swing.jpg",
            "contact": "analyses/test-id/keyframes/phase_contact.jpg",
            "follow_through": "analyses/test-id/keyframes/phase_follow_through.jpg",
        },
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(analysis)
        await session.commit()
    return analysis


@pytest.fixture
async def analysis_without_keyframes(db_engine) -> Analysis:
    """Insert a completed Analysis with no keyframe_s3_keys (older record)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    n = 30
    analysis = Analysis(
        id=uuid.uuid4(),
        status=AnalysisStatus.completed,
        stroke_type=StrokeType.forehand,
        pro_reference="federer",
        video_s3_key="uploads/test/video.mp4",
        pose_data=_fake_landmarks(n),
        aligned_pro_landmarks=_fake_landmarks(n),
        frame_mapping=list(range(n)),
        frame_deviations=[],
        phase_boundaries={},
        fps=30.0,
        keyframe_s3_keys=None,
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(analysis)
        await session.commit()
    return analysis


# ---------------------------------------------------------------------------
# _save_keyframes unit tests
# ---------------------------------------------------------------------------

class TestSaveKeyframes:
    def _make_frame_pngs(self, tmp_path: Path, count: int) -> list[str]:
        """Create real PNG files in tmp_path and return their paths."""
        paths = []
        for i in range(count):
            img = np.zeros((64, 64, 3), dtype=np.uint8)
            img[:, :, i % 3] = 128 + i  # distinct color per frame
            p = str(tmp_path / f"frame_{i:05d}.png")
            cv2.imwrite(p, img)
            paths.append(p)
        return paths

    def test_produces_one_jpeg_per_phase(self, tmp_path):
        from app.worker.tasks import _save_keyframes

        frame_paths = self._make_frame_pngs(tmp_path, 30)
        phases = {
            "preparation": (0, 4),
            "backswing": (5, 10),
            "forward_swing": (11, 18),
            "contact": (19, 21),
            "follow_through": (22, 29),
        }
        result = _save_keyframes(frame_paths, phases, str(tmp_path))
        assert set(result.keys()) == set(phases.keys())

    def test_jpeg_files_exist_on_disk(self, tmp_path):
        from app.worker.tasks import _save_keyframes

        frame_paths = self._make_frame_pngs(tmp_path, 10)
        phases = {"backswing": (0, 4), "forward_swing": (5, 9)}
        result = _save_keyframes(frame_paths, phases, str(tmp_path))
        for path in result.values():
            assert Path(path).exists(), f"{path} was not created"
            assert path.endswith(".jpg")

    def test_uses_phase_start_frame(self, tmp_path):
        """The keyframe for each phase should be the frame at phase start, not another frame."""
        from app.worker.tasks import _save_keyframes

        # Create 10 frames: even frames are dark (~30), odd frames are bright (~200)
        frame_paths = []
        for i in range(10):
            brightness = 30 if i % 2 == 0 else 200
            img = np.full((64, 64, 3), brightness, dtype=np.uint8)
            p = str(tmp_path / f"frame_{i:05d}.png")
            cv2.imwrite(p, img)
            frame_paths.append(p)

        # Phase starts at frame 5 (odd → bright ~200) not frame 4 (even → dark ~30)
        phases = {"backswing": (5, 8)}
        result = _save_keyframes(frame_paths, phases, str(tmp_path))
        assert "backswing" in result

        saved = cv2.imread(result["backswing"])
        assert saved is not None
        # JPEG is lossy, but mean value should be close to 200 (bright frame 5), not 30
        mean_val = float(saved.mean())
        assert mean_val > 100, (
            f"Expected bright frame (mean > 100), got {mean_val:.1f} — wrong frame was saved"
        )

    def test_clamps_to_last_frame_when_start_exceeds_bounds(self, tmp_path):
        from app.worker.tasks import _save_keyframes

        frame_paths = self._make_frame_pngs(tmp_path, 5)
        phases = {"follow_through": (100, 200)}  # way out of bounds
        result = _save_keyframes(frame_paths, phases, str(tmp_path))
        # Should still produce a keyframe (clamped to last frame)
        assert "follow_through" in result

    def test_empty_frame_list_returns_empty_dict(self, tmp_path):
        from app.worker.tasks import _save_keyframes

        result = _save_keyframes([], {"backswing": (0, 5)}, str(tmp_path))
        assert result == {}


# ---------------------------------------------------------------------------
# generate_presigned_urls (batch utility)
# ---------------------------------------------------------------------------

class TestGeneratePresignedUrls:
    def test_returns_same_count_as_input(self):
        from app.services.s3 import generate_presigned_urls

        keys = ["analyses/id/keyframes/phase_backswing.jpg",
                "analyses/id/keyframes/phase_contact.jpg"]
        with patch("app.services.s3.get_settings") as mock_settings:
            mock_settings.return_value.s3_bucket = ""
            urls = generate_presigned_urls(keys)
        assert len(urls) == len(keys)

    def test_local_dev_returns_uploads_paths(self):
        from app.services.s3 import generate_presigned_urls

        keys = ["analyses/abc/keyframes/phase_backswing.jpg"]
        with patch("app.services.s3.get_settings") as mock_settings:
            mock_settings.return_value.s3_bucket = ""
            urls = generate_presigned_urls(keys)
        assert urls[0] == "/uploads/analyses/abc/keyframes/phase_backswing.jpg"

    def test_preserves_order(self):
        from app.services.s3 import generate_presigned_urls

        keys = ["key_a", "key_b", "key_c"]
        with patch("app.services.s3.get_settings") as mock_settings:
            mock_settings.return_value.s3_bucket = ""
            urls = generate_presigned_urls(keys)
        for key, url in zip(keys, urls):
            assert key in url

    def test_empty_list_returns_empty_list(self):
        from app.services.s3 import generate_presigned_urls

        with patch("app.services.s3.get_settings") as mock_settings:
            mock_settings.return_value.s3_bucket = ""
            urls = generate_presigned_urls([])
        assert urls == []


# ---------------------------------------------------------------------------
# GET /api/analysis/{id} — video_url and keyframe_urls
# ---------------------------------------------------------------------------

class TestAnalysisEndpointUrls:
    async def test_video_url_present_in_response(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}")
        assert r.status_code == 200
        body = r.json()
        assert "video_url" in body
        assert body["video_url"] is not None

    async def test_video_url_contains_s3_key(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}")
        body = r.json()
        # In local dev (no S3), the URL is /uploads/{key}
        assert "uploads/test/video.mp4" in body["video_url"]

    async def test_keyframe_urls_present_in_response(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}")
        body = r.json()
        assert "keyframe_urls" in body
        assert body["keyframe_urls"] is not None
        assert set(body["keyframe_urls"].keys()) == {
            "preparation", "backswing", "forward_swing", "contact", "follow_through"
        }

    async def test_keyframe_urls_are_http_paths(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}")
        body = r.json()
        for phase_name, url in body["keyframe_urls"].items():
            assert url.startswith("/uploads/"), f"{phase_name} URL is not an /uploads/ path: {url}"

    async def test_keyframe_urls_null_when_no_keyframes(self, client, analysis_without_keyframes):
        r = await client.get(f"/api/analysis/{analysis_without_keyframes.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["keyframe_urls"] is None


# ---------------------------------------------------------------------------
# GET /api/analysis/{id}/overlay — video_url, keyframe_urls, cache-control
# ---------------------------------------------------------------------------

class TestOverlayEndpointUrls:
    async def test_video_url_in_overlay_response(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}/overlay")
        assert r.status_code == 200
        body = r.json()
        assert "video_url" in body
        assert body["video_url"] is not None
        assert "uploads/test/video.mp4" in body["video_url"]

    async def test_keyframe_urls_in_overlay_response(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}/overlay")
        body = r.json()
        assert "keyframe_urls" in body
        assert body["keyframe_urls"] is not None
        assert len(body["keyframe_urls"]) == 5

    async def test_overlay_cache_control_is_private_short_lived(self, client, analysis_with_keyframes):
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}/overlay")
        cc = r.headers.get("cache-control", "")
        assert "private" in cc
        assert "3600" in cc

    async def test_overlay_no_longer_immutable_cached(self, client, analysis_with_keyframes):
        """Presigned URLs expire — the overlay response must not be cached as immutable."""
        r = await client.get(f"/api/analysis/{analysis_with_keyframes.id}/overlay")
        cc = r.headers.get("cache-control", "")
        assert "immutable" not in cc
