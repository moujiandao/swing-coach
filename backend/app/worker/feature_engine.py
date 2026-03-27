"""
Feature extraction and phase segmentation for the SwingCoach pipeline.

Stage 3 of the worker pipeline: landmark numpy arrays → joint angles, velocities,
and phase boundaries that drive DTW comparison and coaching feedback.
"""
import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

from app.models import StrokeType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Landmark indices (BlazePose 33-point model)
# ---------------------------------------------------------------------------

# Hitting-arm indices for a right-handed player.
# For left-handed, these are swapped at call time.
_R = {
    "shoulder": 12,
    "elbow":    14,
    "wrist":    16,
    "hip":      24,
    "knee":     26,
    "ankle":    28,
}
_L = {
    "shoulder": 11,
    "elbow":    13,
    "wrist":    15,
    "hip":      23,
    "knee":     25,
    "ankle":    27,
}

# Named constants for clarity elsewhere
_LEFT_SHOULDER  = 11
_RIGHT_SHOULDER = 12
_LEFT_HIP       = 23
_RIGHT_HIP      = 24


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class FeatureExtractionResult:
    joint_angles: dict[str, np.ndarray]       # degrees, one value per frame
    velocities: dict[str, np.ndarray]         # smoothed speed per frame
    phases: dict[str, tuple[int, int]]        # (start_frame, end_frame) inclusive
    contact_frame: int                        # frame index of peak wrist speed


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def compute_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """
    Angle (degrees) at point *b* formed by vectors b→a and b→c.

    All inputs are 1-D arrays of length 2 or 3 (only x,y used for stability).
    Returns a value in [0, 360).
    """
    ba = a[:2] - b[:2]
    bc = c[:2] - b[:2]
    # atan2 gives signed angle; we want unsigned angle at vertex b
    cos_val = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-9)
    cos_val = np.clip(cos_val, -1.0, 1.0)
    angle_rad = np.arccos(cos_val)
    return float(np.degrees(angle_rad))


def _line_angle_deg(p1: np.ndarray, p2: np.ndarray) -> float:
    """
    Angle of the line from p1 to p2 relative to the positive x-axis, [0, 360).
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    angle = float(np.degrees(np.arctan2(dy, dx)))
    return angle % 360.0


# ---------------------------------------------------------------------------
# Velocity helper
# ---------------------------------------------------------------------------

def compute_velocity(positions: np.ndarray, fps: float) -> np.ndarray:
    """
    First derivative of a position timeseries (N, 2) or (N, 3), smoothed with
    a Savitzky-Golay filter.  Returns speed (scalar) per frame as (N,) array.

    Edge frames use finite-difference approximations compatible with savgol.
    The filter window is capped to the series length (minimum 3 frames, odd).
    """
    n = positions.shape[0]
    # Build window: at most n frames, at least 3, always odd
    window = min(7, n if n % 2 == 1 else n - 1)
    window = max(window, 3)
    polyorder = min(2, window - 1)

    smoothed = savgol_filter(positions, window_length=window, polyorder=polyorder, axis=0)
    # Gradient along time axis → velocity in normalized coords / second
    velocity_vec = np.gradient(smoothed, 1.0 / fps, axis=0)
    speed = np.linalg.norm(velocity_vec[:, :2], axis=1)  # use x,y only
    return speed.astype(np.float32)


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------

def detect_phases(
    wrist_positions: np.ndarray,   # (N, 3)
    wrist_speed: np.ndarray,       # (N,) smoothed scalar speed
) -> tuple[dict[str, tuple[int, int]], int]:
    """
    Segment the swing into 5 phases and identify the contact frame.

    Returns:
        phases: dict mapping phase name → (start, end) frame indices (inclusive)
        contact_frame: index of peak wrist speed
    """
    n = len(wrist_speed)
    contact_frame = int(np.argmax(wrist_speed))

    # --- backswing_start: last sign-change of wrist x-velocity before contact ---
    # A positive x-velocity means wrist moving right (forward for right-hander);
    # we look for the transition from positive→negative (wrist starts moving away).
    wrist_x = wrist_positions[:, 0]
    dx = np.diff(wrist_x, prepend=wrist_x[0])  # length N

    backswing_start = 0
    for i in range(contact_frame - 1, 0, -1):
        # sign flip: was moving one direction, then the other
        if dx[i] * dx[i - 1] < 0:
            backswing_start = i
            break

    # --- forward_swing_start: sign-change after backswing_start ---
    forward_swing_start = backswing_start + 1
    for i in range(backswing_start + 1, contact_frame):
        if dx[i] * dx[i - 1] < 0:
            forward_swing_start = i
            break

    # Guard: ensure monotone ordering
    forward_swing_start = max(forward_swing_start, backswing_start + 1)
    contact_frame_clamped = max(contact_frame, forward_swing_start + 1)

    follow_through_start = contact_frame_clamped + 1

    phases: dict[str, tuple[int, int]] = {
        "preparation":   (0,                       max(0, backswing_start - 1)),
        "backswing":     (backswing_start,          forward_swing_start - 1),
        "forward_swing": (forward_swing_start,      contact_frame_clamped),
        "contact":       (max(0, contact_frame_clamped - 1), min(n - 1, contact_frame_clamped + 1)),
        "follow_through":(follow_through_start,    n - 1),
    }

    # Clamp every phase so start ≤ end, both within [0, n-1]
    phases = {
        k: (max(0, min(s, e, n - 1)), min(n - 1, max(s, e)))
        for k, (s, e) in phases.items()
    }

    return phases, contact_frame_clamped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_features(
    landmarks: np.ndarray,   # (num_frames, 33, 3)
    fps: float,
    stroke_type: str,        # StrokeType enum value or string
    handedness: str = "right",
) -> FeatureExtractionResult:
    """
    Turn raw pose landmarks into coaching-relevant features.

    Args:
        landmarks: (N, 33, 3) float array of normalized x,y,z coords.
        fps: Frames per second of the source video.
        stroke_type: StrokeType value (string or enum); used for future
                     stroke-specific phase logic.
        handedness: "right" or "left" — determines which arm is the hitting arm.

    Returns:
        FeatureExtractionResult with joint_angles, velocities, phases,
        and contact_frame.
    """
    if landmarks.ndim != 3 or landmarks.shape[1] != 33 or landmarks.shape[2] != 3:
        raise ValueError(
            f"Expected landmarks shape (N, 33, 3), got {landmarks.shape}"
        )

    n = landmarks.shape[0]

    # Select hitting-arm and front-leg indices based on handedness
    if handedness == "left":
        hit = _L   # left-arm is hitting arm
        front = _R  # right side is front for left-handers
    else:
        hit = _R
        front = _L

    # Convenience: extract per-frame arrays for key joints
    def lm(idx: int) -> np.ndarray:
        """Return (N, 3) array for landmark index."""
        return landmarks[:, idx, :]

    hit_shoulder = lm(hit["shoulder"])
    hit_elbow    = lm(hit["elbow"])
    hit_wrist    = lm(hit["wrist"])
    hit_hip      = lm(hit["hip"])
    hit_knee     = lm(hit["knee"])
    hit_ankle    = lm(hit["ankle"])

    l_shoulder = lm(_LEFT_SHOULDER)
    r_shoulder = lm(_RIGHT_SHOULDER)
    l_hip      = lm(_LEFT_HIP)
    r_hip      = lm(_RIGHT_HIP)

    # --- Joint angles (degrees, per frame) ---
    elbow_angle         = np.array([compute_angle(hit_shoulder[i], hit_elbow[i], hit_wrist[i])   for i in range(n)], dtype=np.float32)
    knee_bend           = np.array([compute_angle(hit_hip[i],      hit_knee[i],  hit_ankle[i])   for i in range(n)], dtype=np.float32)
    racket_arm_elevation= np.array([compute_angle(hit_elbow[i],    hit_shoulder[i], hit_hip[i])  for i in range(n)], dtype=np.float32)
    shoulder_rotation   = np.array([_line_angle_deg(l_shoulder[i], r_shoulder[i])                for i in range(n)], dtype=np.float32)
    hip_rotation        = np.array([_line_angle_deg(l_hip[i],      r_hip[i])                     for i in range(n)], dtype=np.float32)
    trunk_rotation      = (shoulder_rotation - hip_rotation) % 360.0

    joint_angles = {
        "elbow_angle":          elbow_angle,
        "shoulder_rotation":    shoulder_rotation,
        "hip_rotation":         hip_rotation,
        "trunk_rotation":       trunk_rotation,
        "knee_bend":            knee_bend,
        "racket_arm_elevation": racket_arm_elevation,
    }

    # --- Velocities (smoothed speed per frame) ---
    wrist_speed  = compute_velocity(hit_wrist, fps)
    elbow_speed  = compute_velocity(hit_elbow, fps)
    hip_mid      = (l_hip + r_hip) / 2.0
    hip_speed    = compute_velocity(hip_mid, fps)

    velocities = {
        "wrist_speed": wrist_speed,
        "elbow_speed": elbow_speed,
        "hip_speed":   hip_speed,
    }

    # --- Phase detection ---
    phases, contact_frame = detect_phases(hit_wrist, wrist_speed)

    logger.info(
        "Features extracted: %d frames, contact at frame %d, phases=%s",
        n, contact_frame, {k: v for k, v in phases.items()},
    )

    return FeatureExtractionResult(
        joint_angles=joint_angles,
        velocities=velocities,
        phases=phases,
        contact_frame=contact_frame,
    )
