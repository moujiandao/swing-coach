"""
Tests for app/worker/angle_features.py — angle-invariant feature extraction.
"""
import numpy as np
import pytest

from app.worker.angle_features import (
    ANGLE_FEATURE_KEYS,
    VELOCITY_FEATURE_KEYS,
    extract_angle_features,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_synthetic_landmarks(n: int = 30, seed: int = 0) -> np.ndarray:
    """
    Create a (N, 33, 3) synthetic landmark array with plausible joint positions.
    Not anatomically accurate, but structured enough for feature extraction.
    """
    rng = np.random.default_rng(seed)
    # Start with a base skeleton and add small per-frame variation
    base = rng.uniform(0.2, 0.8, (33, 3)).astype(np.float32)
    landmarks = np.tile(base, (n, 1, 1))
    # Add smooth per-frame noise to simulate motion
    noise = rng.normal(0, 0.02, (n, 33, 3)).astype(np.float32)
    noise = np.cumsum(noise, axis=0)  # smooth drift
    landmarks = landmarks + noise
    landmarks = np.clip(landmarks, 0.0, 1.0)
    return landmarks


# ---------------------------------------------------------------------------
# extract_angle_features
# ---------------------------------------------------------------------------

class TestExtractAngleFeatures:
    def test_output_keys(self):
        """Output contains all expected angle and velocity feature keys."""
        lm = _make_synthetic_landmarks(n=20, seed=1)
        result = extract_angle_features(lm, fps=30.0)
        for key in ANGLE_FEATURE_KEYS:
            assert key in result, f"Missing angle feature: {key}"
        for key in VELOCITY_FEATURE_KEYS:
            assert key in result, f"Missing velocity feature: {key}"

    def test_output_shape(self):
        """Each feature array has length N matching input frame count."""
        n = 25
        lm = _make_synthetic_landmarks(n=n, seed=2)
        result = extract_angle_features(lm, fps=30.0)
        for key, arr in result.items():
            assert arr.shape == (n,), f"Feature {key}: expected shape ({n},), got {arr.shape}"

    def test_output_dtype(self):
        """All output arrays are float32."""
        lm = _make_synthetic_landmarks(n=15, seed=3)
        result = extract_angle_features(lm, fps=30.0)
        for key, arr in result.items():
            assert arr.dtype == np.float32, f"Feature {key}: expected float32, got {arr.dtype}"

    def test_angle_ranges(self):
        """Joint angles should be in [0, 180], segment angles in [0, 360)."""
        lm = _make_synthetic_landmarks(n=20, seed=4)
        result = extract_angle_features(lm, fps=30.0)

        joint_angle_keys = [
            "elbow_flexion_hit", "elbow_flexion_nonhit",
            "shoulder_abduction_hit",
            "knee_bend_hit", "knee_bend_nonhit",
            "wrist_deviation_hit",
        ]
        for key in joint_angle_keys:
            assert np.all(result[key] >= 0.0), f"{key} has negative values"
            assert np.all(result[key] <= 180.0), f"{key} exceeds 180 degrees"

        segment_angle_keys = [
            "shoulder_rotation_est", "hip_rotation_est", "trunk_lateral_tilt",
        ]
        for key in segment_angle_keys:
            assert np.all(result[key] >= 0.0), f"{key} has negative values"
            assert np.all(result[key] < 360.0), f"{key} exceeds 360 degrees"

    def test_handedness_left(self):
        """Left-handed extraction runs without error and produces same keys."""
        lm = _make_synthetic_landmarks(n=15, seed=5)
        result = extract_angle_features(lm, fps=30.0, handedness="left")
        for key in ANGLE_FEATURE_KEYS:
            assert key in result

    def test_handedness_swaps_sides(self):
        """Left vs right handedness should produce different elbow flexion values."""
        lm = _make_synthetic_landmarks(n=15, seed=6)
        right = extract_angle_features(lm, fps=30.0, handedness="right")
        left = extract_angle_features(lm, fps=30.0, handedness="left")
        # Hit arm elbow for right should equal non-hit for left (they use same landmarks)
        np.testing.assert_allclose(
            right["elbow_flexion_hit"],
            left["elbow_flexion_nonhit"],
            atol=0.01,
        )

    def test_velocity_nonzero_for_moving_input(self):
        """Velocity features should be non-zero when landmarks move over time."""
        lm = _make_synthetic_landmarks(n=30, seed=7)
        result = extract_angle_features(lm, fps=30.0)
        for key in VELOCITY_FEATURE_KEYS:
            assert np.any(np.abs(result[key]) > 0.1), (
                f"Velocity {key} is unexpectedly near-zero for moving input"
            )

    def test_invalid_shape_raises(self):
        """Wrong input shape raises ValueError."""
        with pytest.raises(ValueError, match="Expected landmarks shape"):
            extract_angle_features(np.zeros((10, 2)), fps=30.0)

    def test_single_frame(self):
        """Single frame extraction works (velocities will be zero)."""
        lm = _make_synthetic_landmarks(n=1, seed=8)
        result = extract_angle_features(lm, fps=30.0)
        assert result["elbow_flexion_hit"].shape == (1,)
        # Single frame -> zero velocity
        for key in VELOCITY_FEATURE_KEYS:
            assert result[key][0] == 0.0

    def test_feature_count(self):
        """Total feature count matches ANGLE + VELOCITY keys."""
        lm = _make_synthetic_landmarks(n=10, seed=9)
        result = extract_angle_features(lm, fps=30.0)
        expected = len(ANGLE_FEATURE_KEYS) + len(VELOCITY_FEATURE_KEYS)
        assert len(result) == expected, f"Expected {expected} features, got {len(result)}"

    def test_deterministic(self):
        """Same input produces identical output."""
        lm = _make_synthetic_landmarks(n=15, seed=10)
        r1 = extract_angle_features(lm, fps=30.0)
        r2 = extract_angle_features(lm, fps=30.0)
        for key in r1:
            np.testing.assert_array_equal(r1[key], r2[key])
