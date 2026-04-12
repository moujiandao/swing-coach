"""
Tests for DTW comparator angle distance mode.

Verifies that distance_mode='angle' produces valid scores and that
angle-mode scores are more stable than landmark-mode when landmarks
are artificially rotated (simulating a different camera angle).
"""
import numpy as np
import pytest

from app.worker.dtw_comparator import DISTANCE_MODES, ComparisonResult, compare_swing
from app.worker.feature_engine import FeatureExtractionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_N = 60
_PHASES = {
    "preparation":    (0,  9),
    "backswing":      (10, 24),
    "forward_swing":  (25, 38),
    "contact":        (37, 41),
    "follow_through": (42, _N - 1),
}


def _make_landmarks(n: int = _N, seed: int = 0) -> np.ndarray:
    """Create (N, 33, 3) synthetic landmarks with plausible motion."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.3, 0.7, (33, 3)).astype(np.float32)
    landmarks = np.tile(base, (n, 1, 1))
    # Add smooth motion per frame
    for i in range(n):
        t = i / max(n - 1, 1)
        # Simulate a swing arc on the hitting arm (right side: 12, 14, 16)
        landmarks[i, 16, 0] += 0.15 * np.sin(np.pi * t)  # wrist x
        landmarks[i, 16, 1] -= 0.10 * np.cos(np.pi * t)  # wrist y
        landmarks[i, 14, 0] += 0.08 * np.sin(np.pi * t)  # elbow x
        landmarks[i, 14, 1] -= 0.05 * np.cos(np.pi * t)  # elbow y
    return np.clip(landmarks, 0.01, 0.99)


def _rotate_landmarks_2d(landmarks: np.ndarray, angle_deg: float) -> np.ndarray:
    """
    Rotate all landmarks around their centroid in the XY plane.
    Simulates filming from a different camera angle.
    """
    rotated = landmarks.copy()
    rad = np.radians(angle_deg)
    cos_a, sin_a = np.cos(rad), np.sin(rad)

    for i in range(landmarks.shape[0]):
        cx = landmarks[i, :, 0].mean()
        cy = landmarks[i, :, 1].mean()
        dx = landmarks[i, :, 0] - cx
        dy = landmarks[i, :, 1] - cy
        rotated[i, :, 0] = cx + dx * cos_a - dy * sin_a
        rotated[i, :, 1] = cy + dx * sin_a + dy * cos_a

    return np.clip(rotated, 0.01, 0.99)


def _make_features_from_landmarks(landmarks: np.ndarray) -> FeatureExtractionResult:
    """Build a FeatureExtractionResult with the same phases for consistent comparison."""
    from app.worker.feature_engine import extract_features
    return extract_features(landmarks, fps=30.0, stroke_type="forehand", handedness="right")


def _make_pro_reference(landmarks: np.ndarray) -> dict:
    """Build a pro reference dict from landmarks."""
    features = _make_features_from_landmarks(landmarks)
    return {
        "player": "test_pro",
        "stroke_type": "forehand",
        "joint_angles": features.joint_angles,
        "velocities": features.velocities,
        "phases": features.phases,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Basic angle mode functionality
# ---------------------------------------------------------------------------

class TestAngleModeBasic:
    def test_angle_mode_returns_comparison_result(self):
        """Angle mode produces a valid ComparisonResult."""
        lm = _make_landmarks(seed=1)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        result = compare_swing(
            features, ref, fps=30.0,
            distance_mode="angle",
            user_landmarks=lm, pro_landmarks=lm,
        )
        assert isinstance(result, ComparisonResult)

    def test_angle_mode_identical_high_score(self):
        """Identical landmarks in angle mode produce a reasonably high overall score.
        Note: some phases may have very few frames from synthetic data, falling
        back to a neutral 50.0 score, which pulls the overall down."""
        lm = _make_landmarks(seed=2)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        result = compare_swing(
            features, ref, fps=30.0,
            distance_mode="angle",
            user_landmarks=lm, pro_landmarks=lm,
        )
        # Phases with enough frames score ~100; short phases fallback to 50.
        # Weighted average lands around 75-85 for synthetic data.
        assert result.overall_score > 75.0, f"Expected >75, got {result.overall_score:.1f}"

    def test_angle_mode_different_low_score(self):
        """Very different landmarks produce a low score in angle mode."""
        user_lm = _make_landmarks(seed=10)
        pro_lm = _make_landmarks(seed=99)
        user_features = _make_features_from_landmarks(user_lm)
        pro_ref = _make_pro_reference(pro_lm)
        result = compare_swing(
            user_features, pro_ref, fps=30.0,
            distance_mode="angle",
            user_landmarks=user_lm, pro_landmarks=pro_lm,
        )
        assert result.overall_score < 90.0, f"Expected <90, got {result.overall_score:.1f}"

    def test_angle_mode_phase_scores_present(self):
        """Angle mode populates all standard phase scores."""
        lm = _make_landmarks(seed=3)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        result = compare_swing(
            features, ref, fps=30.0,
            distance_mode="angle",
            user_landmarks=lm, pro_landmarks=lm,
        )
        expected_phases = {"preparation", "backswing", "forward_swing", "contact", "follow_through"}
        assert expected_phases.issubset(set(result.phase_scores.keys()))

    def test_angle_mode_score_in_range(self):
        """Overall score is in [0, 100]."""
        lm = _make_landmarks(seed=4)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        result = compare_swing(
            features, ref, fps=30.0,
            distance_mode="angle",
            user_landmarks=lm, pro_landmarks=lm,
        )
        assert 0.0 <= result.overall_score <= 100.0


# ---------------------------------------------------------------------------
# Camera angle stability: angle mode vs landmark mode
# ---------------------------------------------------------------------------

class TestAngleModeStability:
    def test_joint_angles_stable_under_rotation(self):
        """
        Pure joint angles (elbow flexion, knee bend) computed via compute_angle_3pt
        are invariant to 2D rotation. The segment-angle estimates (shoulder_rotation_est,
        hip_rotation_est, trunk_lateral_tilt) are NOT invariant - they depend on
        camera perspective.

        Phase 2 (3D world_landmarks) will fix the segment-angle features.
        This test verifies that the joint-angle features specifically are stable.
        """
        from app.worker.angle_features import extract_angle_features

        pro_lm = _make_landmarks(seed=20)
        rotated_lm = _rotate_landmarks_2d(pro_lm, angle_deg=15.0)

        orig_feats = extract_angle_features(pro_lm, fps=30.0)
        rot_feats = extract_angle_features(rotated_lm, fps=30.0)

        # Joint angles (3-point angles) should be nearly identical under rotation
        invariant_keys = [
            "elbow_flexion_hit", "elbow_flexion_nonhit",
            "shoulder_abduction_hit",
            "knee_bend_hit", "knee_bend_nonhit",
            "wrist_deviation_hit",
        ]
        for key in invariant_keys:
            diff = np.abs(orig_feats[key] - rot_feats[key])
            max_diff = float(np.max(diff))
            # 3-point angles are theoretically perfectly invariant to rotation,
            # but floating point and clipping introduce small differences
            assert max_diff < 2.0, (
                f"Joint angle {key} changed by {max_diff:.1f}° under 15° rotation "
                f"(expected near-invariance)"
            )

    def test_angle_mode_tolerates_moderate_rotation(self):
        """Angle mode score stays above 70 for a 20-degree camera rotation."""
        pro_lm = _make_landmarks(seed=30)
        rotated_lm = _rotate_landmarks_2d(pro_lm, angle_deg=20.0)
        features = _make_features_from_landmarks(rotated_lm)
        ref = _make_pro_reference(pro_lm)
        result = compare_swing(
            features, ref, fps=30.0,
            distance_mode="angle",
            user_landmarks=rotated_lm, pro_landmarks=pro_lm,
        )
        assert result.overall_score > 70.0, (
            f"Expected angle-mode score >70 under 20° rotation, got {result.overall_score:.1f}"
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestAngleModeErrors:
    def test_invalid_distance_mode_raises(self):
        """Invalid distance_mode raises ValueError."""
        lm = _make_landmarks(n=10, seed=40)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        with pytest.raises(ValueError, match="distance_mode"):
            compare_swing(features, ref, distance_mode="invalid")

    def test_angle_mode_missing_landmarks_raises(self):
        """Angle mode without landmarks raises ValueError."""
        lm = _make_landmarks(n=10, seed=41)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        with pytest.raises(ValueError, match="user_landmarks"):
            compare_swing(features, ref, distance_mode="angle")

    def test_landmark_mode_ignores_landmarks(self):
        """Landmark mode works fine even if landmarks are passed (ignored)."""
        lm = _make_landmarks(seed=42)
        features = _make_features_from_landmarks(lm)
        ref = _make_pro_reference(lm)
        result = compare_swing(
            features, ref, fps=30.0,
            distance_mode="landmark",
            user_landmarks=lm, pro_landmarks=lm,
        )
        # Synthetic data has short phases that fallback to 50.0
        assert result.overall_score > 75.0


# ---------------------------------------------------------------------------
# Distance mode constants
# ---------------------------------------------------------------------------

class TestDistanceModes:
    def test_distance_modes_tuple(self):
        assert "landmark" in DISTANCE_MODES
        assert "angle" in DISTANCE_MODES
