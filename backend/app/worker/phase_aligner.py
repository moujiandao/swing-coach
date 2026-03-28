"""
Phase alignment engine: maps user swing frames to pro reference frames.

The problem: a user's swing might be 90 frames while the pro reference is 60.
Each phase (preparation, backswing, etc.) has a different duration in each.
This module computes a frame_mapping array so that for every user frame we know
the corresponding pro frame to overlay — aligned by phase, not just total length.
"""
import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# Canonical phase order — must match feature_engine.py
PHASE_ORDER = [
    "preparation",
    "backswing",
    "forward_swing",
    "contact",
    "follow_through",
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PhaseBoundary:
    phase_name: str
    user_start: int
    user_end: int
    pro_start: int
    pro_end: int
    user_duration_frames: int
    pro_duration_frames: int
    tempo_ratio: float  # user_duration / pro_duration; >1 means user is slower


@dataclass
class PhaseAlignmentResult:
    # Length == user_frame_count; frame_mapping[user_frame] = pro_frame_index
    frame_mapping: list[int]
    # Per-phase alignment info for tempo feedback
    phase_boundaries: dict[str, PhaseBoundary]
    total_user_frames: int
    total_pro_frames: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def align_phases(
    user_phases: dict[str, tuple[int, int]],
    pro_phases: dict[str, tuple[int, int]],
    user_frame_count: int,
    pro_frame_count: int,
) -> PhaseAlignmentResult:
    """
    Build a frame-by-frame mapping from user swing frames to pro reference frames.

    For each phase present in both swings, a linear interpolation maps user
    frames to pro frames within that phase.  User frames that don't fall in
    any shared phase are filled by nearest-neighbour from the closest mapped
    frame (forward-fill then backward-fill).

    Args:
        user_phases:       dict phase_name → (start, end) inclusive, from feature_engine
        pro_phases:        dict phase_name → (start, end) inclusive, from pro reference
        user_frame_count:  total number of user frames
        pro_frame_count:   total number of pro frames

    Returns:
        PhaseAlignmentResult with frame_mapping and per-phase PhaseBoundary info
    """
    # float sentinel so we can detect unmapped frames later
    mapping = np.full(user_frame_count, np.nan, dtype=np.float64)
    phase_boundaries: dict[str, PhaseBoundary] = {}

    for phase in PHASE_ORDER:
        if phase not in user_phases or phase not in pro_phases:
            logger.debug("Phase '%s' missing from user or pro — skipping in mapping", phase)
            continue

        u_start, u_end = user_phases[phase]
        p_start, p_end = pro_phases[phase]

        # Inclusive durations (minimum 1 frame each)
        n_user = max(u_end - u_start + 1, 1)
        n_pro  = max(p_end - p_start + 1, 1)

        # Linear interpolation: user frame i → pro frame
        # np.interp maps [u_start..u_end] → [p_start..p_end]
        user_frames = np.arange(u_start, u_end + 1, dtype=np.float64)
        if n_user == 1:
            # Single-frame phase: map to midpoint of pro phase
            pro_mapped = np.array([p_start + (n_pro - 1) / 2.0])
        else:
            pro_mapped = np.interp(
                user_frames,
                [u_start, u_end],
                [p_start, p_end],
            )

        # Write into mapping array
        for local_i, pro_f in zip(range(u_start, u_end + 1), pro_mapped):
            mapping[local_i] = pro_f

        # PhaseBoundary record
        tempo_ratio = n_user / n_pro if n_pro > 0 else 1.0
        phase_boundaries[phase] = PhaseBoundary(
            phase_name=phase,
            user_start=u_start,
            user_end=u_end,
            pro_start=p_start,
            pro_end=p_end,
            user_duration_frames=n_user,
            pro_duration_frames=n_pro,
            tempo_ratio=tempo_ratio,
        )

    # Fill unmapped frames (those not in any shared phase) using nearest-neighbour.
    # Forward-fill first, then backward-fill for any leading unmapped frames.
    _forward_fill(mapping)
    _backward_fill(mapping)

    # Any still-nan frames (edge case: no phases at all) → map to 0
    mapping = np.where(np.isnan(mapping), 0.0, mapping)

    # Round and clamp to valid pro frame indices
    frame_mapping = np.clip(np.round(mapping), 0, pro_frame_count - 1).astype(int).tolist()

    logger.info(
        "Phase alignment: %d user frames → %d pro frames, %d phases aligned",
        user_frame_count, pro_frame_count, len(phase_boundaries),
    )

    return PhaseAlignmentResult(
        frame_mapping=frame_mapping,
        phase_boundaries=phase_boundaries,
        total_user_frames=user_frame_count,
        total_pro_frames=pro_frame_count,
    )


def resample_landmarks(
    landmarks: np.ndarray,
    target_length: int,
) -> np.ndarray:
    """
    Resample a landmark sequence to a target number of frames using linear
    interpolation per landmark per coordinate.

    Args:
        landmarks:     (N, 33, 3) float array of normalized x,y,z coordinates
        target_length: desired number of output frames

    Returns:
        np.ndarray of shape (target_length, 33, 3)
    """
    n = landmarks.shape[0]
    if n == target_length:
        return landmarks.copy()

    x_old = np.linspace(0.0, 1.0, n)
    x_new = np.linspace(0.0, 1.0, target_length)

    # Interpolate each of the 33 * 3 = 99 timeseries independently
    resampled = np.zeros((target_length, 33, 3), dtype=landmarks.dtype)
    for lm_idx in range(33):
        for coord in range(3):
            resampled[:, lm_idx, coord] = np.interp(
                x_new, x_old, landmarks[:, lm_idx, coord]
            )

    return resampled


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _forward_fill(arr: np.ndarray) -> None:
    """Replace NaN entries with the last non-NaN value (in-place)."""
    last = np.nan
    for i in range(len(arr)):
        if not np.isnan(arr[i]):
            last = arr[i]
        elif not np.isnan(last):
            arr[i] = last


def _backward_fill(arr: np.ndarray) -> None:
    """Replace leading NaN entries with the first non-NaN value (in-place)."""
    first = np.nan
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            first = arr[i]
        elif not np.isnan(first):
            arr[i] = first
