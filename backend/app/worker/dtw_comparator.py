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

# Per-phase scale factors: DTW distance at which score decays to 100/e ~ 37.
# Higher = more forgiving (needs larger distance to penalize).
_PHASE_SCALE_FACTORS: dict[str, float] = {
    "preparation":    50.0,
    "backswing":      65.0,   # more forgiving - beginners often have unconventional backswings
    "forward_swing":  50.0,
    "contact":        50.0,
    "follow_through": 35.0,   # stricter - follow-through is a reliable indicator of form
}
_DEFAULT_SCALE_FACTOR = 50.0  # fallback for unlisted phases

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
    swing_tempo: dict | None = None         # {user_ratio, pro_ratio, similarity}


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


def _dtw_score(
    user_seg: np.ndarray,
    pro_seg: np.ndarray,
    scale_factor: float = _DEFAULT_SCALE_FACTOR,
) -> float:
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
    return float(100.0 * math.exp(-normalised / scale_factor))


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
    user_velocities = user_features.velocities

    pro_angles: dict[str, np.ndarray] = pro_reference["joint_angles"]
    pro_phases: dict[str, tuple[int, int]] = pro_reference["phases"]
    pro_velocities: dict[str, np.ndarray] = pro_reference.get("velocities", {})

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
        phase_scale = _PHASE_SCALE_FACTORS.get(phase, _DEFAULT_SCALE_FACTOR)

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

            score = _dtw_score(user_rs, pro_rs, scale_factor=phase_scale)
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

        # Forward swing: also compare wrist_acceleration from velocities
        if phase == "forward_swing":
            user_accel = user_velocities.get("wrist_acceleration")
            pro_accel = pro_velocities.get("wrist_acceleration")
            if user_accel is not None and pro_accel is not None:
                u_seg = user_accel[u_start: u_end + 1]
                p_seg = pro_accel[p_start: p_end + 1]
                if len(u_seg) >= 2 and len(p_seg) >= 2:
                    tlen = max(len(u_seg), len(p_seg))
                    u_rs = _resample(u_seg, tlen)
                    p_rs = _resample(p_seg, tlen)
                    accel_score = _dtw_score(u_rs, p_rs, scale_factor=phase_scale)
                    joint_phase_scores.append(accel_score)

                    severity = _classify_severity(accel_score)
                    if severity is not None:
                        mean_diff = float(np.mean(u_rs - p_rs))
                        max_diff = float(np.max(np.abs(u_rs - p_rs)))
                        t_offset = _timing_offset_ms(u_rs, p_rs, fps)
                        all_deviations.append(Deviation(
                            joint="wrist_acceleration",
                            phase=phase,
                            mean_diff_degrees=mean_diff,
                            max_diff_degrees=max_diff,
                            timing_offset_ms=t_offset,
                            severity=severity,
                            description=_describe_deviation(
                                "wrist_acceleration", phase, mean_diff, severity
                            ),
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

    # Swing tempo: backswing duration / forward swing duration
    swing_tempo = None
    if "backswing" in user_phases and "forward_swing" in user_phases \
       and "backswing" in pro_phases and "forward_swing" in pro_phases:
        u_bs = user_phases["backswing"]
        u_fs = user_phases["forward_swing"]
        p_bs = pro_phases["backswing"]
        p_fs = pro_phases["forward_swing"]

        u_bs_dur = u_bs[1] - u_bs[0] + 1
        u_fs_dur = u_fs[1] - u_fs[0] + 1
        p_bs_dur = p_bs[1] - p_bs[0] + 1
        p_fs_dur = p_fs[1] - p_fs[0] + 1

        # Need at least 3 frames in each phase for a meaningful ratio
        min_frames = 3
        if u_bs_dur >= min_frames and u_fs_dur >= min_frames \
           and p_bs_dur >= min_frames and p_fs_dur >= min_frames:
            user_ratio = u_bs_dur / u_fs_dur
            pro_ratio = p_bs_dur / p_fs_dur

            # Similarity: how close the ratios are (0-100 scale)
            # Using exponential decay on the absolute ratio difference.
            # Scale factor of 1.0 means a difference of 1.0 in ratios
            # (e.g., 2.5:1 vs 3.5:1) scores ~37. Gentler than relative diff
            # which punishes small pro ratios disproportionately.
            ratio_diff = abs(user_ratio - pro_ratio)
            tempo_similarity = 100.0 * math.exp(-ratio_diff / 1.0)

            swing_tempo = {
                "user_ratio": round(user_ratio, 2),
                "pro_ratio": round(pro_ratio, 2),
                "similarity": round(tempo_similarity, 1),
            }
            phase_scores["swing_tempo"] = tempo_similarity

            severity = _classify_severity(tempo_similarity)
            if severity is not None:
                if user_ratio > pro_ratio:
                    desc = (
                        f"Backswing is relatively slow compared to forward swing "
                        f"(ratio {user_ratio:.1f}:1 vs pro's {pro_ratio:.1f}:1). "
                        f"Try a quicker takeback to better load the forward swing."
                    )
                else:
                    desc = (
                        f"Backswing is rushed relative to forward swing "
                        f"(ratio {user_ratio:.1f}:1 vs pro's {pro_ratio:.1f}:1). "
                        f"Slow down the takeback to build more torque."
                    )
                all_deviations.append(Deviation(
                    joint="swing_tempo",
                    phase="backswing",
                    mean_diff_degrees=round(user_ratio - pro_ratio, 2),
                    max_diff_degrees=round(abs(user_ratio - pro_ratio), 2),
                    timing_offset_ms=0.0,
                    severity=severity,
                    description=desc,
                ))
                # Re-sort after adding tempo deviation
                all_deviations.sort(key=lambda d: severity_order.get(d.severity, 9))

    logger.info(
        "DTW comparison complete: overall=%.1f, phases=%s, deviations=%d, tempo=%s",
        overall,
        {p: f"{s:.1f}" for p, s in phase_scores.items()},
        len(all_deviations),
        swing_tempo,
    )

    return ComparisonResult(
        overall_score=overall,
        phase_scores=phase_scores,
        deviations=all_deviations,
        swing_tempo=swing_tempo,
    )


# ---------------------------------------------------------------------------
# Base score — lower body fundamentals across the entire swing
# ---------------------------------------------------------------------------

_BASE_SCORE_WEIGHTS: dict[str, float] = {
    "stance_width":  0.25,
    "knee_bend":     0.30,
    "hip_rotation":  0.25,
    "hip_speed":     0.20,
}


def compute_base_score(
    user_features: FeatureExtractionResult,
    pro_reference: dict,
    user_phases: dict[str, tuple[int, int]] | None = None,
    pro_phases: dict[str, tuple[int, int]] | None = None,
) -> float:
    """
    Compute a 0-100 "base" score evaluating lower body fundamentals
    within the active swing evaluation window.

    Compares stance_width, knee_bend, and hip_rotation from joint_angles,
    plus hip_speed from velocities, using DTW with weighted averaging.
    Trims input series to the evaluation window defined by phase boundaries
    so idle frames at the start/end of the video don't dilute the score.

    Args:
        user_features: Output of extract_features().
        pro_reference: Reference dict with "joint_angles" and "velocities".
        user_phases: User phase boundaries for trimming. Falls back to user_features.phases.
        pro_phases: Pro phase boundaries for trimming. Falls back to pro_reference["phases"].

    Returns:
        Single 0-100 float.
    """
    user_angles = user_features.joint_angles
    user_velocities = user_features.velocities
    pro_angles: dict[str, np.ndarray] = pro_reference.get("joint_angles", {})
    pro_velocities: dict[str, np.ndarray] = pro_reference.get("velocities", {})

    # Determine evaluation windows from phase boundaries
    u_ph = user_phases or user_features.phases
    p_ph = pro_phases or pro_reference.get("phases", {})
    u_start = min(s for s, _ in u_ph.values()) if u_ph else 0
    u_end = max(e for _, e in u_ph.values()) if u_ph else None
    p_start = min(s for s, _ in p_ph.values()) if p_ph else 0
    p_end = max(e for _, e in p_ph.values()) if p_ph else None

    weighted_sum = 0.0
    total_weight = 0.0

    for key, weight in _BASE_SCORE_WEIGHTS.items():
        # hip_speed lives in velocities; the rest are in joint_angles
        if key == "hip_speed":
            user_series = user_velocities.get(key)
            pro_series = pro_velocities.get(key)
        else:
            user_series = user_angles.get(key)
            pro_series = pro_angles.get(key)

        if user_series is None or pro_series is None:
            continue

        # Trim to evaluation window
        user_series = user_series[u_start: (u_end + 1) if u_end is not None else None]
        pro_series = pro_series[p_start: (p_end + 1) if p_end is not None else None]

        if len(user_series) < 2 or len(pro_series) < 2:
            continue

        target_len = max(len(user_series), len(pro_series))
        user_rs = _resample(user_series, target_len)
        pro_rs = _resample(pro_series, target_len)

        score = _dtw_score(user_rs, pro_rs)
        weighted_sum += weight * score
        total_weight += weight

    if total_weight < 1e-9:
        logger.warning("Base score: no matching lower-body features found, returning 50.0")
        return 50.0

    base = weighted_sum / total_weight
    logger.info("Base score computed: %.1f", base)
    return float(base)
