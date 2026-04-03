"""
YOLOv8 tennis racquet detection for the SwingCoach pipeline.

Runs object detection on each frame to locate the tennis racquet's position
and orientation, producing a center-line (base + tip) that the frontend can
draw directly instead of the wrist-projection heuristic.

Uses the YOLOv8n (nano) model with COCO class 38 = "tennis racket".
"""
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# COCO class index for "tennis racket"
_TENNIS_RACKET_CLASS = 38

# Minimum confidence to accept a detection
_MIN_CONFIDENCE = 0.25

# Maximum gap (in frames) to interpolate across when racquet is not detected
_MAX_INTERPOLATION_GAP = 5


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RacquetDetection:
    """A single frame's racquet position as a drawable line."""
    base_x: float       # normalized [0,1] - near the hand/grip end
    base_y: float
    tip_x: float        # normalized [0,1] - head end of racquet
    tip_y: float
    confidence: float


@dataclass
class RacquetDetectionResult:
    """Per-frame racquet detections across all frames."""
    detections: list[RacquetDetection | None]   # one per frame, None if not detected
    detection_rate: float                        # frames_with_racquet / total_frames


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_model():
    """Load YOLOv8n model, downloading on first use (~6MB)."""
    from ultralytics import YOLO
    model = YOLO("yolov8n.pt")
    return model


def _bbox_to_centerline(
    x1: float, y1: float, x2: float, y2: float,
    img_w: int, img_h: int,
    wrist_xy: tuple[float, float] | None = None,
) -> tuple[float, float, float, float]:
    """
    Convert a bounding box to a center-line along the racquet's long axis.

    Returns (base_x, base_y, tip_x, tip_y) in normalized [0,1] coordinates.
    The "base" is the end closer to the wrist (if provided), otherwise the
    bottom of the bbox (closer to the player's body in typical camera angles).
    """
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    w = x2 - x1
    h = y2 - y1

    # The racquet's long axis runs along the bbox's longer dimension.
    # We extend from center along that axis by half the length.
    if h >= w:
        # Vertical-ish racquet
        half_len = h / 2.0
        end_a = (cx, cy - half_len)  # top
        end_b = (cx, cy + half_len)  # bottom
    else:
        # Horizontal-ish racquet
        half_len = w / 2.0
        end_a = (cx - half_len, cy)  # left
        end_b = (cx + half_len, cy)  # right

    # Determine which end is the base (grip) vs tip (head).
    # If we have a wrist position, base = end closer to wrist.
    if wrist_xy is not None:
        wx, wy = wrist_xy
        dist_a = (end_a[0] / img_w - wx) ** 2 + (end_a[1] / img_h - wy) ** 2
        dist_b = (end_b[0] / img_w - wx) ** 2 + (end_b[1] / img_h - wy) ** 2
        if dist_a <= dist_b:
            base, tip = end_a, end_b
        else:
            base, tip = end_b, end_a
    else:
        # Default: lower point is base (player is usually below racquet head)
        if end_a[1] >= end_b[1]:
            base, tip = end_a, end_b
        else:
            base, tip = end_b, end_a

    # Normalize to [0,1]
    return (
        base[0] / img_w, base[1] / img_h,
        tip[0] / img_w, tip[1] / img_h,
    )


def _interpolate_detections(
    detections: list[RacquetDetection | None],
    max_gap: int = _MAX_INTERPOLATION_GAP,
) -> list[RacquetDetection | None]:
    """
    Fill short gaps in racquet detections via linear interpolation.
    Same logic as pose_estimator's gap filling.
    """
    n = len(detections)
    if n == 0:
        return detections

    result = list(detections)
    detected_indices = [i for i, d in enumerate(detections) if d is not None]

    if not detected_indices:
        return result

    for i in range(n):
        if result[i] is not None:
            continue

        # Find nearest detected frames before and after
        prev_idx = None
        next_idx = None
        for di in reversed(detected_indices):
            if di < i:
                prev_idx = di
                break
        for di in detected_indices:
            if di > i:
                next_idx = di
                break

        if prev_idx is not None and next_idx is not None:
            gap = next_idx - prev_idx - 1
            if gap > max_gap:
                continue
            t = (i - prev_idx) / (next_idx - prev_idx)
            prev_d = result[prev_idx]
            next_d = result[next_idx]
            result[i] = RacquetDetection(
                base_x=prev_d.base_x + t * (next_d.base_x - prev_d.base_x),
                base_y=prev_d.base_y + t * (next_d.base_y - prev_d.base_y),
                tip_x=prev_d.tip_x + t * (next_d.tip_x - prev_d.tip_x),
                tip_y=prev_d.tip_y + t * (next_d.tip_y - prev_d.tip_y),
                confidence=0.0,  # interpolated, not a real detection
            )
        elif prev_idx is not None:
            # Edge copy
            result[i] = RacquetDetection(
                base_x=result[prev_idx].base_x,
                base_y=result[prev_idx].base_y,
                tip_x=result[prev_idx].tip_x,
                tip_y=result[prev_idx].tip_y,
                confidence=0.0,
            )
        elif next_idx is not None:
            result[i] = RacquetDetection(
                base_x=result[next_idx].base_x,
                base_y=result[next_idx].base_y,
                tip_x=result[next_idx].tip_x,
                tip_y=result[next_idx].tip_y,
                confidence=0.0,
            )

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_racquets(
    frame_paths: list[str],
    wrist_landmarks: np.ndarray | None = None,
) -> RacquetDetectionResult:
    """
    Run YOLOv8 racquet detection on each frame.

    Args:
        frame_paths: Sorted list of paths to frame PNG files.
        wrist_landmarks: Optional (num_frames, 2) array of normalized wrist
            (x, y) positions from MediaPipe, used to orient the racquet
            line (base near wrist, tip away). If None, uses heuristic.

    Returns:
        RacquetDetectionResult with per-frame detections and detection rate.
    """
    if not frame_paths:
        return RacquetDetectionResult(detections=[], detection_rate=0.0)

    model = _load_model()
    raw_detections: list[RacquetDetection | None] = []

    for i, frame_path in enumerate(frame_paths):
        bgr = cv2.imread(frame_path)
        if bgr is None:
            logger.warning("Could not read frame: %s", frame_path)
            raw_detections.append(None)
            continue

        img_h, img_w = bgr.shape[:2]

        # Run YOLO inference (verbose=False suppresses per-frame logging)
        results = model.predict(bgr, verbose=False, conf=_MIN_CONFIDENCE)

        best_detection = None
        best_conf = 0.0

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if cls_id == _TENNIS_RACKET_CLASS and conf > best_conf:
                    best_conf = conf
                    x1, y1, x2, y2 = box.xyxy[0].tolist()

                    # Get wrist position for this frame if available
                    wrist_xy = None
                    if wrist_landmarks is not None and i < len(wrist_landmarks):
                        wrist_xy = (float(wrist_landmarks[i, 0]),
                                    float(wrist_landmarks[i, 1]))

                    bx, by, tx, ty = _bbox_to_centerline(
                        x1, y1, x2, y2, img_w, img_h, wrist_xy
                    )
                    best_detection = RacquetDetection(
                        base_x=bx, base_y=by,
                        tip_x=tx, tip_y=ty,
                        confidence=conf,
                    )

        raw_detections.append(best_detection)

        if i == 0 or (i + 1) % 50 == 0:
            logger.debug(
                "Racquet detection frame %d/%d: %s",
                i + 1, len(frame_paths),
                f"conf={best_conf:.2f}" if best_detection else "not detected",
            )

    # Interpolate gaps
    detections = _interpolate_detections(raw_detections)

    frames_detected = sum(1 for d in raw_detections if d is not None)
    detection_rate = frames_detected / len(frame_paths) if frame_paths else 0.0

    logger.info(
        "Racquet detection: %d/%d frames (%.0f%%)",
        frames_detected, len(frame_paths), detection_rate * 100,
    )

    return RacquetDetectionResult(
        detections=detections,
        detection_rate=detection_rate,
    )


def serialize_detections(detections: list[RacquetDetection | None]) -> list[list[float] | None]:
    """
    Convert detections to compact JSON-serializable format.
    Each detection becomes [base_x, base_y, tip_x, tip_y, confidence] or null.
    """
    result = []
    for d in detections:
        if d is None:
            result.append(None)
        else:
            result.append([
                round(d.base_x, 4),
                round(d.base_y, 4),
                round(d.tip_x, 4),
                round(d.tip_y, 4),
                round(d.confidence, 3),
            ])
    return result


def deserialize_detections(data: list[list[float] | None]) -> list[RacquetDetection | None]:
    """Reconstruct RacquetDetection objects from serialized JSON format."""
    result = []
    for item in data:
        if item is None:
            result.append(None)
        else:
            result.append(RacquetDetection(
                base_x=item[0], base_y=item[1],
                tip_x=item[2], tip_y=item[3],
                confidence=item[4],
            ))
    return result
