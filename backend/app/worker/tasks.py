"""
RQ worker task: orchestrates the full SwingCoach analysis pipeline.

Call chain:
  download video → extract frames → pose estimation → feature extraction
  → DTW comparison → Claude feedback → write results to DB → cleanup

This runs in a synchronous RQ worker process. Async operations (DB, Claude API)
are bridged via asyncio.run().
"""
import asyncio
import logging
import shutil
import tempfile
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import uuid as _uuid

import numpy as np
from sqlalchemy import select

from app.config import get_settings
from app.models import Analysis, AnalysisStatus, ProReference
from app.pro_references.loader import ProReferenceDB
from app.services.db import get_session
from app.services.s3 import download_video, upload_file
from app.worker.deviation_annotator import compute_frame_deviations
from app.worker.dtw_comparator import compare_swing, compute_base_score
from app.worker.evals import run_pipeline_evals
from app.worker.feature_engine import extract_features
from app.worker.feedback_generator import generate_coaching_feedback
from app.worker.frame_extractor import extract_frames
from app.worker.phase_aligner import align_phases, resample_landmarks
from app.worker.pose_estimator import extract_poses
from app.worker.racquet_detector import detect_racquets, serialize_detections

logger = logging.getLogger(__name__)

# Singleton reference DB — loaded once when the worker process starts
_pro_db: ProReferenceDB | None = None


def _get_pro_db() -> ProReferenceDB:
    global _pro_db
    if _pro_db is None:
        _pro_db = ProReferenceDB()
        _pro_db.load_all()
    return _pro_db


# ---------------------------------------------------------------------------
# Keyframe extraction helper
# ---------------------------------------------------------------------------

def _save_keyframes(
    frame_paths: list[str],
    phases: dict[str, tuple[int, int]],
    work_dir: str,
) -> dict[str, str]:
    """
    Save the first frame of each phase as a JPEG to work_dir.
    Returns {phase_name: local_jpeg_path}.
    Non-fatal: phases with unreadable frames are skipped.
    """
    import cv2

    keyframes: dict[str, str] = {}
    for phase_name, (start_frame, _end_frame) in phases.items():
        if not frame_paths:
            continue
        idx = min(start_frame, len(frame_paths) - 1)
        frame = cv2.imread(frame_paths[idx])
        if frame is None:
            logger.warning("Could not read frame %s for keyframe '%s'", frame_paths[idx], phase_name)
            continue
        out_path = str(Path(work_dir) / f"keyframe_{phase_name}.jpg")
        cv2.imwrite(out_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        keyframes[phase_name] = out_path
    return keyframes


# ---------------------------------------------------------------------------
# Internal async helpers
# ---------------------------------------------------------------------------

async def _fetch_pro_reference(pro_reference_id: _uuid.UUID) -> ProReference | None:
    async with get_session() as session:
        result = await session.execute(
            select(ProReference).where(ProReference.id == pro_reference_id)
        )
        return result.scalar_one_or_none()


async def _fetch_analysis(analysis_id: str) -> Analysis:
    async with get_session() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == _uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id)
        )
        analysis = result.scalar_one_or_none()
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id} not found in database")
        return analysis


async def _mark_processing(analysis_id: str) -> Analysis:
    async with get_session() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == _uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id)
        )
        analysis = result.scalar_one()
        analysis.status = AnalysisStatus.processing
        return analysis


async def _write_results(
    analysis_id: str,
    pose_data: list,
    phase_scores: dict,
    deviations: list,
    coaching_feedback: dict,
    overall_score: float,
    processing_time_ms: int,
    pro_landmarks: list | None = None,
    aligned_pro_landmarks: list | None = None,
    frame_mapping: list | None = None,
    frame_deviations: list | None = None,
    phase_boundaries: dict | None = None,
    fps: float | None = None,
    keyframe_s3_keys: dict | None = None,
    detection_mask: list | None = None,
    racquet_data: list | None = None,
    pro_racquet_data: list | None = None,
) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == _uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id)
        )
        analysis = result.scalar_one()
        analysis.status = AnalysisStatus.completed
        analysis.pose_data = pose_data
        analysis.phase_scores = phase_scores
        analysis.deviations = deviations
        analysis.coaching_feedback = coaching_feedback
        analysis.overall_score = overall_score
        analysis.pro_landmarks = pro_landmarks
        analysis.aligned_pro_landmarks = aligned_pro_landmarks
        analysis.frame_mapping = frame_mapping
        analysis.frame_deviations = frame_deviations
        analysis.phase_boundaries = phase_boundaries
        analysis.fps = fps
        analysis.keyframe_s3_keys = keyframe_s3_keys
        analysis.detection_mask = detection_mask
        analysis.racquet_data = racquet_data
        analysis.pro_racquet_data = pro_racquet_data
        analysis.completed_at = datetime.now(timezone.utc)
        analysis.processing_time_ms = processing_time_ms


async def _mark_failed(analysis_id: str, error: str) -> None:
    try:
        async with get_session() as session:
            result = await session.execute(
                select(Analysis).where(Analysis.id == _uuid.UUID(analysis_id) if isinstance(analysis_id, str) else analysis_id)
            )
            analysis = result.scalar_one_or_none()
            if analysis is not None:
                analysis.status = AnalysisStatus.failed
                analysis.error_message = error
    except Exception:
        logger.exception("Failed to write error status for analysis %s", analysis_id)


# ---------------------------------------------------------------------------
# Main task
# ---------------------------------------------------------------------------

def process_analysis(analysis_id: str) -> None:
    """
    Main RQ task. Orchestrates the full analysis pipeline for one video.

    Does NOT re-raise exceptions — RQ will see the job as failed via its own
    mechanisms; the Analysis record already carries status='failed'.
    """
    settings = get_settings()
    work_dir: str | None = None
    t_start = time.perf_counter()

    try:
        # 1. Fetch record and verify it exists
        logger.info("[%s] Pipeline start", analysis_id)
        analysis = asyncio.run(_fetch_analysis(analysis_id))
        stroke_type = analysis.stroke_type.value
        pro_reference_name = analysis.pro_reference
        pro_reference_db_id = analysis.pro_reference_id
        s3_key = analysis.video_s3_key

        # 2. Create temp working directory
        work_dir = tempfile.mkdtemp(prefix=f"swingcoach_{analysis_id[:8]}_")
        video_path = str(Path(work_dir) / "video.mp4")

        # 3. Download video
        t0 = time.perf_counter()
        logger.info("[%s] Downloading video (key=%s)", analysis_id, s3_key)
        download_video(s3_key, video_path)
        logger.info("[%s] Download done (%.1fs)", analysis_id, time.perf_counter() - t0)

        # 4. Extract frames
        t0 = time.perf_counter()
        logger.info("[%s] Extracting frames", analysis_id)
        frames_dir = str(Path(work_dir) / "frames")
        frame_result = extract_frames(video_path, output_dir=frames_dir)
        fps = frame_result.fps
        logger.info(
            "[%s] Frames done: %d frames @ %.1f fps (%.1fs)",
            analysis_id, len(frame_result.frame_paths), fps, time.perf_counter() - t0,
        )

        # 5. Pose estimation
        t0 = time.perf_counter()
        logger.info("[%s] Running pose estimation", analysis_id)
        pose_result = extract_poses(frame_result.frame_paths)
        logger.info(
            "[%s] Pose done: detection_rate=%.0f%% (%.1fs)",
            analysis_id, pose_result.detection_rate * 100, time.perf_counter() - t0,
        )

        # 5.5. Racquet detection (YOLO) — non-fatal
        racquet_data_serialized: list | None = None
        try:
            t0 = time.perf_counter()
            logger.info("[%s] Running racquet detection (YOLO)", analysis_id)
            # Pass right wrist (landmark 16) xy for base/tip orientation
            wrist_xy = pose_result.landmarks[:, 16, :2]  # (num_frames, 2)
            racquet_result = detect_racquets(frame_result.frame_paths, wrist_landmarks=wrist_xy)
            # Trim to same window as pose detection
            racquet_data_serialized = serialize_detections(racquet_result.detections)
            logger.info(
                "[%s] Racquet detection done: rate=%.0f%% (%.1fs)",
                analysis_id, racquet_result.detection_rate * 100, time.perf_counter() - t0,
            )
        except Exception as rq_exc:
            logger.warning("[%s] Racquet detection failed (non-fatal): %s", analysis_id, rq_exc)

        # 6. Feature extraction
        t0 = time.perf_counter()
        logger.info("[%s] Extracting features", analysis_id)
        features = extract_features(
            landmarks=pose_result.landmarks,
            fps=fps,
            stroke_type=stroke_type,
            handedness="right",  # TODO: accept from Analysis record in later sprint
        )
        logger.info("[%s] Features done (%.1fs)", analysis_id, time.perf_counter() - t0)

        # 6.5. Extract keyframes at phase boundaries and upload to S3
        keyframe_s3_keys: dict | None = None
        try:
            t0 = time.perf_counter()
            logger.info("[%s] Extracting keyframes", analysis_id)
            keyframe_local = _save_keyframes(frame_result.frame_paths, features.phases, work_dir)
            keyframe_s3_keys = {}
            for phase_name, local_path in keyframe_local.items():
                s3_key = f"analyses/{analysis_id}/keyframes/phase_{phase_name}.jpg"
                upload_file(local_path, s3_key, content_type="image/jpeg")
                keyframe_s3_keys[phase_name] = s3_key
            logger.info(
                "[%s] Keyframes uploaded: %d phases (%.1fs)",
                analysis_id, len(keyframe_s3_keys), time.perf_counter() - t0,
            )
        except Exception as kf_exc:
            logger.warning("[%s] Keyframe extraction failed (non-fatal): %s", analysis_id, kf_exc)
            keyframe_s3_keys = None

        # 7. Load pro reference
        t0 = time.perf_counter()
        pro_landmarks_for_storage: list | None = None
        pro_racquet_raw: list | None = None

        if pro_reference_db_id is not None:
            # Preferred path: load .npz directly using the path stored on the DB record
            db_ref = asyncio.run(_fetch_pro_reference(pro_reference_db_id))
            if db_ref is not None and db_ref.npz_path and Path(db_ref.npz_path).exists():
                data = np.load(db_ref.npz_path, allow_pickle=False)
                # Reconstruct phases dict from stored key/value arrays
                phase_keys = [str(k) for k in data["_phase_keys"]]
                phase_values = data["_phase_values"]
                phases = {k: (int(phase_values[i, 0]), int(phase_values[i, 1]))
                          for i, k in enumerate(phase_keys)}
                joint_angles = {
                    key[len("angle_"):]: data[key]
                    for key in data.files if key.startswith("angle_")
                }
                velocities = {
                    key[len("velocity_"):]: data[key]
                    for key in data.files if key.startswith("velocity_")
                }
                pro_ref = {
                    "player": str(data["_player"]),
                    "stroke_type": str(data["_stroke_type"]),
                    "joint_angles": joint_angles,
                    "velocities": velocities,
                    "phases": phases,
                    "metadata": {},
                }
                # Store the raw landmarks for frontend overlay rendering
                if "_landmarks" in data.files:
                    pro_landmarks_for_storage = data["_landmarks"].tolist()
                # Load pro racquet detections if available
                pro_racquet_raw = None
                if "_racquet_data" in data.files:
                    pro_racquet_raw = data["_racquet_data"].tolist()
                logger.info(
                    "[%s] Pro reference loaded from DB id=%s (%.1fs)",
                    analysis_id, pro_reference_db_id, time.perf_counter() - t0,
                )
            else:
                logger.warning(
                    "[%s] DB pro reference %s has no npz_path or file missing, falling back",
                    analysis_id, pro_reference_db_id,
                )
                pro_ref = None
        else:
            pro_ref = None

        if pro_ref is None:
            # Legacy / fallback path: load from filesystem by string name
            pro_db = _get_pro_db()
            pro_ref = pro_db.get_reference(pro_reference_name, stroke_type)
            if pro_ref is None:
                logger.warning(
                    "[%s] Pro reference '%s_%s' not found, falling back to synthetic_forehand",
                    analysis_id, pro_reference_name, stroke_type,
                )
                pro_ref = pro_db.get_reference("synthetic", "forehand")
            if pro_ref is None:
                raise ValueError(
                    f"No pro reference found for '{pro_reference_name}_{stroke_type}' "
                    "and synthetic fallback is also missing. Run generate_synthetic_reference.py first."
                )
            logger.info("[%s] Pro reference loaded from filesystem (%.1fs)", analysis_id, time.perf_counter() - t0)

        # 8. DTW comparison
        t0 = time.perf_counter()
        logger.info("[%s] Running DTW comparison", analysis_id)
        comparison = compare_swing(features, pro_ref, fps=fps)
        logger.info(
            "[%s] DTW done: overall_score=%.1f, deviations=%d (%.1fs)",
            analysis_id, comparison.overall_score, len(comparison.deviations),
            time.perf_counter() - t0,
        )

        # 8.5. Compute base score (lower body fundamentals)
        try:
            base = compute_base_score(features, pro_ref)
            comparison.phase_scores["base"] = base
            logger.info("[%s] Base score: %.1f", analysis_id, base)
        except Exception as base_exc:
            logger.warning("[%s] Base score computation failed (non-fatal): %s", analysis_id, base_exc)

        # 9. Phase alignment and deviation annotation
        t0 = time.perf_counter()
        logger.info("[%s] Running phase alignment", analysis_id)
        aligned_pro_landmarks_list: list | None = None
        frame_mapping_list: list | None = None
        frame_deviations_list: list | None = None
        phase_boundaries_dict: dict | None = None

        pro_landmarks_np: np.ndarray | None = None
        if pro_landmarks_for_storage is not None:
            pro_landmarks_np = np.array(pro_landmarks_for_storage, dtype=np.float32)

        if pro_landmarks_np is not None and pro_landmarks_np.ndim == 3:
            pro_phases = pro_ref.get("phases", {})
            user_frame_count = pose_result.landmarks.shape[0]
            pro_frame_count  = pro_landmarks_np.shape[0]

            alignment = align_phases(
                user_phases=features.phases,
                pro_phases=pro_phases,
                user_frame_count=user_frame_count,
                pro_frame_count=pro_frame_count,
            )
            frame_mapping_list = alignment.frame_mapping

            # Resample pro landmarks to exactly match user frame count
            aligned_pro_np = resample_landmarks(pro_landmarks_np, user_frame_count)
            aligned_pro_landmarks_list = aligned_pro_np.tolist()

            # Per-frame deviation annotation
            frame_devs = compute_frame_deviations(
                user_landmarks=pose_result.landmarks,
                pro_landmarks_aligned=aligned_pro_np,
                phases=features.phases,
                deviations=comparison.deviations,
            )
            frame_deviations_list = [asdict(fd) for fd in frame_devs]

            # Phase boundaries as plain dicts for JSON storage
            phase_boundaries_dict = {
                name: asdict(pb) for name, pb in alignment.phase_boundaries.items()
            }
            logger.info(
                "[%s] Phase alignment done: %d phases, %d deviation frames (%.1fs)",
                analysis_id, len(alignment.phase_boundaries),
                len(frame_devs), time.perf_counter() - t0,
            )
        else:
            logger.warning("[%s] No pro landmarks available — skipping phase alignment", analysis_id)

        # 9.5. Resample pro racquet data to user frame count
        pro_racquet_data_serialized: list | None = None
        if pro_racquet_raw is not None and pro_landmarks_np is not None:
            try:
                user_frame_count = pose_result.landmarks.shape[0]
                pro_frame_count = len(pro_racquet_raw)
                # Simple nearest-neighbor resampling using frame_mapping
                resampled = []
                for ui in range(user_frame_count):
                    if frame_mapping_list and ui < len(frame_mapping_list):
                        pi = frame_mapping_list[ui]
                    else:
                        pi = int(round(ui * pro_frame_count / user_frame_count))
                    pi = min(pi, pro_frame_count - 1)
                    resampled.append(pro_racquet_raw[pi])
                pro_racquet_data_serialized = resampled
                logger.info("[%s] Pro racquet data resampled to %d frames", analysis_id, user_frame_count)
            except Exception as prq_exc:
                logger.warning("[%s] Pro racquet data resampling failed (non-fatal): %s", analysis_id, prq_exc)

        # 10. Claude coaching feedback
        t0 = time.perf_counter()
        logger.info("[%s] Generating coaching feedback", analysis_id)
        if settings.anthropic_api_key:
            feedback = asyncio.run(
                generate_coaching_feedback(comparison, stroke_type, pro_reference_name)
            )
            coaching_dict = asdict(feedback)
        else:
            logger.warning("[%s] ANTHROPIC_API_KEY not set — skipping feedback generation", analysis_id)
            coaching_dict = {"summary": "API key not configured.", "overall_assessment": "unknown",
                             "priority_fixes": [], "positive_notes": [], "drill_plan": []}
        logger.info("[%s] Feedback done (%.1fs)", analysis_id, time.perf_counter() - t0)

        # 10.5. Run deterministic pipeline evals
        try:
            eval_result = run_pipeline_evals(
                features=features,
                comparison=comparison,
                feedback=coaching_dict,
                frame_deviations=frame_deviations_list,
                frame_mapping=frame_mapping_list,
                num_user_frames=pose_result.landmarks.shape[0],
            )
            coaching_dict["eval_passed"] = eval_result.passed
            coaching_dict["eval_issues"] = eval_result.issues
            logger.info(
                "[%s] Pipeline eval: passed=%s score=%d/%d issues=%d",
                analysis_id, eval_result.passed, eval_result.score, eval_result.total,
                len(eval_result.issues),
            )
        except Exception as eval_exc:
            logger.warning("[%s] Pipeline eval failed (non-fatal): %s", analysis_id, eval_exc)

        # 11. Serialize results for JSON storage
        detection_mask_list = pose_result.detection_mask.tolist()
        pose_data_serializable = pose_result.landmarks.tolist()
        deviations_serializable = [asdict(d) for d in comparison.deviations]

        processing_time_ms = int((time.perf_counter() - t_start) * 1000)

        # 12. Write completed results to DB
        asyncio.run(_write_results(
            analysis_id=analysis_id,
            pose_data=pose_data_serializable,
            phase_scores=comparison.phase_scores,
            deviations=deviations_serializable,
            coaching_feedback=coaching_dict,
            overall_score=comparison.overall_score,
            processing_time_ms=processing_time_ms,
            pro_landmarks=pro_landmarks_for_storage,
            aligned_pro_landmarks=aligned_pro_landmarks_list,
            frame_mapping=frame_mapping_list,
            frame_deviations=frame_deviations_list,
            phase_boundaries=phase_boundaries_dict,
            fps=fps,
            keyframe_s3_keys=keyframe_s3_keys,
            detection_mask=detection_mask_list,
            racquet_data=racquet_data_serialized,
            pro_racquet_data=pro_racquet_data_serialized,
        ))

        logger.info(
            "[%s] Pipeline complete — score=%.1f, total=%.1fs",
            analysis_id, comparison.overall_score, processing_time_ms / 1000,
        )

    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        logger.error(
            "[%s] Pipeline failed after %.1fs: %s",
            analysis_id, elapsed_ms / 1000, exc,
        )
        logger.error(traceback.format_exc())
        asyncio.run(_mark_failed(analysis_id, str(exc)))

    finally:
        if work_dir and Path(work_dir).exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("[%s] Temp dir cleaned up", analysis_id)


# Keep the old name as an alias so existing enqueue calls still work
run_analysis = process_analysis
