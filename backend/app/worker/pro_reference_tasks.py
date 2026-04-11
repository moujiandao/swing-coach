"""
RQ worker task: build a .npz pro reference file from an uploaded video.

Pipeline (subset of the full analysis pipeline — no DTW or Claude feedback):
  download video → extract frames → pose estimation → feature extraction
  → generate thumbnail → save .npz → update DB → cleanup
"""
import asyncio
import logging
import shutil
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import uuid as _uuid
from sqlalchemy import select

from app.models import ProReference, ProReferenceStatus, StrokeType
from app.services.db import get_session
from app.services.s3 import download_video, upload_file
from app.worker.feature_engine import extract_features
from app.worker.frame_extractor import extract_frames
from app.worker.pose_estimator import extract_poses
from app.worker.racquet_detector import detect_racquets, serialize_detections
from app.pro_references.loader import save_reference

logger = logging.getLogger(__name__)

# Where .npz files are written — mirrors the static reference location so
# ProReferenceDB.load_all() picks them up as a fallback.
_PRO_REF_DATA_DIR = Path(__file__).parent.parent / "pro_references" / "data"


# ---------------------------------------------------------------------------
# Async DB helpers (called via asyncio.run() from the synchronous RQ task)
# ---------------------------------------------------------------------------

async def _fetch_pro_reference(reference_id: str) -> ProReference:
    ref_uuid = _uuid.UUID(reference_id) if isinstance(reference_id, str) else reference_id
    async with get_session() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == ref_uuid)
        )
        ref = result.scalar_one_or_none()
        if ref is None:
            raise ValueError(f"ProReference {reference_id} not found")
        if ref.status != ProReferenceStatus.processing:
            raise ValueError(
                f"ProReference {reference_id} has status '{ref.status.value}', expected 'processing'"
            )
        return ref


async def _write_pro_reference_results(
    reference_id: str,
    npz_path: str,
    thumbnail_s3_key: str | None,
    frame_count: int,
    fps: float,
    duration_seconds: float,
) -> None:
    ref_uuid = _uuid.UUID(reference_id) if isinstance(reference_id, str) else reference_id
    async with get_session() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == ref_uuid)
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


async def _mark_pro_reference_failed(reference_id: str, error: str) -> None:
    try:
        ref_uuid = _uuid.UUID(reference_id) if isinstance(reference_id, str) else reference_id
        async with get_session() as session:
            result = await session.execute(
                select(ProReference).where(ProReference.id == ref_uuid)
            )
            ref = result.scalar_one_or_none()
            if ref is not None:
                ref.status = ProReferenceStatus.failed
                ref.error_message = error
    except Exception:
        logger.exception("Failed to write error status for pro reference %s", reference_id)


# ---------------------------------------------------------------------------
# Racquet data upsampling helper
# ---------------------------------------------------------------------------

def _upsample_racquet_data(racquet_data: list, target_len: int) -> list:
    """
    Upsample racquet detection data to match upsampled landmark frame count.
    Uses linear interpolation for coordinates, sets confidence to 0.0 for
    interpolated frames to distinguish them from real detections.
    """
    n = len(racquet_data)
    if n == target_len or n < 2:
        return racquet_data

    # Convert to numpy: each frame is [base_x, base_y, tip_x, tip_y, conf] or None
    arr = np.zeros((n, 5), dtype=np.float32)
    for i, item in enumerate(racquet_data):
        if item is not None:
            arr[i] = item

    t_old = np.linspace(0.0, 1.0, n)
    t_new = np.linspace(0.0, 1.0, target_len)

    # Interpolate coordinates (first 4 columns) linearly
    from scipy.interpolate import interp1d
    coord_interp = interp1d(t_old, arr[:, :4], axis=0, kind="linear")
    new_coords = coord_interp(t_new)

    # Confidence: only keep original-frame confidence, set interpolated to 0.0
    new_conf = np.zeros(target_len, dtype=np.float32)
    for i in range(n):
        nearest = int(round(i * (target_len - 1) / (n - 1)))
        new_conf[nearest] = arr[i, 4]

    result = []
    for i in range(target_len):
        result.append([float(new_coords[i, 0]), float(new_coords[i, 1]),
                        float(new_coords[i, 2]), float(new_coords[i, 3]),
                        float(new_conf[i])])
    return result


# ---------------------------------------------------------------------------
# Thumbnail helper
# ---------------------------------------------------------------------------

def _generate_thumbnail(frame_paths: list[str], work_dir: str) -> str | None:
    """
    Extract the middle frame, resize to 320x180 JPEG.
    Returns the local path to the thumbnail, or None if it fails.
    """
    if not frame_paths:
        return None

    mid_index = len(frame_paths) // 2
    frame_path = frame_paths[mid_index]

    frame = cv2.imread(frame_path)
    if frame is None:
        logger.warning("Could not read middle frame for thumbnail: %s", frame_path)
        return None

    thumb = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
    thumb_path = str(Path(work_dir) / "thumbnail.jpg")
    cv2.imwrite(thumb_path, thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return thumb_path


# ---------------------------------------------------------------------------
# Main RQ task
# ---------------------------------------------------------------------------

def process_pro_reference(reference_id: str) -> None:
    """
    RQ task. Builds a .npz pro reference file from an uploaded video.

    Does NOT re-raise exceptions — RQ will record the job as failed via its own
    mechanisms; the ProReference record carries status='failed'.
    """
    work_dir: str | None = None
    t_start = time.perf_counter()

    try:
        logger.info("[pro-ref %s] Pipeline start", reference_id)

        # 1. Fetch record, verify status is "processing"
        ref = asyncio.run(_fetch_pro_reference(reference_id))
        player_name = ref.player_name
        player_slug = ref.player_slug
        stroke_type = ref.stroke_type.value
        s3_key = ref.video_s3_key

        # 2. Create temp working directory
        work_dir = tempfile.mkdtemp(prefix=f"proref_{reference_id[:8]}_")
        video_path = str(Path(work_dir) / "video.mp4")

        # 3. Download video from S3 (or local dev uploads/)
        t0 = time.perf_counter()
        logger.info("[pro-ref %s] Downloading video (key=%s)", reference_id, s3_key)
        download_video(s3_key, video_path)
        logger.info("[pro-ref %s] Download done (%.1fs)", reference_id, time.perf_counter() - t0)

        # 4. Extract frames
        t0 = time.perf_counter()
        frames_dir = str(Path(work_dir) / "frames")
        frame_result = extract_frames(video_path, output_dir=frames_dir)
        fps = frame_result.fps
        duration_seconds = frame_result.duration_seconds
        logger.info(
            "[pro-ref %s] Frames done: %d frames @ %.1f fps (%.1fs)",
            reference_id, len(frame_result.frame_paths), fps, time.perf_counter() - t0,
        )

        # 5. Pose estimation
        t0 = time.perf_counter()
        pose_result = extract_poses(frame_result.frame_paths)
        logger.info(
            "[pro-ref %s] Pose done: detection_rate=%.0f%% (%.1fs)",
            reference_id, pose_result.detection_rate * 100, time.perf_counter() - t0,
        )

        # 5.5. Racquet detection (YOLO) — non-fatal
        racquet_data_serialized: list | None = None
        try:
            t0 = time.perf_counter()
            logger.info("[pro-ref %s] Running racquet detection (YOLO)", reference_id)
            wrist_xy = pose_result.landmarks[:, 16, :2]
            racquet_result = detect_racquets(frame_result.frame_paths, wrist_landmarks=wrist_xy)
            racquet_data_serialized = serialize_detections(racquet_result.detections)
            logger.info(
                "[pro-ref %s] Racquet detection done: rate=%.0f%% (%.1fs)",
                reference_id, racquet_result.detection_rate * 100, time.perf_counter() - t0,
            )
        except Exception as rq_exc:
            logger.warning("[pro-ref %s] Racquet detection failed (non-fatal): %s", reference_id, rq_exc)

        # 5.7. Upsample landmarks if source fps is low (< 50fps)
        # Low-fps videos produce degenerate phase boundaries (e.g., 1-frame backswing).
        # Cubic spline interpolation to 60fps gives the phase detector enough data points.
        landmarks_for_features = pose_result.landmarks
        effective_fps = fps
        original_frame_count = len(frame_result.frame_paths)
        if fps < 50.0:
            from app.worker.feature_engine import upsample_landmarks
            landmarks_for_features, effective_fps = upsample_landmarks(
                pose_result.landmarks, source_fps=fps,
            )
            logger.info(
                "[pro-ref %s] Upsampled landmarks: %d → %d frames (%.1f → %.1f fps)",
                reference_id, pose_result.landmarks.shape[0],
                landmarks_for_features.shape[0], fps, effective_fps,
            )

            # Also upsample racquet data to match new frame count
            if racquet_data_serialized is not None:
                racquet_data_serialized = _upsample_racquet_data(
                    racquet_data_serialized, landmarks_for_features.shape[0],
                )

        # 6. Feature extraction
        t0 = time.perf_counter()
        features = extract_features(
            landmarks=landmarks_for_features,
            fps=effective_fps,
            stroke_type=stroke_type,
            handedness="right",
        )
        logger.info("[pro-ref %s] Features done (%.1fs)", reference_id, time.perf_counter() - t0)

        # 7. Generate thumbnail from middle frame
        t0 = time.perf_counter()
        thumb_local_path = _generate_thumbnail(frame_result.frame_paths, work_dir)
        thumbnail_s3_key: str | None = None
        if thumb_local_path:
            thumbnail_s3_key = f"pro-references/{reference_id}/thumbnail.jpg"
            upload_file(thumb_local_path, thumbnail_s3_key, content_type="image/jpeg")
            logger.info("[pro-ref %s] Thumbnail uploaded (%.1fs)", reference_id, time.perf_counter() - t0)

        # 8. Save .npz — store joint_angles, velocities, phases, landmarks, metadata
        _PRO_REF_DATA_DIR.mkdir(parents=True, exist_ok=True)
        npz_filename = f"{player_slug}.npz"
        npz_path = str(_PRO_REF_DATA_DIR / npz_filename)

        _save_npz(
            path=npz_path,
            player_name=player_name,
            stroke_type=stroke_type,
            joint_angles=features.joint_angles,
            velocities=features.velocities,
            phases=features.phases,
            landmarks=landmarks_for_features,
            fps=effective_fps,
            frame_count=landmarks_for_features.shape[0],
            racquet_data=racquet_data_serialized,
            original_fps=fps if fps < 50.0 else None,
            original_frame_count=original_frame_count if fps < 50.0 else None,
        )
        logger.info("[pro-ref %s] .npz saved → %s", reference_id, npz_path)

        # 9. Update DB record
        asyncio.run(_write_pro_reference_results(
            reference_id=reference_id,
            npz_path=npz_path,
            thumbnail_s3_key=thumbnail_s3_key,
            frame_count=landmarks_for_features.shape[0],
            fps=effective_fps,
            duration_seconds=duration_seconds,
        ))

        elapsed = time.perf_counter() - t_start
        logger.info("[pro-ref %s] Pipeline complete — total=%.1fs", reference_id, elapsed)

    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        logger.error(
            "[pro-ref %s] Pipeline failed after %.1fs: %s",
            reference_id, elapsed_ms / 1000, exc,
        )
        logger.error(traceback.format_exc())
        asyncio.run(_mark_pro_reference_failed(reference_id, str(exc)))

    finally:
        if work_dir and Path(work_dir).exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("[pro-ref %s] Temp dir cleaned up", reference_id)


# ---------------------------------------------------------------------------
# .npz serialisation
# ---------------------------------------------------------------------------

def _save_npz(
    path: str,
    player_name: str,
    stroke_type: str,
    joint_angles: dict[str, np.ndarray],
    velocities: dict[str, np.ndarray],
    phases: dict[str, tuple[int, int]],
    landmarks: np.ndarray,
    fps: float,
    frame_count: int,
    racquet_data: list | None = None,
    original_fps: float | None = None,
    original_frame_count: int | None = None,
) -> None:
    """
    Write a pro reference .npz archive.

    Extends the format used by save_reference() in loader.py with:
      - velocity_{name}  arrays
      - _landmarks       full (N, 33, 3) array for overlay rendering
    """
    phase_keys = list(phases.keys())
    phase_values = np.array([list(v) for v in phases.values()], dtype=np.int32)

    save_dict: dict[str, object] = {
        "_player": player_name,
        "_stroke_type": stroke_type,
        "_phase_keys": np.array(phase_keys),
        "_phase_values": phase_values,
        "_landmarks": landmarks,
        "_fps": np.float64(fps),
        "_frame_count": np.int64(frame_count),
    }
    if original_fps is not None:
        save_dict["_original_fps"] = np.float64(original_fps)
    if original_frame_count is not None:
        save_dict["_original_frame_count"] = np.int64(original_frame_count)
    for name, arr in joint_angles.items():
        save_dict[f"angle_{name}"] = arr
    for name, arr in velocities.items():
        save_dict[f"velocity_{name}"] = arr

    # Store YOLO racquet detections as a numpy array for .npz compatibility.
    # Each frame is [base_x, base_y, tip_x, tip_y, conf] or all zeros if not detected.
    if racquet_data is not None:
        rq_arr = np.zeros((len(racquet_data), 5), dtype=np.float32)
        for i, item in enumerate(racquet_data):
            if item is not None:
                rq_arr[i] = item
        save_dict["_racquet_data"] = rq_arr

    np.savez(path, **save_dict)
