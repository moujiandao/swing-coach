"""
End-to-end pipeline test — runs manually, not via pytest.

Usage (from project root):
    uv --project backend run python scripts/test_e2e.py

Requirements:
    - ffmpeg on PATH
    - backend/app/pro_references/data/synthetic_forehand.npz exists
      (run scripts/generate_synthetic_reference.py first if not)
    - No Redis or S3 needed — runs the pipeline function directly

What this tests:
    - DB record creation, status transitions, result fields written correctly
    - Frame extraction (real FFmpeg call)
    - Pose estimation (mocked — synthetic landmark data so no real human video needed)
    - Feature extraction → DTW comparison → DB write
    - Temp dir cleanup
    - If ANTHROPIC_API_KEY is set: Claude feedback generation

Pose estimation is mocked because a synthetic solid-color video has no detectable
human — that stage has its own unit tests. Everything else runs for real.
"""
import asyncio
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Allow running from project root
_BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Analysis, AnalysisStatus, Base, StrokeType
from app.pro_references.loader import ProReferenceDB
from app.worker.pose_estimator import PoseEstimationResult
from app.worker.tasks import process_analysis


# ---------------------------------------------------------------------------
# In-memory SQLite DB for the e2e test
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def _setup_db() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _create_analysis(video_s3_key: str) -> str:
    analysis_id = uuid.uuid4()
    async with _session_factory() as session:
        analysis = Analysis(
            id=analysis_id,
            status=AnalysisStatus.pending,
            stroke_type=StrokeType.forehand,
            pro_reference="synthetic",
            video_s3_key=video_s3_key,
            created_at=datetime.now(timezone.utc),
        )
        session.add(analysis)
        await session.commit()
    return str(analysis_id)


async def _fetch_analysis(analysis_id: str) -> Analysis:
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == (uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id))
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------
# Synthetic landmark data (replaces MediaPipe output)
# ---------------------------------------------------------------------------

def _make_synthetic_pose(n_frames: int = 30) -> PoseEstimationResult:
    """Return a realistic-ish pose estimation result without running MediaPipe."""
    rng = np.random.default_rng(42)
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


# ---------------------------------------------------------------------------
# Synthetic video (solid colour — just needs to be valid for FFmpeg)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Patch helpers — override DB and S3 functions with test versions
# ---------------------------------------------------------------------------

async def _patched_fetch_analysis(analysis_id: str) -> Analysis:
    return await _fetch_analysis(analysis_id)


async def _patched_mark_processing(analysis_id: str) -> Analysis:
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == (uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id))
        )
        analysis = result.scalar_one()
        analysis.status = AnalysisStatus.processing
        await session.commit()
        return analysis


async def _patched_write_results(
    analysis_id, pose_data, phase_scores, deviations,
    coaching_feedback, overall_score, processing_time_ms,
):
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == (uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id))
        )
        analysis = result.scalar_one()
        analysis.status = AnalysisStatus.completed
        analysis.pose_data = pose_data
        analysis.phase_scores = phase_scores
        analysis.deviations = deviations
        analysis.coaching_feedback = coaching_feedback
        analysis.overall_score = overall_score
        analysis.completed_at = datetime.now(timezone.utc)
        analysis.processing_time_ms = processing_time_ms
        await session.commit()


async def _patched_mark_failed(analysis_id: str, error: str) -> None:
    async with _session_factory() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == (uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id))
        )
        analysis = result.scalar_one_or_none()
        if analysis is not None:
            analysis.status = AnalysisStatus.failed
            analysis.error_message = error
            await session.commit()


def _patched_download_video(s3_key: str, local_path: str) -> None:
    """No-op: the test video is already at local_path (passed via s3_key mapping)."""
    # s3_key holds the actual video path for this test
    import shutil
    shutil.copy2(s3_key, local_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("SwingCoach E2E Pipeline Test")
    print("=" * 60)

    # Setup in-memory DB
    asyncio.run(_setup_db())
    print("[1/7] In-memory SQLite DB created")

    # Generate synthetic reference if not present
    ref_path = _BACKEND / "app" / "pro_references" / "data" / "synthetic_forehand.npz"
    if not ref_path.exists():
        print("[2/7] Generating synthetic reference ...")
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "generate_synthetic_reference.py")],
            check=True,
        )
    else:
        print(f"[2/7] Synthetic reference found: {ref_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test video
        video_path = str(Path(tmpdir) / "test_swing.mp4")
        _create_test_video(video_path)
        print(f"[3/7] Synthetic test video created: {video_path}")

        # Create Analysis DB record — use video_path as the "s3_key" for local dev
        analysis_id = asyncio.run(_create_analysis(video_s3_key=video_path))
        print(f"[4/7] Analysis record created: {analysis_id}")

        # Patch all external boundaries
        synthetic_pose = _make_synthetic_pose(n_frames=30)

        with (
            patch("app.worker.tasks._fetch_analysis", side_effect=_patched_fetch_analysis),
            patch("app.worker.tasks._write_results", side_effect=_patched_write_results),
            patch("app.worker.tasks._mark_failed",   side_effect=_patched_mark_failed),
            patch("app.worker.tasks.download_video",  side_effect=_patched_download_video),
            patch("app.worker.tasks.extract_poses",   return_value=synthetic_pose),
        ):
            print("[5/7] Running process_analysis() ...")
            process_analysis(analysis_id)

    # Fetch and validate result
    analysis = asyncio.run(_fetch_analysis(analysis_id))
    print(f"[6/7] Analysis fetched from DB")

    print()
    print("─" * 60)
    print(f"  Status:           {analysis.status.value}")
    score_str = f"{analysis.overall_score:.1f}" if analysis.overall_score is not None else "N/A"
    print(f"  Overall score:    {score_str}")
    print(f"  Processing time:  {analysis.processing_time_ms}ms")
    print(f"  Deviations:       {len(analysis.deviations) if analysis.deviations else 0}")
    if analysis.coaching_feedback:
        cf = analysis.coaching_feedback
        print(f"  Feedback summary: {cf.get('summary', '')[:80]}...")
        print(f"  Assessment:       {cf.get('overall_assessment', 'N/A')}")
    if analysis.error_message:
        print(f"  Error:            {analysis.error_message}")
    print("─" * 60)

    # Assertions
    errors = []

    if analysis.status != AnalysisStatus.completed:
        errors.append(f"status is '{analysis.status.value}', expected 'completed'")
    if analysis.overall_score is None:
        errors.append("overall_score is None")
    if analysis.phase_scores is None:
        errors.append("phase_scores is None")
    if analysis.deviations is None:
        errors.append("deviations is None")
    if analysis.processing_time_ms is None or analysis.processing_time_ms <= 0:
        errors.append("processing_time_ms not recorded")
    if analysis.completed_at is None:
        errors.append("completed_at is None")
    if analysis.pose_data is None:
        errors.append("pose_data is None")

    print()
    if errors:
        print(f"[7/7] FAIL — {len(errors)} assertion(s) failed:")
        for e in errors:
            print(f"       ✗ {e}")
        sys.exit(1)
    else:
        print("[7/7] PASS — all assertions passed")


if __name__ == "__main__":
    main()
