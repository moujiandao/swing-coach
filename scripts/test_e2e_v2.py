"""
End-to-end V2 pipeline test — runs manually, not via pytest.

Usage (from project root):
    uv --project backend run python scripts/test_e2e_v2.py

Requirements:
    - ffmpeg on PATH
    - No Redis, S3, or running server needed — pipeline functions run in-process
    - A synthetic_forehand.npz is NOT required — the test creates its own pro reference

What this tests:
    - ProReference pipeline: synthetic video -> frames -> pose -> features -> .npz -> DB
    - Analysis pipeline: synthetic video -> pose -> DTW -> phase alignment -> deviation annotation
    - Overlay data integrity: frame counts, mapping length, phase boundaries
"""
import asyncio
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Analysis,
    AnalysisStatus,
    Base,
    ProReference,
    ProReferenceStatus,
    StrokeType,
    slugify,
)
from app.worker.pose_estimator import PoseEstimationResult
from app.worker.pro_reference_tasks import process_pro_reference
from app.worker.tasks import process_analysis


# ---------------------------------------------------------------------------
# In-memory SQLite DB shared by both pipeline stages
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def _setup_db() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# Test record creation helpers
# ---------------------------------------------------------------------------

async def _create_pro_reference(player_name: str, video_s3_key: str) -> str:
    ref_id = uuid.uuid4()
    async with _session_factory() as session:
        ref = ProReference(
            id=ref_id,
            player_name=player_name,
            player_slug=slugify(player_name),
            stroke_type=StrokeType.forehand,
            video_s3_key=video_s3_key,
            status=ProReferenceStatus.processing,
            is_builtin=False,
            created_at=datetime.now(timezone.utc),
        )
        session.add(ref)
        await session.commit()
    return str(ref_id)


async def _create_analysis(video_s3_key: str, pro_reference_id: str) -> str:
    analysis_id = uuid.uuid4()
    async with _session_factory() as session:
        analysis = Analysis(
            id=analysis_id,
            status=AnalysisStatus.pending,
            stroke_type=StrokeType.forehand,
            pro_reference="e2e-test",
            pro_reference_id=uuid.UUID(pro_reference_id),
            video_s3_key=video_s3_key,
            created_at=datetime.now(timezone.utc),
        )
        session.add(analysis)
        await session.commit()
    return str(analysis_id)


async def _fetch_analysis_record(analysis_id: str) -> Analysis:
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == uuid.UUID(analysis_id))
        )
        return result.scalar_one()


async def _fetch_pro_reference_record(reference_id: str) -> ProReference:
    async with _session_factory() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == uuid.UUID(reference_id))
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------
# Patched async DB helpers — redirect all get_session() calls to test DB
# ---------------------------------------------------------------------------

async def _patched_fetch_pro_ref_for_task(reference_id: str) -> ProReference:
    return await _fetch_pro_reference_record(reference_id)


async def _patched_write_pro_ref_results(
    reference_id: str,
    npz_path: str,
    thumbnail_s3_key,
    frame_count: int,
    fps: float,
    duration_seconds: float,
) -> None:
    async with _session_factory() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == uuid.UUID(reference_id))
        )
        ref = result.scalar_one()
        ref.status = ProReferenceStatus.ready
        ref.npz_path = npz_path
        ref.thumbnail_s3_key = thumbnail_s3_key
        ref.frame_count = frame_count
        ref.fps = fps
        ref.duration_seconds = duration_seconds
        ref.processed_at = datetime.now(timezone.utc)
        ref.error_message = None
        await session.commit()


async def _patched_mark_pro_ref_failed(reference_id: str, error: str) -> None:
    async with _session_factory() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == uuid.UUID(reference_id))
        )
        ref = result.scalar_one_or_none()
        if ref is not None:
            ref.status = ProReferenceStatus.failed
            ref.error_message = error
            await session.commit()


async def _patched_fetch_analysis(analysis_id: str) -> Analysis:
    return await _fetch_analysis_record(analysis_id)


async def _patched_fetch_pro_ref_for_analysis(pro_reference_id) -> ProReference | None:
    # tasks.py passes a UUID object, not a string
    ref_id = str(pro_reference_id) if not isinstance(pro_reference_id, str) else pro_reference_id
    return await _fetch_pro_reference_record(ref_id)


async def _patched_write_results(
    analysis_id: str,
    pose_data,
    phase_scores,
    deviations,
    coaching_feedback,
    overall_score,
    processing_time_ms,
    pro_landmarks=None,
    aligned_pro_landmarks=None,
    frame_mapping=None,
    frame_deviations=None,
    phase_boundaries=None,
    fps=None,
    keyframe_s3_keys=None,
) -> None:
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == uuid.UUID(analysis_id))
        )
        a = result.scalar_one()
        a.status = AnalysisStatus.completed
        a.pose_data = pose_data
        a.phase_scores = phase_scores
        a.deviations = deviations
        a.coaching_feedback = coaching_feedback
        a.overall_score = overall_score
        a.pro_landmarks = pro_landmarks
        a.aligned_pro_landmarks = aligned_pro_landmarks
        a.frame_mapping = frame_mapping
        a.frame_deviations = frame_deviations
        a.phase_boundaries = phase_boundaries
        a.fps = fps
        a.keyframe_s3_keys = keyframe_s3_keys
        a.completed_at = datetime.now(timezone.utc)
        a.processing_time_ms = processing_time_ms
        await session.commit()


async def _patched_mark_failed(analysis_id: str, error: str) -> None:
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == uuid.UUID(analysis_id))
        )
        a = result.scalar_one_or_none()
        if a is not None:
            a.status = AnalysisStatus.failed
            a.error_message = error
            await session.commit()


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_synthetic_pose(n_frames: int, seed: int = 42) -> PoseEstimationResult:
    """Return a pose estimation result without running MediaPipe."""
    rng = np.random.default_rng(seed)
    landmarks = rng.uniform(0.2, 0.8, (n_frames, 33, 3)).astype(np.float32)
    # Give the right wrist (index 16) a sinusoidal trajectory for phase detection
    t = np.linspace(0, 2 * np.pi, n_frames)
    landmarks[:, 16, 0] = 0.5 + 0.3 * np.sin(t)
    visibility = rng.uniform(0.7, 1.0, (n_frames, 33)).astype(np.float32)
    return PoseEstimationResult(
        landmarks=landmarks,
        visibility=visibility,
        frames_processed=n_frames,
        frames_with_pose=n_frames,
        detection_rate=1.0,
    )


def _create_test_video(path: str, duration_s: int = 3, fps: int = 30) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-f", "lavfi",
            "-i", f"color=c=navy:size=320x240:rate={fps}",
            "-t", str(duration_s),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            path,
            "-y",
        ],
        capture_output=True,
        check=True,
    )


def _patched_download_video(s3_key: str, local_path: str) -> None:
    """s3_key holds the actual test video path for this test."""
    shutil.copy2(s3_key, local_path)


def _patched_upload_file(*args, **kwargs) -> None:
    """No-op: skip actual S3 uploads during the test."""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:  # noqa: PLR0915
    print("=" * 65)
    print("SwingCoach E2E V2 Test — Pro Library + Visual Overlay")
    print("=" * 65)

    # Track cleanup paths
    npz_path_to_cleanup: str | None = None
    errors: list[str] = []

    asyncio.run(_setup_db())
    print("[1/9] In-memory SQLite DB created")

    with tempfile.TemporaryDirectory() as tmpdir:
        # ----------------------------------------------------------------
        # PHASE A — Pro Reference pipeline
        # ----------------------------------------------------------------
        pro_video_path = str(Path(tmpdir) / "pro_swing.mp4")
        _create_test_video(pro_video_path)
        print(f"[2/9] Synthetic pro reference video created")

        ref_id = asyncio.run(
            _create_pro_reference("E2E Test Player", video_s3_key=pro_video_path)
        )
        print(f"[3/9] ProReference record created (id={ref_id[:8]}...)")

        pro_pose = _make_synthetic_pose(n_frames=30, seed=42)

        with (
            patch("app.worker.pro_reference_tasks.download_video",
                  side_effect=_patched_download_video),
            patch("app.worker.pro_reference_tasks.extract_poses",
                  return_value=pro_pose),
            patch("app.worker.pro_reference_tasks.upload_file",
                  side_effect=_patched_upload_file),
            patch("app.worker.pro_reference_tasks._fetch_pro_reference",
                  side_effect=_patched_fetch_pro_ref_for_task),
            patch("app.worker.pro_reference_tasks._write_pro_reference_results",
                  side_effect=_patched_write_pro_ref_results),
            patch("app.worker.pro_reference_tasks._mark_pro_reference_failed",
                  side_effect=_patched_mark_pro_ref_failed),
        ):
            print("[4/9] Running process_pro_reference() ...")
            process_pro_reference(ref_id)

        # Verify pro reference record
        pro_ref = asyncio.run(_fetch_pro_reference_record(ref_id))
        print(f"[5/9] ProReference status: {pro_ref.status.value}")

        if pro_ref.status != ProReferenceStatus.ready:
            errors.append(
                f"ProReference status is '{pro_ref.status.value}', expected 'ready'"
            )
            if pro_ref.error_message:
                errors.append(f"  ProReference error: {pro_ref.error_message}")
        if not pro_ref.npz_path:
            errors.append("ProReference npz_path is None")
        if not pro_ref.frame_count or pro_ref.frame_count <= 0:
            errors.append("ProReference frame_count is 0 or None")
        npz_path_to_cleanup = pro_ref.npz_path

        # ----------------------------------------------------------------
        # PHASE B — Analysis pipeline
        # ----------------------------------------------------------------
        user_video_path = str(Path(tmpdir) / "user_swing.mp4")
        _create_test_video(user_video_path)
        print(f"[6/9] Synthetic user swing video created")

        analysis_id = asyncio.run(
            _create_analysis(video_s3_key=user_video_path, pro_reference_id=ref_id)
        )
        print(f"[7/9] Analysis record created (id={analysis_id[:8]}...)")

        # Slightly different pose: different seed + fewer frames to exercise resampling
        user_pose = _make_synthetic_pose(n_frames=25, seed=99)

        with (
            patch("app.worker.tasks.download_video",
                  side_effect=_patched_download_video),
            patch("app.worker.tasks.extract_poses",
                  return_value=user_pose),
            patch("app.worker.tasks.upload_file",
                  side_effect=_patched_upload_file),
            patch("app.worker.tasks._fetch_analysis",
                  side_effect=_patched_fetch_analysis),
            patch("app.worker.tasks._fetch_pro_reference",
                  side_effect=_patched_fetch_pro_ref_for_analysis),
            patch("app.worker.tasks._write_results",
                  side_effect=_patched_write_results),
            patch("app.worker.tasks._mark_failed",
                  side_effect=_patched_mark_failed),
        ):
            print("[8/9] Running process_analysis() ...")
            process_analysis(analysis_id)

    # ----------------------------------------------------------------
    # PHASE C — Overlay verification (simulates GET /api/analysis/{id}/overlay)
    # ----------------------------------------------------------------
    analysis = asyncio.run(_fetch_analysis_record(analysis_id))
    print(f"[9/9] Analysis status: {analysis.status.value}")

    user_landmarks = analysis.pose_data or []
    pro_landmarks  = analysis.aligned_pro_landmarks or []
    frame_mapping  = analysis.frame_mapping or []
    frame_devs     = analysis.frame_deviations or []
    phase_bounds   = analysis.phase_boundaries or {}

    user_frame_count = len(user_landmarks)
    pro_frame_count  = len(pro_landmarks)

    # ----------------------------------------------------------------
    # Summary table
    # ----------------------------------------------------------------
    print()
    print("─" * 65)
    score_str = f"{analysis.overall_score:.1f}" if analysis.overall_score is not None else "N/A"
    print(f"  Overall score:         {score_str}")
    print(f"  Deviations detected:   {len(analysis.deviations or [])}")
    print(f"  User frames:           {user_frame_count}")
    print(f"  Pro frames (aligned):  {pro_frame_count}")
    print(f"  Frame mapping length:  {len(frame_mapping)}")
    print(f"  Frame deviations:      {len(frame_devs)}")
    print(f"  Phase boundaries:      {list(phase_bounds.keys())}")
    print(f"  FPS:                   {analysis.fps}")

    if phase_bounds:
        print()
        print("  Per-phase tempo ratios:")
        for phase, pb in phase_bounds.items():
            ratio = pb.get("tempo_ratio", "?")
            print(f"    {phase:<20} {ratio}")

    print("─" * 65)

    # ----------------------------------------------------------------
    # Assertions
    # ----------------------------------------------------------------
    if analysis.status != AnalysisStatus.completed:
        errors.append(f"Analysis status is '{analysis.status.value}', expected 'completed'")
    if analysis.overall_score is None:
        errors.append("overall_score is None")
    if analysis.pose_data is None:
        errors.append("pose_data (user_landmarks) is None")
    if analysis.aligned_pro_landmarks is None:
        errors.append("aligned_pro_landmarks is None")
    if analysis.frame_mapping is None:
        errors.append("frame_mapping is None")
    if analysis.frame_deviations is None:
        errors.append("frame_deviations is None")
    if analysis.phase_boundaries is None:
        errors.append("phase_boundaries is None")

    # Overlay-specific checks
    if user_frame_count != pro_frame_count:
        errors.append(
            f"user_landmarks ({user_frame_count} frames) != pro_landmarks ({pro_frame_count} frames)"
        )
    if len(frame_mapping) != user_frame_count:
        errors.append(
            f"frame_mapping length ({len(frame_mapping)}) != user frame count ({user_frame_count})"
        )
    if len(frame_devs) == 0:
        # Soft warning — synthetic random data may not always exceed the deviation threshold
        print("  NOTE: frame_deviations is empty (synthetic data may not exceed 10° threshold)")
    if len(phase_bounds) == 0:
        errors.append("phase_boundaries is empty")

    # Cleanup the .npz written to disk
    if npz_path_to_cleanup and Path(npz_path_to_cleanup).exists():
        Path(npz_path_to_cleanup).unlink()
        print(f"  Cleaned up .npz: {npz_path_to_cleanup}")

    print()
    if errors:
        print(f"FAIL — {len(errors)} assertion(s) failed:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("PASS — all assertions passed")


if __name__ == "__main__":
    main()
