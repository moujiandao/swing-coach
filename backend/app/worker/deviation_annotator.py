"""
Per-frame deviation annotation.

Takes user landmarks, aligned pro landmarks, and the DTW deviation list from
compare_swing(), then produces a per-frame list of which joints are actively
deviating and by how much — used by the frontend to highlight skeleton joints.
"""
import logging
from dataclasses import dataclass, field

import numpy as np

from app.worker.dtw_comparator import Deviation
from app.worker.feature_engine import compute_angle, _line_angle_deg

logger = logging.getLogger(__name__)

# Degrees below which a per-frame angle difference is not flagged
_DEFAULT_THRESHOLD_DEGREES = 10.0

# Severity tiers for per-frame deviations
_SEVERITY_ORDER = ["critical", "moderate", "minor"]

# Mapping: joint name → MediaPipe landmark indices to highlight on the skeleton
JOINT_LANDMARK_MAP: dict[str, list[int]] = {
    "elbow_angle":          [13, 14],           # left / right elbow
    "shoulder_rotation":    [11, 12],           # left / right shoulder
    "hip_rotation":         [23, 24],           # left / right hip
    "knee_bend":            [25, 26],           # left / right knee
    "racket_arm_elevation": [11, 12, 13, 14],   # shoulder + elbow (hitting side)
    "trunk_rotation":       [11, 12, 23, 24],   # both shoulders + both hips
    "left_elbow_angle":     [11, 13],           # left shoulder + left elbow
    "left_arm_elevation":   [11, 13, 23],       # left shoulder + elbow + hip
    "stance_width":         [27, 28],           # left + right ankle
    "head_movement":        [0, 11, 12],        # nose + both shoulders
}

# Direction labels per metric — overrides "too_wide"/"too_narrow" where semantics differ
_DIRECTION_LABELS: dict[str, tuple[str, str]] = {
    "default":       ("too_wide", "too_narrow"),
    "head_movement": ("too_low",  "too_high"),
}

# Default: assume right-handed player (same as feature_engine default)
# Landmark indices for the right (hitting) arm/leg
_HIT_SHOULDER = 12
_HIT_ELBOW    = 14
_HIT_WRIST    = 16
_HIT_HIP      = 24
_HIT_KNEE     = 26
_HIT_ANKLE    = 28
_L_SHOULDER   = 11
_R_SHOULDER   = 12
_L_HIP        = 23
_R_HIP        = 24


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class JointDeviation:
    joint_name: str
    landmark_indices: list[int]
    user_angle: float
    pro_angle: float
    diff_degrees: float         # user - pro (signed)
    direction: str              # "too_wide" | "too_narrow"


@dataclass
class FrameDeviation:
    frame_index: int
    deviating_joints: list[JointDeviation]
    phase: str
    severity: str               # worst severity among deviating joints this frame


# ---------------------------------------------------------------------------
# Internal: per-frame angle computation from raw landmarks
# ---------------------------------------------------------------------------

def _angle_for_joint(joint: str, landmarks_frame: np.ndarray) -> float | None:
    """
    Compute the angle for a named joint from a single frame's landmark array.

    Args:
        joint:            joint name matching keys in JOINT_LANDMARK_MAP
        landmarks_frame:  (33, 3) array for one frame

    Returns:
        Angle in degrees, or None if the joint name is not recognised.
    """
    lm = landmarks_frame  # convenience alias

    if joint == "elbow_angle":
        return compute_angle(lm[_HIT_SHOULDER], lm[_HIT_ELBOW], lm[_HIT_WRIST])
    if joint == "knee_bend":
        return compute_angle(lm[_HIT_HIP], lm[_HIT_KNEE], lm[_HIT_ANKLE])
    if joint == "racket_arm_elevation":
        return compute_angle(lm[_HIT_ELBOW], lm[_HIT_SHOULDER], lm[_HIT_HIP])
    if joint == "shoulder_rotation":
        return _line_angle_deg(lm[_L_SHOULDER], lm[_R_SHOULDER])
    if joint == "hip_rotation":
        return _line_angle_deg(lm[_L_HIP], lm[_R_HIP])
    if joint == "trunk_rotation":
        shoulder = _line_angle_deg(lm[_L_SHOULDER], lm[_R_SHOULDER])
        hip      = _line_angle_deg(lm[_L_HIP],      lm[_R_HIP])
        return (shoulder - hip) % 360.0

    # Non-hitting arm (assumes right-handed; left shoulder = 11, left elbow = 13, left wrist = 15)
    if joint == "left_elbow_angle":
        return compute_angle(lm[11], lm[13], lm[15])
    if joint == "left_arm_elevation":
        return compute_angle(lm[13], lm[11], lm[23])

    # Distance/offset metrics — returned as scalar values compatible with diff_degrees field
    if joint == "stance_width":
        return float(np.sqrt((lm[27, 0] - lm[28, 0])**2 + (lm[27, 1] - lm[28, 1])**2))
    if joint == "head_movement":
        return float(lm[0, 1] - (lm[11, 1] + lm[12, 1]) / 2)

    return None


def _frame_phase(frame_index: int, phases: dict[str, tuple[int, int]]) -> str:
    """Return the phase name the given frame falls in, or 'unknown'."""
    from app.worker.phase_aligner import PHASE_ORDER
    for phase in PHASE_ORDER:
        if phase in phases:
            start, end = phases[phase]
            if start <= frame_index <= end:
                return phase
    return "unknown"


def _worst_severity(deviations: list[JointDeviation], deviation_list: list[Deviation]) -> str:
    """
    Return the worst severity among a set of JointDeviations by looking up
    the matching Deviation from the DTW comparator result.
    """
    severity_rank = {"critical": 0, "moderate": 1, "minor": 2}
    best_rank = 2  # start at "minor"

    joint_names = {jd.joint_name for jd in deviations}
    for dev in deviation_list:
        if dev.joint in joint_names:
            rank = severity_rank.get(dev.severity, 2)
            if rank < best_rank:
                best_rank = rank

    return _SEVERITY_ORDER[best_rank]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_frame_deviations(
    user_landmarks: np.ndarray,        # (N, 33, 3)
    pro_landmarks_aligned: np.ndarray, # (N, 33, 3) — already resampled to N frames
    phases: dict[str, tuple[int, int]],
    deviations: list[Deviation],
    threshold_degrees: float = _DEFAULT_THRESHOLD_DEGREES,
) -> list[FrameDeviation]:
    """
    Compute per-frame deviations by comparing user and aligned pro landmarks.

    For each frame, checks each joint listed in the DTW deviations.  A joint
    is flagged on a frame when:
      - The frame falls within the joint's deviation phase, AND
      - |user_angle - pro_angle| > threshold_degrees

    Args:
        user_landmarks:        (N, 33, 3) user pose landmarks
        pro_landmarks_aligned: (N, 33, 3) pro landmarks resampled to same length
        phases:                phase boundaries for the user swing
        deviations:            DTW comparison deviations from compare_swing()
        threshold_degrees:     minimum angle difference to flag (default 10°)

    Returns:
        List of FrameDeviation, one entry per frame that has at least one
        deviating joint.  Frames with no deviations are omitted.
    """
    n_frames = user_landmarks.shape[0]
    frame_deviations: list[FrameDeviation] = []

    # Build a quick lookup: phase_name → set of joints deviating in that phase
    phase_to_deviations: dict[str, list[Deviation]] = {}
    for dev in deviations:
        phase_to_deviations.setdefault(dev.phase, []).append(dev)

    for frame_idx in range(n_frames):
        phase = _frame_phase(frame_idx, phases)
        if phase == "unknown":
            continue

        # Only consider deviations that apply to this phase
        active_deviations = phase_to_deviations.get(phase, [])
        if not active_deviations:
            continue

        user_frame = user_landmarks[frame_idx]   # (33, 3)
        pro_frame  = pro_landmarks_aligned[frame_idx]  # (33, 3)

        joint_devs: list[JointDeviation] = []

        for dev in active_deviations:
            user_angle = _angle_for_joint(dev.joint, user_frame)
            pro_angle  = _angle_for_joint(dev.joint, pro_frame)

            if user_angle is None or pro_angle is None:
                continue

            diff = user_angle - pro_angle
            if abs(diff) < threshold_degrees:
                continue

            labels = _DIRECTION_LABELS.get(dev.joint, _DIRECTION_LABELS["default"])
            direction = labels[0] if diff > 0 else labels[1]
            landmark_indices = JOINT_LANDMARK_MAP.get(dev.joint, [])

            joint_devs.append(JointDeviation(
                joint_name=dev.joint,
                landmark_indices=landmark_indices,
                user_angle=round(float(user_angle), 2),
                pro_angle=round(float(pro_angle), 2),
                diff_degrees=round(float(diff), 2),
                direction=direction,
            ))

        if joint_devs:
            severity = _worst_severity(joint_devs, deviations)
            frame_deviations.append(FrameDeviation(
                frame_index=frame_idx,
                deviating_joints=joint_devs,
                phase=phase,
                severity=severity,
            ))

    logger.info(
        "Deviation annotation: %d/%d frames have deviations",
        len(frame_deviations), n_frames,
    )

    return frame_deviations
