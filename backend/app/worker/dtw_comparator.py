"""
DTW comparison between a user's swing features and a pro reference.

Stage 4 of the worker pipeline: FeatureExtractionResult + pro reference → ComparisonResult.

Uses tslearn for DTW distance computation with alignment path extraction.
Phase-segmented comparison so deviations are localized and actionable.
"""
import logging
import math
from dataclasses import dataclass, field

import numpy as np
from tslearn.metrics import dtw, dtw_path

from app.worker.feature_engine import FeatureExtractionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

_SCALE_FACTOR = 50.0  # DTW distance at which score decays to 100/e ≈ 37

_PHASE_WEIGHTS: dict[str, float] = {
    "preparation":   0.05,
    "backswing":     0.15,
    "forward_swing": 0.35,
    "contact":       0.30,
    "follow_through": 0.15,
}

_SEVERITY_THRESHOLDS = {
    "critical": 40.0,   # score < 40
    "moderate": 60.0,   # 40 <= score < 60
    "minor":    70.0,   # 60 <= score < 70
    # score >= 70 → not added to deviations list
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Deviation:
    joint: str
    phase: str
    mean_diff_degrees: float
    max_diff_degrees: float
    timing_offset_ms: float
    severity: str
    description: str


@dataclass
class ComparisonResult:
    overall_score: float                    # 0-100
    phase_scores: dict[str, float]          # per-phase 0-100
    deviations: list[Deviation] = field(default_factory=list)  # worst first


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resample(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Resample a 1-D array to target_len using linear interpolation."""
    if len(arr) == target_len:
        return arr
    x_old = np.linspace(0.0, 1.0, len(arr))
    x_new = np.linspace(0.0, 1.0, target_len)
    return np.interp(x_new, x_old, arr).astype(np.float32)


def _dtw_score(user_seg: np.ndarray, pro_seg: np.ndarray) -> float:
    """
    Compute a 0-100 similarity score from the DTW distance between two segments.
    Both segments are 1-D float arrays (one joint angle timeseries for one phase).
    """
    # tslearn expects (n, 1) shaped series
    u = user_seg.reshape(-1, 1).astype(np.float64)
    p = pro_seg.reshape(-1, 1).astype(np.float64)
    dist = dtw(u, p)
    # Normalise by length so shorter phases don't dominate
    normalised = dist / max(len(user_seg), 1)
    return float(100.0 * math.exp(-normalised / _SCALE_FACTOR))


def _timing_offset_ms(
    user_seg: np.ndarray,
    pro_seg: np.ndarray,
    fps: float,
) -> float:
    """
    Use the DTW alignment path to estimate how many milliseconds ahead or behind
    the user's motion is relative to the pro reference.

    Positive = user is ahead (faster execution); negative = user is late.
    """
    u = user_seg.reshape(-1, 1).astype(np.float64)
    p = pro_seg.reshape(-1, 1).astype(np.float64)
    path, _ = dtw_path(u, p)
    if not path:
        return 0.0
    # Average (user_frame - pro_frame) along alignment path
    diffs = [uf - pf for uf, pf in path]
    mean_frame_diff = float(np.mean(diffs))
    return mean_frame_diff * (1000.0 / fps)


def _classify_severity(score: float) -> str | None:
    """Return severity string for a given score, or None if no deviation."""
    if score < _SEVERITY_THRESHOLDS["critical"]:
        return "critical"
    if score < _SEVERITY_THRESHOLDS["moderate"]:
        return "moderate"
    if score < _SEVERITY_THRESHOLDS["minor"]:
        return "minor"
    return None


def _describe_deviation(
    joint: str,
    phase: str,
    mean_diff: float,
    severity: str,
) -> str:
    joint_label = joint.replace("_", " ").title()
    phase_label = phase.replace("_", " ")
    direction = "wider" if mean_diff > 0 else "tighter"
    return (
        f"{joint_label} is {abs(mean_diff):.0f}° {direction} than reference "
        f"during {phase_label} ({severity})"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_swing(
    user_features: FeatureExtractionResult,
    pro_reference: dict,           # from ProReferenceDB.get_reference()
    fps: float = 30.0,
) -> ComparisonResult:
    """
    Compare user swing features against a pro reference using phase-segmented DTW.

    Args:
        user_features: Output of extract_features() for the user's swing.
        pro_reference: Reference dict with keys "joint_angles" and "phases".
        fps: Frames per second (used for timing offset calculation).

    Returns:
        ComparisonResult with overall_score, phase_scores, and deviations list.
    """
    user_angles = user_features.joint_angles
    user_phases = user_features.phases

    pro_angles: dict[str, np.ndarray] = pro_reference["joint_angles"]
    pro_phases: dict[str, tuple[int, int]] = pro_reference["phases"]

    # Only compare joints present in both
    common_joints = set(user_angles.keys()) & set(pro_angles.keys())
    if not common_joints:
        raise ValueError("No common joint angles between user features and pro reference.")

    phase_names = list(_PHASE_WEIGHTS.keys())

    # phase_scores[phase] = mean score across all joints for that phase
    phase_scores: dict[str, float] = {}
    all_deviations: list[Deviation] = []

    for phase in phase_names:
        if phase not in user_phases or phase not in pro_phases:
            phase_scores[phase] = 50.0  # neutral fallback
            continue

        u_start, u_end = user_phases[phase]
        p_start, p_end = pro_phases[phase]

        joint_phase_scores: list[float] = []

        for joint in sorted(common_joints):
            user_seg = user_angles[joint][u_start: u_end + 1]
            pro_seg  = pro_angles[joint][p_start: p_end + 1]

            if len(user_seg) < 2 or len(pro_seg) < 2:
                continue

            # Resample both to the same length for fair DTW comparison
            target_len = max(len(user_seg), len(pro_seg))
            user_rs = _resample(user_seg, target_len)
            pro_rs  = _resample(pro_seg,  target_len)

            score = _dtw_score(user_rs, pro_rs)
            joint_phase_scores.append(score)

            severity = _classify_severity(score)
            if severity is not None:
                mean_diff = float(np.mean(user_rs - pro_rs))
                max_diff  = float(np.max(np.abs(user_rs - pro_rs)))
                t_offset  = _timing_offset_ms(user_rs, pro_rs, fps)
                all_deviations.append(Deviation(
                    joint=joint,
                    phase=phase,
                    mean_diff_degrees=mean_diff,
                    max_diff_degrees=max_diff,
                    timing_offset_ms=t_offset,
                    severity=severity,
                    description=_describe_deviation(joint, phase, mean_diff, severity),
                ))

        phase_scores[phase] = float(np.mean(joint_phase_scores)) if joint_phase_scores else 50.0

    # Weighted overall score
    total_weight = sum(_PHASE_WEIGHTS[p] for p in phase_names if p in phase_scores)
    overall = sum(
        _PHASE_WEIGHTS[p] * phase_scores[p]
        for p in phase_names
        if p in phase_scores
    ) / max(total_weight, 1e-9)

    # Sort deviations: critical first, then by score ascending (worst first)
    severity_order = {"critical": 0, "moderate": 1, "minor": 2}
    all_deviations.sort(key=lambda d: severity_order.get(d.severity, 9))

    logger.info(
        "DTW comparison complete: overall=%.1f, phases=%s, deviations=%d",
        overall,
        {p: f"{s:.1f}" for p, s in phase_scores.items()},
        len(all_deviations),
    )

    return ComparisonResult(
        overall_score=overall,
        phase_scores=phase_scores,
        deviations=all_deviations,
    )
