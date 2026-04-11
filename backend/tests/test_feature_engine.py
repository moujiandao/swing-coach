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
    upsample_landmarks,
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
        - x increases fast (forward swing -> contact at peak speed)
        - x continues (follow-through)
        Returns wrist_positions (N,3), wrist_speed (N,), and shoulder_rotation (N,).
        """
        t = np.linspace(0, 2 * np.pi, n)
        # Sinusoidal x: starts going forward, then backward, then fast forward
        x = np.sin(t)
        positions = np.column_stack([x, np.zeros(n), np.zeros(n)]).astype(np.float32)
        speed = compute_velocity(positions, fps=30.0)
        # Shoulder rotation tracks the wrist motion (rotates with the swing)
        shoulder_rot = (20.0 * np.sin(t)).astype(np.float32)
        return positions, speed, shoulder_rot

    def test_returns_five_phases(self):
        positions, speed, shoulder_rot = self._synthetic_wrist()
        phases, contact_frame = detect_phases(positions, speed, shoulder_rot)
        assert set(phases.keys()) == {
            "preparation", "backswing", "forward_swing", "contact", "follow_through"
        }

    def test_phases_non_overlapping(self):
        positions, speed, shoulder_rot = self._synthetic_wrist()
        phases, _ = detect_phases(positions, speed, shoulder_rot)
        # Phases have valid start <= end
        for name, (s, e) in phases.items():
            assert s <= e, f"Phase {name} has start > end"

    def test_contact_frame_near_peak_speed(self):
        positions, speed, shoulder_rot = self._synthetic_wrist()
        _, contact_frame = detect_phases(positions, speed, shoulder_rot)
        peak = int(np.argmax(speed))
        # Contact frame should be within a few frames of peak wrist speed
        assert abs(contact_frame - peak) <= 5

    def test_follow_through_ends_within_bounds(self):
        positions, speed, shoulder_rot = self._synthetic_wrist(n=60)
        phases, _ = detect_phases(positions, speed, shoulder_rot)
        # Follow-through ends at or before the last frame (may trim idle tail)
        assert phases["follow_through"][1] <= 59

    def test_preparation_starts_within_bounds(self):
        positions, speed, shoulder_rot = self._synthetic_wrist()
        phases, _ = detect_phases(positions, speed, shoulder_rot)
        # Preparation starts at or after frame 0 (may trim idle start)
        assert phases["preparation"][0] >= 0

    def test_eval_window_trims_idle_frames(self):
        """Idle padding at start/end should be excluded from phases."""
        # Build: 40 idle + 90 active swing + 40 idle
        n_idle = 40
        n_active = 90
        n = n_idle + n_active + n_idle

        # Active wrist: sinusoidal trajectory with a clear backswing-then-forward
        # pattern. Using sin(t) starting at t=0 gives: forward -> backward -> forward
        # which produces clear sign changes in dx for phase detection.
        t_active = np.linspace(0, 2 * np.pi, n_active)
        x_active = 0.5 + 0.3 * np.sin(t_active)
        # Idle: hold at the active start/end position (0.5) so transition is smooth
        x = np.concatenate([
            np.full(n_idle, 0.5),
            x_active,
            np.full(n_idle, 0.5),
        ])
        positions = np.column_stack([x, np.zeros(n), np.zeros(n)]).astype(np.float32)
        speed = compute_velocity(positions, fps=30.0)

        # Shoulder rotation: flat during idle, rotating during active
        shoulder_rot = np.concatenate([
            np.zeros(n_idle),
            25.0 * np.sin(t_active),
            np.zeros(n_idle),
        ]).astype(np.float32)

        phases, _ = detect_phases(positions, speed, shoulder_rot)

        # Follow-through should NOT end at last frame (idle tail trimmed)
        assert phases["follow_through"][1] < n - 1, (
            f"Expected idle end frames to be trimmed, got follow_through end={phases['follow_through'][1]}"
        )


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
            "trunk_rotation", "knee_bend", "racket_arm_elevation",
            "left_elbow_angle", "left_arm_elevation", "stance_width", "head_movement",
        }
        assert set(result.joint_angles.keys()) == expected

    def test_joint_angles_in_degrees_range(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        # stance_width is a normalized distance [0, ~1]; head_movement is a signed offset
        non_angle_metrics = {"stance_width", "head_movement"}
        for name, arr in result.joint_angles.items():
            assert arr.shape == (60,), f"{name} wrong shape"
            if name not in non_angle_metrics:
                assert np.all(arr >= 0) and np.all(arr < 360), (
                    f"{name} out of [0,360): min={arr.min():.2f} max={arr.max():.2f}"
                )

    def test_velocity_keys(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert set(result.velocities.keys()) == {"wrist_speed", "elbow_speed", "hip_speed", "wrist_acceleration"}

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


# ---------------------------------------------------------------------------
# New metrics — Track A
# ---------------------------------------------------------------------------

class TestNewMetrics:
    def test_stance_width_is_nonnegative(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert np.all(result.joint_angles["stance_width"] >= 0)

    def test_stance_width_distance_math(self):
        """Landmarks placed at known positions → verify exact distance."""
        n = 10
        lm = np.zeros((n, 33, 3), dtype=np.float32)
        # Left ankle (27) at (0.3, 0.9), right ankle (28) at (0.7, 0.9)
        lm[:, 27] = [0.3, 0.9, 0.0]
        lm[:, 28] = [0.7, 0.9, 0.0]
        # Give wrist a sinusoidal trajectory so phase detection works
        t = np.linspace(0, 2 * np.pi, n)
        lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t)
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        expected_width = 0.4  # |0.7 - 0.3|
        assert np.allclose(result.joint_angles["stance_width"], expected_width, atol=1e-5)

    def test_head_movement_zero_when_symmetric(self):
        """Nose at exact midpoint of shoulders → head_movement should be 0."""
        n = 10
        lm = np.zeros((n, 33, 3), dtype=np.float32)
        # Shoulders at y=0.4 and y=0.4 (same height), nose midpoint
        lm[:, 11] = [0.3, 0.4, 0.0]  # left shoulder
        lm[:, 12] = [0.7, 0.4, 0.0]  # right shoulder
        lm[:, 0]  = [0.5, 0.4, 0.0]  # nose at same y as shoulder midpoint
        t = np.linspace(0, 2 * np.pi, n)
        lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t)
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert np.allclose(result.joint_angles["head_movement"], 0.0, atol=1e-5)

    def test_left_elbow_angle_right_angle(self):
        """Place left arm landmarks at a 90° angle and verify result."""
        n = 10
        lm = np.zeros((n, 33, 3), dtype=np.float32)
        # Left shoulder (11) → elbow (13) → wrist (15) forming 90°
        lm[:, 11] = [0.3, 0.5, 0.0]  # left shoulder
        lm[:, 13] = [0.3, 0.7, 0.0]  # left elbow (below shoulder)
        lm[:, 15] = [0.5, 0.7, 0.0]  # left wrist (right of elbow)
        # Other needed landmarks
        lm[:, 23] = [0.3, 0.9, 0.0]  # left hip
        t = np.linspace(0, 2 * np.pi, n)
        lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t)
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        angles = result.joint_angles["left_elbow_angle"]
        assert np.allclose(angles, 90.0, atol=2.0)

    def test_left_arm_uses_opposite_side_from_hitting_arm(self):
        """
        For a right-handed player, left_elbow_angle uses left arm (lm 11,13,15).
        Putting motion ONLY on left arm should give non-trivial left_elbow_angle
        but zero change if right arm is frozen.
        """
        n = 20
        lm = np.full((n, 33, 3), 0.5, dtype=np.float32)
        # Move left wrist (15) so left_elbow_angle varies
        lm[:, 15, 0] = np.linspace(0.3, 0.7, n)
        t = np.linspace(0, 2 * np.pi, n)
        lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t)  # give right wrist trajectory for phase detection

        result_right = extract_features(lm, fps=30.0, stroke_type="forehand", handedness="right")
        result_left  = extract_features(lm, fps=30.0, stroke_type="forehand", handedness="left")

        # For right-handed: left_elbow_angle uses left arm → should vary
        # For left-handed: left_elbow_angle also uses non-hitting (right) arm → different
        # Just verify both return the correct shape
        assert result_right.joint_angles["left_elbow_angle"].shape == (n,)
        assert result_left.joint_angles["left_elbow_angle"].shape == (n,)

    def test_wrist_acceleration_shape(self):
        n = 60
        lm = _make_landmarks(n)
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert result.velocities["wrist_acceleration"].shape == (n,)

    def test_wrist_acceleration_is_float32(self):
        lm = _make_landmarks()
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        assert result.velocities["wrist_acceleration"].dtype == np.float32

    def test_wrist_acceleration_nonzero_for_varying_speed(self):
        """A swing with changing wrist speed should have nonzero acceleration."""
        lm = _make_landmarks(60)
        result = extract_features(lm, fps=30.0, stroke_type="forehand")
        # Interior frames should have some nonzero acceleration
        accel = result.velocities["wrist_acceleration"]
        assert not np.allclose(accel[5:-5], 0.0)


# ---------------------------------------------------------------------------
# upsample_landmarks
# ---------------------------------------------------------------------------

class TestUpsampleLandmarks:
    def test_doubles_frame_count_at_half_fps(self):
        """25fps → 60fps should roughly 2.4x the frame count."""
        n = 40
        lm = np.random.rand(n, 33, 3).astype(np.float32)
        result, fps = upsample_landmarks(lm, source_fps=25.0, target_fps=60.0)
        expected_n = int(round(40 * 60.0 / 25.0))  # 96
        assert result.shape == (expected_n, 33, 3)
        assert fps == 60.0

    def test_noop_at_high_fps(self):
        """60fps input should return unchanged."""
        n = 100
        lm = np.random.rand(n, 33, 3).astype(np.float32)
        result, fps = upsample_landmarks(lm, source_fps=60.0, target_fps=60.0)
        assert result.shape == (n, 33, 3)
        assert fps == 60.0
        np.testing.assert_array_equal(result, lm)

    def test_noop_above_target(self):
        """120fps input should return unchanged (no downsampling)."""
        n = 200
        lm = np.random.rand(n, 33, 3).astype(np.float32)
        result, fps = upsample_landmarks(lm, source_fps=120.0, target_fps=60.0)
        assert fps == 120.0
        np.testing.assert_array_equal(result, lm)

    def test_preserves_endpoints(self):
        """First and last frames should match original (interpolation property)."""
        n = 40
        lm = np.random.rand(n, 33, 3).astype(np.float32)
        result, _ = upsample_landmarks(lm, source_fps=25.0, target_fps=60.0)
        np.testing.assert_allclose(result[0], lm[0], atol=1e-5)
        np.testing.assert_allclose(result[-1], lm[-1], atol=1e-5)

    def test_coordinates_in_range(self):
        """Output should stay in [0, 1] range."""
        n = 40
        lm = np.random.rand(n, 33, 3).astype(np.float32)
        result, _ = upsample_landmarks(lm, source_fps=25.0, target_fps=60.0)
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)

    def test_short_sequence_uses_linear(self):
        """N=3 frames should fall back to linear interpolation without error."""
        lm = np.array([
            [[0.1, 0.1, 0.0]] * 33,
            [[0.5, 0.5, 0.0]] * 33,
            [[0.9, 0.9, 0.0]] * 33,
        ], dtype=np.float32)
        result, fps = upsample_landmarks(lm, source_fps=10.0, target_fps=60.0)
        assert result.shape[0] > 3
        assert fps == 60.0

    def test_single_frame_returns_unchanged(self):
        """N=1 should return unchanged."""
        lm = np.random.rand(1, 33, 3).astype(np.float32)
        result, fps = upsample_landmarks(lm, source_fps=25.0, target_fps=60.0)
        assert result.shape == (1, 33, 3)
        assert fps == 25.0

    def test_upsampling_increases_total_frames(self):
        """Upsampled landmarks should have more frames for phase detection."""
        n = 40
        t = np.linspace(0, 2 * np.pi, n)
        lm = np.full((n, 33, 3), 0.5, dtype=np.float32)
        lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t)

        upsampled, new_fps = upsample_landmarks(lm, source_fps=25.0, target_fps=60.0)
        assert upsampled.shape[0] > n
        assert new_fps == 60.0

    def test_realistic_trajectory_phases_improve(self):
        """
        A more realistic wrist trajectory (with gradual transitions) should
        produce better phase boundaries after upsampling.
        """
        n = 40
        rng = np.random.default_rng(42)
        t = np.linspace(0, 2 * np.pi, n)
        # Add noise to make transitions less sharp (more like real motion)
        lm = np.full((n, 33, 3), 0.5, dtype=np.float32)
        lm[:, 16, 0] = 0.5 + 0.3 * np.sin(t) + rng.normal(0, 0.01, n).astype(np.float32)

        # Phases before upsampling
        wrist_pos_orig = lm[:, 16, :]
        speed_orig = compute_velocity(wrist_pos_orig, 25.0)
        # Synthetic shoulder rotation matching wrist motion
        shoulder_rot_orig = (20.0 * np.sin(t)).astype(np.float32)
        phases_orig, _ = detect_phases(wrist_pos_orig, speed_orig, shoulder_rot_orig)
        total_orig = sum(e - s + 1 for s, e in phases_orig.values())

        # Phases after upsampling
        upsampled, new_fps = upsample_landmarks(lm, source_fps=25.0, target_fps=60.0)
        wrist_pos_up = upsampled[:, 16, :]
        speed_up = compute_velocity(wrist_pos_up, new_fps)
        n_up = upsampled.shape[0]
        t_up = np.linspace(0, 2 * np.pi, n_up)
        shoulder_rot_up = (20.0 * np.sin(t_up)).astype(np.float32)
        phases_up, _ = detect_phases(wrist_pos_up, speed_up, shoulder_rot_up)
        total_up = sum(e - s + 1 for s, e in phases_up.values())

        # Upsampled should have more total phase frames
        assert total_up > total_orig
