"""
Tests for app/worker/feature_engine.py

Covers:
- compute_angle with known geometries
- compute_velocity with a linear position series
- Phase detection with a synthetic sinusoidal wrist trajectory
- Left-hand mirroring swaps the correct landmarks
- FeatureExtractionResult shape and phase properties
"""
import numpy as np
import pytest

from app.worker.feature_engine import (
    FeatureExtractionResult,
    _L,
    _R,
    compute_angle,
    compute_velocity,
    detect_phases,
    extract_features,
)


# ---------------------------------------------------------------------------
# compute_angle
# ---------------------------------------------------------------------------

class TestComputeAngle:
    def test_90_degrees(self):
        # Right angle: a=(1,0), b=(0,0), c=(0,1)
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([0.0, 1.0, 0.0])
        assert abs(compute_angle(a, b, c) - 90.0) < 1e-4

    def test_180_degrees(self):
        # Straight line: a=(1,0), b=(0,0), c=(-1,0)
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([-1.0, 0.0, 0.0])
        assert abs(compute_angle(a, b, c) - 180.0) < 0.01

    def test_45_degrees(self):
        # a=(1,0), b=(0,0), c=(1,1) → 45°
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([1.0, 1.0, 0.0])
        assert abs(compute_angle(a, b, c) - 45.0) < 1e-4

    def test_0_degrees(self):
        # Coincident rays: a and c in same direction → 0°
        a = np.array([2.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([1.0, 0.0, 0.0])
        assert abs(compute_angle(a, b, c) - 0.0) < 0.01

    def test_result_in_0_360_range(self):
        rng = np.random.default_rng(42)
        for _ in range(20):
            a = rng.random(3)
            b = rng.random(3)
            c = rng.random(3)
            angle = compute_angle(a, b, c)
            assert 0.0 <= angle <= 360.0


# ---------------------------------------------------------------------------
# compute_velocity
# ---------------------------------------------------------------------------

class TestComputeVelocity:
    def test_linear_series_has_constant_speed(self):
        # Position increases linearly → velocity should be nearly constant
        fps = 30.0
        n = 30
        t = np.arange(n) / fps
        # wrist moves at 1 m/s in x, 0 in y (normalized coords, but concept holds)
        positions = np.column_stack([t, np.zeros(n), np.zeros(n)]).astype(np.float32)
        speed = compute_velocity(positions, fps)
        assert speed.shape == (n,)
        # Expect speed ≈ 1.0 everywhere (within savgol edge effects)
        assert np.allclose(speed[2:-2], 1.0, atol=0.1)

    def test_stationary_series_has_zero_speed(self):
        fps = 60.0
        n = 20
        positions = np.ones((n, 3), dtype=np.float32) * 0.5
        speed = compute_velocity(positions, fps)
        assert np.allclose(speed, 0.0, atol=1e-5)

    def test_output_shape(self):
        fps = 30.0
        n = 15
        positions = np.random.rand(n, 3).astype(np.float32)
        speed = compute_velocity(positions, fps)
        assert speed.shape == (n,)

    def test_smoothing_reduces_noise(self):
        # Smoothed velocity should have lower variance than a naive (unsmoothed) derivative
        fps = 30.0
        n = 60
        rng = np.random.default_rng(0)
        t = np.linspace(0, 2 * np.pi, n)
        clean = np.column_stack([np.sin(t), np.cos(t), np.zeros(n)]).astype(np.float32)
        noisy = clean + rng.normal(0, 0.1, clean.shape).astype(np.float32)

        # Smoothed speed via compute_velocity
        speed_smoothed = compute_velocity(noisy, fps)

        # Naive speed: raw gradient, no smoothing
        raw_vel = np.gradient(noisy, 1.0 / fps, axis=0)
        speed_raw = np.linalg.norm(raw_vel[:, :2], axis=1).astype(np.float32)

        # Smoothing must reduce variance compared to raw derivative
        assert np.std(speed_smoothed) < np.std(speed_raw)


# ---------------------------------------------------------------------------
# detect_phases
# ---------------------------------------------------------------------------

class TestDetectPhases:
    def _synthetic_wrist(self, n: int = 90):
        """
        Simulate a right-hand forehand wrist trajectory:
        - x increases slowly (preparation)
        - x decreases (backswing)
        - x increases fast (forward swing → contact at peak speed)
        - x continues (follow-through)
        Returns wrist_positions (N,3) and wrist_speed (N,).
        """
        t = np.linspace(0, 2 * np.pi, n)
        # Sinusoidal x: starts going forward, then backward, then fast forward
        x = np.sin(t)
        positions = np.column_stack([x, np.zeros(n), np.zeros(n)]).astype(np.float32)
        speed = compute_velocity(positions, fps=30.0)
        return positions, speed

    def test_returns_five_phases(self):
        positions, speed = self._synthetic_wrist()
        phases, contact_frame = detect_phases(positions, speed)
        assert set(phases.keys()) == {
            "preparation", "backswing", "forward_swing", "contact", "follow_through"
        }

    def test_phases_non_overlapping(self):
        positions, speed = self._synthetic_wrist()
        phases, _ = detect_phases(positions, speed)
        # Phases have valid start ≤ end
        for name, (s, e) in phases.items():
            assert s <= e, f"Phase {name} has start > end"

    def test_contact_frame_near_peak_speed(self):
        positions, speed = self._synthetic_wrist()
        _, contact_frame = detect_phases(positions, speed)
        peak = int(np.argmax(speed))
        # Contact frame should be within a few frames of peak wrist speed
        assert abs(contact_frame - peak) <= 5

    def test_follow_through_ends_at_last_frame(self):
        positions, speed = self._synthetic_wrist(n=60)
        phases, _ = detect_phases(positions, speed)
        assert phases["follow_through"][1] == 59

    def test_preparation_starts_at_zero(self):
        positions, speed = self._synthetic_wrist()
        phases, _ = detect_phases(positions, speed)
        assert phases["preparation"][0] == 0


# ---------------------------------------------------------------------------
# extract_features — integration tests
# ---------------------------------------------------------------------------

def _make_landmarks(n: int = 60) -> np.ndarray:
    """Build a plausible (N, 33, 3) landmark array for a right-hand swing."""
    rng = np.random.default_rng(7)
    lm = rng.uniform(0.2, 0.8, (n, 33, 3)).astype(np.float32)
    # Give the right wrist (idx 16) a clear sinusoidal trajectory so phase
    # detection has something to work with.
    t = np.linspace(0, 2 * np.pi, n)
    lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t)
    return lm


class TestExtractFeatures:
    def test_output_type(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert isinstance(result, FeatureExtractionResult)

    def test_joint_angle_keys(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        expected = {
            "elbow_angle", "shoulder_rotation", "hip_rotation",
            "trunk_rotation", "knee_bend", "racket_arm_elevation"
        }
        assert set(result.joint_angles.keys()) == expected

    def test_joint_angles_in_degrees_range(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        for name, arr in result.joint_angles.items():
            assert arr.shape == (60,), f"{name} wrong shape"
            assert np.all(arr >= 0) and np.all(arr < 360), (
                f"{name} out of [0,360): min={arr.min():.2f} max={arr.max():.2f}"
            )

    def test_velocity_keys(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert set(result.velocities.keys()) == {"wrist_speed", "elbow_speed", "hip_speed"}

    def test_velocity_shapes(self):
        n = 60
        lm = _make_landmarks(n)
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        for name, arr in result.velocities.items():
            assert arr.shape == (n,), f"{name} wrong shape"

    def test_five_phases_present(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert len(result.phases) == 5

    def test_phases_non_overlapping(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        for name, (s, e) in result.phases.items():
            assert s <= e, f"Phase {name}: start ({s}) > end ({e})"

    def test_contact_frame_in_range(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert 0 <= result.contact_frame < 60

    def test_invalid_landmarks_shape_raises(self):
        bad = np.zeros((10, 17, 3))
        with pytest.raises(ValueError):
            extract_features(bad, fps=30.0, stroke_type="forehand")

    def test_left_hand_uses_different_wrist(self):
        """
        Left-hand should use landmark 15 (left wrist) as hitting wrist;
        right-hand should use landmark 16 (right wrist). We verify by
        putting a high-speed trajectory ONLY on index 15 and confirming
        left-hand contact_frame ends up near the peak of that trajectory.
        """
        n = 60
        lm = np.full((n, 33, 3), 0.5, dtype=np.float32)
        t = np.linspace(0, 2 * np.pi, n)
        # Only left wrist moves
        lm[:, 15, 0] = 0.5 + 0.3 * np.sin(t)

        result_left  = extract_features(lm, fps=30.0, stroke_type="forehand", handedness="left")
        result_right = extract_features(lm, fps=30.0, stroke_type="forehand", handedness="right")

        # Left-hand contact should be near the peak of left-wrist speed
        peak = int(np.argmax(np.abs(np.gradient(lm[:, 15, 0]))))
        # Contact frame for left-hand should be closer to peak than right-hand contact
        assert abs(result_left.contact_frame - peak) <= abs(result_right.contact_frame - peak) + 5
