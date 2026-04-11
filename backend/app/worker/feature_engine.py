"""
Feature extraction and phase segmentation for the SwingCoach pipeline.

Stage 3 of the worker pipeline: landmark numpy arrays → joint angles, velocities,
and phase boundaries that drive DTW comparison and coaching feedback.
"""
import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import interp1d
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
# Landmark temporal upsampling
# ---------------------------------------------------------------------------

_UPSAMPLE_FPS_THRESHOLD = 50.0
_UPSAMPLE_TARGET_FPS = 120.0


def upsample_landmarks(
    landmarks: np.ndarray,
    source_fps: float,
    target_fps: float = _UPSAMPLE_TARGET_FPS,
) -> tuple[np.ndarray, float]:
    """
    Upsample a (N, 33, 3) landmark array from source_fps to target_fps
    using cubic spline interpolation along the time axis.

    Returns (upsampled_landmarks, effective_fps). If source_fps >= target_fps
    or N < 2, returns the input unchanged.
    """
    n = landmarks.shape[0]
    if source_fps >= target_fps or n < 2:
        return landmarks, source_fps

    scale = target_fps / source_fps
    new_n = int(round(n * scale))
    if new_n <= n:
        return landmarks, source_fps

    t_old = np.linspace(0.0, 1.0, n)
    t_new = np.linspace(0.0, 1.0, new_n)

    # Reshape to (N, 99) for vectorized interpolation
    flat = landmarks.reshape(n, -1)

    # Cubic spline requires >= 4 points; fall back to linear for very short sequences
    kind = "cubic" if n >= 4 else "linear"
    interpolator = interp1d(t_old, flat, axis=0, kind=kind, fill_value="extrapolate")
    upsampled_flat = interpolator(t_new)

    # Clamp to [0, 1] - cubic spline can overshoot normalized coordinates
    upsampled_flat = np.clip(upsampled_flat, 0.0, 1.0)

    upsampled = upsampled_flat.reshape(new_n, landmarks.shape[1], landmarks.shape[2])
    logger.info(
        "Upsampled landmarks: %d → %d frames (%.1f → %.1f fps, method=%s)",
        n, new_n, source_fps, target_fps, kind,
    )
    return upsampled.astype(np.float32), target_fps


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------

# Evaluation window thresholds (tune with real swing data)
_SHOULDER_TURN_THRESHOLD = 0.3   # deg/frame: minimum angular velocity to count as active rotation
_DECEL_FRACTION = 0.15           # fraction of peak wrist speed below which follow-through ends


def detect_phases(
    wrist_positions: np.ndarray,   # (N, 3)
    wrist_speed: np.ndarray,       # (N,) smoothed scalar speed
    shoulder_rotation: np.ndarray, # (N,) degrees, shoulder line angle per frame
) -> tuple[dict[str, tuple[int, int]], int]:
    """
    Segment the swing into 5 phases and identify the contact frame.

    The evaluation window is trimmed to the active swing:
    - Starts at shoulder turn initiation (first significant shoulder rotation
      before the backswing), excluding idle frames at the beginning.
    - Ends when wrist speed drops below 15% of peak after contact, excluding
      recovery/idle frames at the end.

    Returns:
        phases: dict mapping phase name → (start, end) frame indices (inclusive)
        contact_frame: index of peak wrist speed
    """
    n = len(wrist_speed)
    contact_frame = int(np.argmax(wrist_speed))

    # --- backswing_start: last sign-change of wrist x-velocity before contact ---
    wrist_x = wrist_positions[:, 0]
    dx = np.diff(wrist_x, prepend=wrist_x[0])  # length N

    backswing_start = 0
    for i in range(contact_frame - 1, 0, -1):
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

    # --- eval_start: shoulder turn initiation ---
    # Smoothed derivative of shoulder rotation to find first significant movement.
    d_shoulder = np.gradient(shoulder_rotation)
    sw = min(7, n if n % 2 == 1 else n - 1)
    sw = max(sw, 3)
    d_shoulder_smooth = savgol_filter(
        d_shoulder, window_length=sw, polyorder=min(2, sw - 1),
    )

    eval_start = 0  # fallback: shoulder was turning from the very start
    for i in range(backswing_start - 1, -1, -1):
        if abs(d_shoulder_smooth[i]) < _SHOULDER_TURN_THRESHOLD:
            eval_start = i + 1
            break

    # --- eval_end: wrist deceleration after contact ---
    peak_speed = wrist_speed[contact_frame]
    speed_threshold = peak_speed * _DECEL_FRACTION
    eval_end = n - 1  # fallback
    for i in range(follow_through_start, n):
        if wrist_speed[i] < speed_threshold:
            eval_end = i
            break

    phases: dict[str, tuple[int, int]] = {
        "preparation":   (eval_start,              max(eval_start, backswing_start - 1)),
        "backswing":     (backswing_start,          forward_swing_start - 1),
        "forward_swing": (forward_swing_start,      contact_frame_clamped),
        "contact":       (max(0, contact_frame_clamped - 1), min(n - 1, contact_frame_clamped + 1)),
        "follow_through":(follow_through_start,    eval_end),
    }

    # Clamp every phase so start <= end, both within [0, n-1]
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
        non_hit = _R
    else:
        hit = _R
        front = _L
        non_hit = _L

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

    # Non-hitting arm joints
    non_hit_shoulder = lm(non_hit["shoulder"])
    non_hit_elbow    = lm(non_hit["elbow"])
    non_hit_wrist    = lm(non_hit["wrist"])
    non_hit_hip      = lm(non_hit["hip"])

    # --- Joint angles (degrees, per frame) ---
    elbow_angle         = np.array([compute_angle(hit_shoulder[i], hit_elbow[i], hit_wrist[i])          for i in range(n)], dtype=np.float32)
    knee_bend           = np.array([compute_angle(hit_hip[i],      hit_knee[i],  hit_ankle[i])          for i in range(n)], dtype=np.float32)
    racket_arm_elevation= np.array([compute_angle(hit_elbow[i],    hit_shoulder[i], hit_hip[i])         for i in range(n)], dtype=np.float32)
    shoulder_rotation   = np.array([_line_angle_deg(l_shoulder[i], r_shoulder[i])                       for i in range(n)], dtype=np.float32)
    hip_rotation        = np.array([_line_angle_deg(l_hip[i],      r_hip[i])                            for i in range(n)], dtype=np.float32)
    trunk_rotation      = (shoulder_rotation - hip_rotation) % 360.0
    left_elbow_angle    = np.array([compute_angle(non_hit_shoulder[i], non_hit_elbow[i], non_hit_wrist[i]) for i in range(n)], dtype=np.float32)
    left_arm_elevation  = np.array([compute_angle(non_hit_elbow[i], non_hit_shoulder[i], non_hit_hip[i])   for i in range(n)], dtype=np.float32)
    stance_width        = np.sqrt((landmarks[:,27,0]-landmarks[:,28,0])**2 + (landmarks[:,27,1]-landmarks[:,28,1])**2).astype(np.float32)
    head_movement       = (landmarks[:,0,1] - (landmarks[:,11,1]+landmarks[:,12,1])/2).astype(np.float32)

    joint_angles = {
        "elbow_angle":          elbow_angle,
        "shoulder_rotation":    shoulder_rotation,
        "hip_rotation":         hip_rotation,
        "trunk_rotation":       trunk_rotation,
        "knee_bend":            knee_bend,
        "racket_arm_elevation": racket_arm_elevation,
        "left_elbow_angle":     left_elbow_angle,
        "left_arm_elevation":   left_arm_elevation,
        "stance_width":         stance_width,
        "head_movement":        head_movement,
    }

    # --- Velocities (smoothed speed per frame) ---
    wrist_speed  = compute_velocity(hit_wrist, fps)
    elbow_speed  = compute_velocity(hit_elbow, fps)
    hip_mid      = (l_hip + r_hip) / 2.0
    hip_speed    = compute_velocity(hip_mid, fps)

    # Wrist acceleration: first derivative of wrist_speed using same window as compute_velocity
    _accel_window = min(7, n if n % 2 == 1 else n - 1)
    _accel_window = max(_accel_window, 3)
    _accel_polyorder = min(2, _accel_window - 1)
    wrist_acceleration = savgol_filter(
        wrist_speed, window_length=_accel_window, polyorder=_accel_polyorder,
        deriv=1, delta=1.0 / fps,
    ).astype(np.float32)

    velocities = {
        "wrist_speed":        wrist_speed,
        "elbow_speed":        elbow_speed,
        "hip_speed":          hip_speed,
        "wrist_acceleration": wrist_acceleration,
    }

    # --- Phase detection ---
    phases, contact_frame = detect_phases(hit_wrist, wrist_speed, shoulder_rotation)

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
