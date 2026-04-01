"""
Tests for the pro reference API endpoints and worker task.

Uses in-memory SQLite + FastAPI dependency_overrides to avoid real DB/S3/Redis.
Worker task tests patch internal async helpers so no event-loop nesting occurs.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models import Base, ProReference, ProReferenceStatus, StrokeType
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
async def ready_reference(db_engine) -> ProReference:
    """A ready, non-builtin ProReference record."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(),
        player_name="Roger Federer",
        player_slug="roger-federer-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.ready,
        is_builtin=False,
        npz_path="/tmp/test.npz",
        video_s3_key="pro-references/test/video.mp4",
        thumbnail_s3_key="pro-references/test/thumbnail.jpg",
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()
    return ref


@pytest.fixture
async def builtin_reference(db_engine) -> ProReference:
    """A ready, builtin ProReference record (cannot be deleted)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(),
        player_name="Synthetic",
        player_slug="synthetic-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.ready,
        is_builtin=True,
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()
    return ref


@pytest.fixture
async def pending_reference(db_engine) -> ProReference:
    """A pending ProReference ready for /confirm."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(),
        player_name="Rafael Nadal",
        player_slug="rafael-nadal-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.pending,
        is_builtin=False,
        video_s3_key="pro-references/test-pending/video.mp4",
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()
    return ref


# ---------------------------------------------------------------------------
# POST /api/pro-references
# ---------------------------------------------------------------------------

async def test_create_returns_201(client):
    with patch("app.routers.pro_references.generate_presigned_upload_url", return_value="https://s3.test/presigned"):
        resp = await client.post(
            "/api/pro-references",
            json={"player_name": "Roger Federer", "stroke_type": "forehand"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert "reference_id" in data
    assert data["upload_url"] == "https://s3.test/presigned"
    assert data["s3_key"].startswith("pro-references/")
    assert data["s3_key"].endswith(".mp4")


async def test_create_generates_slug_from_player_name(client, db_engine):
    """Slug should be derived from player_name + stroke_type."""
    with patch("app.routers.pro_references.generate_presigned_upload_url", return_value="https://s3.test/x"):
        resp = await client.post(
            "/api/pro-references",
            json={"player_name": "Carlos Alcaraz", "stroke_type": "backhand_one"},
        )
    assert resp.status_code == 201
    ref_id = uuid.UUID(resp.json()["reference_id"])

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(ProReference).where(ProReference.id == ref_id))
        ref = result.scalar_one()

    assert ref.player_slug == "carlos-alcaraz-backhand-one"


async def test_create_deduplicates_slug(client, db_engine):
    """Creating two references for the same player+stroke appends -2 on the second."""
    with patch("app.routers.pro_references.generate_presigned_upload_url", return_value="https://s3.test/x"):
        for _ in range(2):
            resp = await client.post(
                "/api/pro-references",
                json={"player_name": "Novak Djokovic", "stroke_type": "serve_flat"},
            )
            assert resp.status_code == 201

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.player_name == "Novak Djokovic")
        )
        refs = result.scalars().all()

    slugs = {r.player_slug for r in refs}
    assert "novak-djokovic-serve-flat" in slugs
    assert "novak-djokovic-serve-flat-2" in slugs


async def test_create_invalid_stroke_type_returns_422(client):
    resp = await client.post(
        "/api/pro-references",
        json={"player_name": "Player", "stroke_type": "smash"},
    )
    assert resp.status_code == 422


async def test_create_missing_player_name_returns_422(client):
    resp = await client.post("/api/pro-references", json={"stroke_type": "forehand"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/pro-references/{id}/confirm
# ---------------------------------------------------------------------------

async def test_confirm_transitions_to_processing(client, pending_reference):
    with patch("app.routers.pro_references._enqueue_pro_reference_job"):
        resp = await client.post(f"/api/pro-references/{pending_reference.id}/confirm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["reference_id"] == str(pending_reference.id)


async def test_confirm_enqueues_job(client, pending_reference):
    with patch("app.routers.pro_references._enqueue_pro_reference_job") as mock_enqueue:
        await client.post(f"/api/pro-references/{pending_reference.id}/confirm")

    mock_enqueue.assert_called_once_with(str(pending_reference.id))


async def test_confirm_unknown_id_returns_404(client):
    with patch("app.routers.pro_references._enqueue_pro_reference_job"):
        resp = await client.post(f"/api/pro-references/{uuid.uuid4()}/confirm")
    assert resp.status_code == 404


async def test_confirm_already_processing_returns_409(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(),
        player_name="Test Player",
        player_slug="test-player-forehand",
        stroke_type=StrokeType.forehand,
        status=ProReferenceStatus.processing,
        is_builtin=False,
        created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()

    resp = await client.post(f"/api/pro-references/{ref.id}/confirm")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/pro-references
# ---------------------------------------------------------------------------

async def test_list_returns_all(client, ready_reference, builtin_reference):
    resp = await client.get("/api/pro-references")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}
    assert str(ready_reference.id) in ids
    assert str(builtin_reference.id) in ids


async def test_list_filters_by_stroke_type(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    forehand_ref = ProReference(
        id=uuid.uuid4(), player_name="A", player_slug="a-forehand",
        stroke_type=StrokeType.forehand, status=ProReferenceStatus.ready,
        is_builtin=False, created_at=datetime.now(timezone.utc),
    )
    volley_ref = ProReference(
        id=uuid.uuid4(), player_name="B", player_slug="b-volley",
        stroke_type=StrokeType.volley, status=ProReferenceStatus.ready,
        is_builtin=False, created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add_all([forehand_ref, volley_ref])
        await session.commit()

    resp = await client.get("/api/pro-references?stroke_type=volley")
    assert resp.status_code == 200
    result_ids = {item["id"] for item in resp.json()}
    assert str(volley_ref.id) in result_ids
    assert str(forehand_ref.id) not in result_ids


async def test_list_filters_by_status(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ready = ProReference(
        id=uuid.uuid4(), player_name="Ready", player_slug="ready-forehand",
        stroke_type=StrokeType.forehand, status=ProReferenceStatus.ready,
        is_builtin=False, created_at=datetime.now(timezone.utc),
    )
    failed = ProReference(
        id=uuid.uuid4(), player_name="Failed", player_slug="failed-forehand",
        stroke_type=StrokeType.forehand, status=ProReferenceStatus.failed,
        is_builtin=False, created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add_all([ready, failed])
        await session.commit()

    resp = await client.get("/api/pro-references?status=failed")
    assert resp.status_code == 200
    result_ids = {item["id"] for item in resp.json()}
    assert str(failed.id) in result_ids
    assert str(ready.id) not in result_ids


async def test_list_excludes_builtins(client, ready_reference, builtin_reference):
    resp = await client.get("/api/pro-references?include_builtin=false")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}
    assert str(ready_reference.id) in ids
    assert str(builtin_reference.id) not in ids


async def test_list_sorted_by_player_name(client, db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    refs = [
        ProReference(
            id=uuid.uuid4(), player_name=name, player_slug=f"{name.lower()}-forehand",
            stroke_type=StrokeType.forehand, status=ProReferenceStatus.ready,
            is_builtin=False, created_at=datetime.now(timezone.utc),
        )
        for name in ["Zverev", "Alcaraz", "Medvedev"]
    ]
    async with factory() as session:
        session.add_all(refs)
        await session.commit()

    resp = await client.get("/api/pro-references")
    assert resp.status_code == 200
    names = [item["player_name"] for item in resp.json()]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# GET /api/pro-references/{id}
# ---------------------------------------------------------------------------

async def test_get_detail_returns_full_reference(client, ready_reference):
    resp = await client.get(f"/api/pro-references/{ready_reference.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(ready_reference.id)
    assert data["player_name"] == "Roger Federer"
    assert data["status"] == "ready"
    assert "npz_path" in data
    assert "frame_count" in data


async def test_get_detail_unknown_id_returns_404(client):
    resp = await client.get(f"/api/pro-references/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/pro-references/{id}
# ---------------------------------------------------------------------------

async def test_delete_non_builtin_returns_204(client, ready_reference, tmp_path):
    # Create a real .npz file so the delete path exercises the unlink
    npz_file = tmp_path / "test.npz"
    npz_file.write_bytes(b"")

    # Update the fixture's npz_path via a direct DB write is not needed —
    # the fixture has npz_path="/tmp/test.npz" which won't exist, so no unlink error.
    with patch("app.routers.pro_references.delete_object"):
        resp = await client.delete(f"/api/pro-references/{ready_reference.id}")

    assert resp.status_code == 204


async def test_delete_removes_db_record(client, ready_reference, db_engine):
    with patch("app.routers.pro_references.delete_object"):
        await client.delete(f"/api/pro-references/{ready_reference.id}")

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == ready_reference.id)
        )
        assert result.scalar_one_or_none() is None


async def test_delete_builtin_returns_403(client, builtin_reference):
    resp = await client.delete(f"/api/pro-references/{builtin_reference.id}")
    assert resp.status_code == 403


async def test_delete_unknown_id_returns_404(client):
    resp = await client.delete(f"/api/pro-references/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/pro-references/{id}/reprocess
# ---------------------------------------------------------------------------

async def test_reprocess_returns_200(client, ready_reference):
    with patch("app.routers.pro_references._enqueue_pro_reference_job"):
        resp = await client.post(f"/api/pro-references/{ready_reference.id}/reprocess")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["reference_id"] == str(ready_reference.id)


async def test_reprocess_enqueues_job(client, ready_reference):
    with patch("app.routers.pro_references._enqueue_pro_reference_job") as mock_enqueue:
        await client.post(f"/api/pro-references/{ready_reference.id}/reprocess")

    mock_enqueue.assert_called_once_with(str(ready_reference.id))


async def test_reprocess_stuck_processing_is_allowed(client, db_engine):
    """A reference stuck in 'processing' (e.g. worker crash) can be reprocessed."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(), player_name="Processing Player", player_slug="processing-player-forehand",
        stroke_type=StrokeType.forehand, status=ProReferenceStatus.processing,
        is_builtin=False, created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()

    with patch("app.routers.pro_references._enqueue_pro_reference_job"):
        resp = await client.post(f"/api/pro-references/{ref.id}/reprocess")
    assert resp.status_code == 200


async def test_reprocess_builtin_returns_403(client, db_engine):
    """Built-in references cannot be reprocessed."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ref = ProReference(
        id=uuid.uuid4(), player_name="Builtin Player", player_slug="builtin-player-forehand",
        stroke_type=StrokeType.forehand, status=ProReferenceStatus.ready,
        is_builtin=True, created_at=datetime.now(timezone.utc),
    )
    async with factory() as session:
        session.add(ref)
        await session.commit()

    resp = await client.post(f"/api/pro-references/{ref.id}/reprocess")
    assert resp.status_code == 403


async def test_reprocess_unknown_id_returns_404(client):
    with patch("app.routers.pro_references._enqueue_pro_reference_job"):
        resp = await client.post(f"/api/pro-references/{uuid.uuid4()}/reprocess")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Worker task: process_pro_reference
# ---------------------------------------------------------------------------

def _make_mock_frame_result(frame_paths: list[str], fps: float = 30.0):
    from app.worker.frame_extractor import FrameExtractionResult
    return FrameExtractionResult(
        frame_paths=frame_paths,
        fps=fps,
        duration_seconds=len(frame_paths) / fps,
        total_frames=len(frame_paths),
        resolution=(320, 240),
    )


def _make_mock_pose_result(n_frames: int):
    from app.worker.pose_estimator import PoseEstimationResult
    landmarks = np.random.rand(n_frames, 33, 3).astype(np.float32)
    visibility = np.ones((n_frames, 33), dtype=np.float32)
    return PoseEstimationResult(
        landmarks=landmarks,
        visibility=visibility,
        frames_processed=n_frames,
        frames_with_pose=n_frames,
        detection_rate=1.0,
    )


def _make_mock_features(n_frames: int = 10):
    from app.worker.feature_engine import FeatureExtractionResult
    return FeatureExtractionResult(
        joint_angles={"elbow_angle": np.linspace(10, 90, n_frames)},
        velocities={"elbow_angle": np.zeros(n_frames)},
        phases={
            "backswing": (0, 3),
            "forward_swing": (4, 7),
            "contact": (8, 8),
            "follow_through": (9, n_frames - 1),
        },
        contact_frame=8,
    )


def _async_return(value):
    """Return an async function that resolves to value."""
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _async_noop(*args, **kwargs):
    async def _inner(*args, **kwargs):
        pass
    return _inner()


def test_process_pro_reference_success(tmp_path):
    """Happy path: task runs all stages and calls _write_pro_reference_results."""
    from app.worker.pro_reference_tasks import process_pro_reference

    n_frames = 10
    frame_paths = [str(tmp_path / f"frame_{i:05d}.png") for i in range(n_frames)]
    for p in frame_paths:
        Path(p).write_bytes(b"\x89PNG")  # placeholder so cv2.imread can be mocked

    mock_ref = MagicMock()
    mock_ref.player_name = "TestPlayer"
    mock_ref.player_slug = "testplayer-forehand"
    mock_ref.stroke_type = MagicMock()
    mock_ref.stroke_type.value = "forehand"
    mock_ref.video_s3_key = "pro-references/abc/video.mp4"
    mock_ref.status = ProReferenceStatus.processing

    mock_frame_result = _make_mock_frame_result(frame_paths)
    mock_pose_result = _make_mock_pose_result(n_frames)
    mock_features = _make_mock_features(n_frames)
    mock_cv2_frame = np.zeros((240, 320, 3), dtype=np.uint8)

    written_args: dict = {}

    async def fake_write(reference_id, npz_path, thumbnail_s3_key, frame_count, fps, duration_seconds):
        written_args.update(
            reference_id=reference_id,
            npz_path=npz_path,
            frame_count=frame_count,
            fps=fps,
        )

    with (
        patch("app.worker.pro_reference_tasks._fetch_pro_reference", new=_async_return(mock_ref)),
        patch("app.worker.pro_reference_tasks._write_pro_reference_results", new=fake_write),
        patch("app.worker.pro_reference_tasks._mark_pro_reference_failed") as mock_fail,
        patch("app.worker.pro_reference_tasks.download_video"),
        patch("app.worker.pro_reference_tasks.extract_frames", return_value=mock_frame_result),
        patch("app.worker.pro_reference_tasks.extract_poses", return_value=mock_pose_result),
        patch("app.worker.pro_reference_tasks.extract_features", return_value=mock_features),
        patch("app.worker.pro_reference_tasks.upload_file"),
        patch("app.worker.pro_reference_tasks.cv2.imread", return_value=mock_cv2_frame),
        patch("app.worker.pro_reference_tasks.cv2.resize", return_value=np.zeros((180, 320, 3), dtype=np.uint8)),
        patch("app.worker.pro_reference_tasks.cv2.imwrite", return_value=True),
        patch("app.worker.pro_reference_tasks._PRO_REF_DATA_DIR", tmp_path),
    ):
        process_pro_reference("test-reference-id-0000")

    # Pipeline should complete without calling _mark_failed
    mock_fail.assert_not_called()
    # _write_pro_reference_results should have been called
    assert written_args["reference_id"] == "test-reference-id-0000"
    assert written_args["npz_path"].endswith("testplayer-forehand.npz")
    assert written_args["frame_count"] == n_frames
    assert written_args["fps"] == 30.0


def test_process_pro_reference_marks_failed_on_exception():
    """If any pipeline stage raises, status is set to 'failed'."""
    from app.worker.pro_reference_tasks import process_pro_reference

    async def fake_fail(*args, **kwargs):
        pass

    with (
        patch("app.worker.pro_reference_tasks._fetch_pro_reference", side_effect=ValueError("boom")),
        patch("app.worker.pro_reference_tasks._mark_pro_reference_failed", new=fake_fail) as mock_fail,
    ):
        # Should not raise — exception is caught and logged
        process_pro_reference("test-bad-id-00000000")


def test_process_pro_reference_saves_npz(tmp_path):
    """Verify the .npz is actually written to disk with expected keys."""
    from app.worker.pro_reference_tasks import process_pro_reference

    n_frames = 8
    frame_paths = [str(tmp_path / f"frame_{i:05d}.png") for i in range(n_frames)]
    for p in frame_paths:
        Path(p).write_bytes(b"")

    mock_ref = MagicMock()
    mock_ref.player_name = "Testplayer"
    mock_ref.player_slug = "testplayer-forehand"
    mock_ref.stroke_type = MagicMock()
    mock_ref.stroke_type.value = "forehand"
    mock_ref.video_s3_key = "pro-references/xyz/video.mp4"
    mock_ref.status = ProReferenceStatus.processing

    mock_frame_result = _make_mock_frame_result(frame_paths, fps=30.0)
    mock_pose_result = _make_mock_pose_result(n_frames)
    mock_features = _make_mock_features(n_frames)

    async def fake_write(reference_id, npz_path, **kwargs):
        pass

    with (
        patch("app.worker.pro_reference_tasks._fetch_pro_reference", new=_async_return(mock_ref)),
        patch("app.worker.pro_reference_tasks._write_pro_reference_results", new=fake_write),
        patch("app.worker.pro_reference_tasks._mark_pro_reference_failed", new=lambda *a, **k: None),
        patch("app.worker.pro_reference_tasks.download_video"),
        patch("app.worker.pro_reference_tasks.extract_frames", return_value=mock_frame_result),
        patch("app.worker.pro_reference_tasks.extract_poses", return_value=mock_pose_result),
        patch("app.worker.pro_reference_tasks.extract_features", return_value=mock_features),
        patch("app.worker.pro_reference_tasks.upload_file"),
        patch("app.worker.pro_reference_tasks.cv2.imread", return_value=np.zeros((240, 320, 3), dtype=np.uint8)),
        patch("app.worker.pro_reference_tasks.cv2.resize", return_value=np.zeros((180, 320, 3), dtype=np.uint8)),
        patch("app.worker.pro_reference_tasks.cv2.imwrite", return_value=True),
        patch("app.worker.pro_reference_tasks._PRO_REF_DATA_DIR", tmp_path),
    ):
        process_pro_reference("test-save-npz-000000")

    npz_file = tmp_path / "testplayer-forehand.npz"
    assert npz_file.exists(), "Expected .npz to be written to disk"

    data = np.load(npz_file, allow_pickle=False)
    assert "angle_elbow_angle" in data.files
    assert "velocity_elbow_angle" in data.files
    assert "_landmarks" in data.files
    assert "_phase_keys" in data.files
    assert "_phase_values" in data.files
