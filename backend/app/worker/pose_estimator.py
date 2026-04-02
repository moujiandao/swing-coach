"""
MediaPipe pose landmark extraction for the SwingCoach pipeline.

Stage 2 of the worker pipeline: PNG frames → landmark numpy arrays.

Uses the MediaPipe Tasks API (0.10+). The legacy mp.solutions.pose API was
removed in 0.10; models are no longer bundled and must be downloaded once.
"""
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------

# pose_landmarker_heavy is the highest-accuracy model (~29 MB).
# Equivalent to the old model_complexity=2.
_MODEL_FILENAME = "pose_landmarker_heavy.task"
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_heavy/float16/latest/"
    "pose_landmarker_heavy.task"
)
_MODEL_CACHE_DIR = Path.home() / ".cache" / "mediapipe"

# MediaPipe references — resolved once at module level for clarity
_BaseOptions = mp.tasks.BaseOptions
_PoseLandmarker = mp.tasks.vision.PoseLandmarker
_PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
_RunningMode = mp.tasks.vision.RunningMode

# ---------------------------------------------------------------------------
# Landmark index map
# All 33 BlazePose landmarks; the subset used by the feature engine is noted.
# ---------------------------------------------------------------------------
LANDMARK_NAMES: dict[int, str] = {
    0: "nose",
    1: "left_eye_inner",
    2: "left_eye",
    3: "left_eye_outer",
    4: "right_eye_inner",
    5: "right_eye",
    6: "right_eye_outer",
    7: "left_ear",
    8: "right_ear",
    9: "mouth_left",
    10: "mouth_right",
    11: "left_shoulder",   # used
    12: "right_shoulder",  # used
    13: "left_elbow",      # used
    14: "right_elbow",     # used
    15: "left_wrist",      # used
    16: "right_wrist",     # used
    17: "left_pinky",
    18: "right_pinky",
    19: "left_index",
    20: "right_index",
    21: "left_thumb",
    22: "right_thumb",
    23: "left_hip",        # used
    24: "right_hip",       # used
    25: "left_knee",       # used
    26: "right_knee",      # used
    27: "left_ankle",      # used
    28: "right_ankle",     # used
    29: "left_heel",
    30: "right_heel",
    31: "left_foot_index",
    32: "right_foot_index",
}

N_LANDMARKS = 33

# Max dimension (width or height) for frames fed to MediaPipe. Larger frames
# are downscaled proportionally before detection. MediaPipe's person detector
# is optimized for ~640-1080px images; 4K frames often cause detection failure.
_MAX_FRAME_DIMENSION = 1080


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PoseEstimationResult:
    landmarks: np.ndarray    # (num_frames, 33, 3)  — normalized x, y, z
    visibility: np.ndarray   # (num_frames, 33)     — per-landmark confidence
    frames_processed: int
    frames_with_pose: int    # frames where a person was detected
    detection_rate: float    # frames_with_pose / frames_processed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_model() -> str:
    """
    Return the path to the pose landmarker model file, downloading it once if
    not already cached.
    """
    model_path = _MODEL_CACHE_DIR / _MODEL_FILENAME
    if not model_path.exists():
        _MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Downloading MediaPipe pose landmarker model (~29 MB) to %s …",
            model_path,
        )
        urllib.request.urlretrieve(_MODEL_URL, model_path)
        logger.info("Model download complete.")
    return str(model_path)


def _interpolate_missing(
    raw_landmarks: list[np.ndarray | None],
    raw_visibility: list[np.ndarray | None],
    detected: set[int],
    n_frames: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Fill frames where pose was not detected via linear interpolation between
    neighboring detected frames. Edge frames copy the nearest detection.
    """
    out_lm = np.zeros((n_frames, N_LANDMARKS, 3), dtype=np.float32)
    out_vis = np.zeros((n_frames, N_LANDMARKS), dtype=np.float32)

    # Place known frames.
    for i in detected:
        out_lm[i] = raw_landmarks[i]
        out_vis[i] = raw_visibility[i]

    if not detected:
        return out_lm, out_vis

    sorted_detected = sorted(detected)

    for i in range(n_frames):
        if i in detected:
            continue

        prev_idx = next((f for f in reversed(sorted_detected) if f < i), None)
        next_idx = next((f for f in sorted_detected if f > i), None)

        if prev_idx is not None and next_idx is not None:
            t = (i - prev_idx) / (next_idx - prev_idx)
            out_lm[i] = (1.0 - t) * out_lm[prev_idx] + t * out_lm[next_idx]
            out_vis[i] = (1.0 - t) * out_vis[prev_idx] + t * out_vis[next_idx]
        elif prev_idx is not None:
            out_lm[i] = out_lm[prev_idx]
            out_vis[i] = out_vis[prev_idx]
        else:
            out_lm[i] = out_lm[next_idx]
            out_vis[i] = out_vis[next_idx]

    return out_lm, out_vis


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_poses(frame_paths: list[str]) -> PoseEstimationResult:
    """
    Run MediaPipe BlazePose on each frame to extract body landmarks.

    Args:
        frame_paths: Sorted list of paths to frame PNG files.

    Returns:
        PoseEstimationResult:
            landmarks  — (num_frames, 33, 3): normalized x, y (image-relative),
                         z (depth relative to hip midpoint)
            visibility — (num_frames, 33): per-landmark confidence scores
            frames_processed, frames_with_pose, detection_rate

    Raises:
        ValueError: if detection_rate < 0.5 (too few frames with a visible person).
        RuntimeError: if an image file cannot be read.
    """
    if not frame_paths:
        raise ValueError("frame_paths is empty — no frames to process")

    from app.config import get_settings
    settings = get_settings()

    model_path = _ensure_model()
    options = _PoseLandmarkerOptions(
        base_options=_BaseOptions(model_asset_path=model_path),
        running_mode=_RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=settings.pose_detection_confidence,
        min_pose_presence_confidence=settings.pose_presence_confidence,
    )

    raw_landmarks: list[np.ndarray | None] = []
    raw_visibility: list[np.ndarray | None] = []
    detected: set[int] = set()

    with _PoseLandmarker.create_from_options(options) as landmarker:
        for i, frame_path in enumerate(frame_paths):
            bgr = cv2.imread(frame_path)
            if bgr is None:
                raise RuntimeError(f"Could not read image: {frame_path}")

            # Downscale large frames - MediaPipe's person detector is optimized
            # for ~640-1080px images and often fails on 4K/high-res input.
            h, w = bgr.shape[:2]
            if max(h, w) > _MAX_FRAME_DIMENSION:
                scale = _MAX_FRAME_DIMENSION / max(h, w)
                new_w, new_h = int(w * scale), int(h * scale)
                bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
                if i == 0:
                    logger.info(
                        "Resizing frames from %dx%d to %dx%d for pose detection",
                        w, h, new_w, new_h,
                    )
            elif i == 0:
                logger.info("Frame resolution: %dx%d (no resize needed)", w, h)

            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            result = landmarker.detect(mp_image)

            if result.pose_landmarks:
                lms = result.pose_landmarks[0]  # first (only) person
                frame_lm = np.array(
                    [[lm.x, lm.y, lm.z] for lm in lms], dtype=np.float32
                )
                frame_vis = np.array(
                    [lm.visibility if lm.visibility is not None else 0.0 for lm in lms],
                    dtype=np.float32,
                )
                raw_landmarks.append(frame_lm)
                raw_visibility.append(frame_vis)
                detected.add(i)
            else:
                raw_landmarks.append(None)
                raw_visibility.append(None)

    frames_processed = len(frame_paths)
    frames_with_pose = len(detected)
    detection_rate = frames_with_pose / frames_processed

    logger.info(
        "Pose detection: %d/%d frames (%.0f%%)",
        frames_with_pose, frames_processed, detection_rate * 100,
    )

    min_rate = settings.pose_min_detection_rate
    if detection_rate < min_rate:
        failed_indices = sorted(set(range(frames_processed)) - detected)
        logger.debug(
            "Failed frame indices (first 20): %s", failed_indices[:20],
        )
        raise ValueError(
            f"Pose detection rate {detection_rate:.1%} is below the "
            f"{min_rate:.0%} threshold "
            f"({frames_with_pose}/{frames_processed} frames detected). "
            "Ensure the person is clearly visible throughout the video."
        )

    landmarks_arr, visibility_arr = _interpolate_missing(
        raw_landmarks, raw_visibility, detected, frames_processed
    )

    return PoseEstimationResult(
        landmarks=landmarks_arr,
        visibility=visibility_arr,
        frames_processed=frames_processed,
        frames_with_pose=frames_with_pose,
        detection_rate=detection_rate,
    )
