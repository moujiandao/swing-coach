"""
Tests for app/worker/angle_utils.py — geometric utility functions.
"""
import numpy as np
import pytest

from app.worker.angle_utils import angular_velocity, compute_angle_3pt, compute_segment_angle


# ---------------------------------------------------------------------------
# compute_angle_3pt
# ---------------------------------------------------------------------------

class TestComputeAngle3pt:
    def test_right_angle(self):
        """90-degree angle at the origin."""
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 0.0])
        c = np.array([0.0, 1.0])
        assert abs(compute_angle_3pt(a, b, c) - 90.0) < 0.1

    def test_straight_line(self):
        """180-degree angle (collinear points)."""
        a = np.array([-1.0, 0.0])
        b = np.array([0.0, 0.0])
        c = np.array([1.0, 0.0])
        assert abs(compute_angle_3pt(a, b, c) - 180.0) < 0.1

    def test_acute_angle_60(self):
        """Equilateral triangle vertex = 60 degrees."""
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 0.0])
        c = np.array([0.5, np.sqrt(3) / 2])
        assert abs(compute_angle_3pt(a, b, c) - 60.0) < 0.1

    def test_zero_angle_coincident(self):
        """Coincident points return 0."""
        p = np.array([1.0, 1.0])
        assert compute_angle_3pt(p, p, p) == 0.0

    def test_3d_points(self):
        """Works with 3D coordinates."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([0.0, 1.0, 0.0])
        assert abs(compute_angle_3pt(a, b, c) - 90.0) < 0.1

    def test_3d_diagonal(self):
        """3D angle using all three dimensions."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([0.0, 0.0, 1.0])
        assert abs(compute_angle_3pt(a, b, c) - 90.0) < 0.1

    def test_obtuse_angle(self):
        """Obtuse angle (~120 degrees)."""
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 0.0])
        c = np.array([-0.5, np.sqrt(3) / 2])
        assert abs(compute_angle_3pt(a, b, c) - 120.0) < 0.1

    def test_result_range_0_180(self):
        """Result is always in [0, 180]."""
        rng = np.random.default_rng(42)
        for _ in range(50):
            pts = rng.uniform(-10, 10, (3, 2))
            angle = compute_angle_3pt(pts[0], pts[1], pts[2])
            assert 0.0 <= angle <= 180.0


# ---------------------------------------------------------------------------
# compute_segment_angle
# ---------------------------------------------------------------------------

class TestComputeSegmentAngle:
    def test_horizontal_right(self):
        """Segment pointing right = 0 degrees."""
        assert abs(compute_segment_angle(np.array([0, 0]), np.array([1, 0])) - 0.0) < 0.1

    def test_vertical_up(self):
        """Segment pointing up = 90 degrees."""
        assert abs(compute_segment_angle(np.array([0, 0]), np.array([0, 1])) - 90.0) < 0.1

    def test_horizontal_left(self):
        """Segment pointing left = 180 degrees."""
        assert abs(compute_segment_angle(np.array([0, 0]), np.array([-1, 0])) - 180.0) < 0.1

    def test_diagonal_45(self):
        """45-degree diagonal."""
        assert abs(compute_segment_angle(np.array([0, 0]), np.array([1, 1])) - 45.0) < 0.1

    def test_result_in_0_360(self):
        """Result is always in [0, 360)."""
        rng = np.random.default_rng(7)
        for _ in range(50):
            pts = rng.uniform(-10, 10, (2, 2))
            angle = compute_segment_angle(pts[0], pts[1])
            assert 0.0 <= angle < 360.0

    def test_270_degrees(self):
        """Segment pointing down = 270 degrees."""
        assert abs(compute_segment_angle(np.array([0, 0]), np.array([0, -1])) - 270.0) < 0.1


# ---------------------------------------------------------------------------
# angular_velocity
# ---------------------------------------------------------------------------

class TestAngularVelocity:
    def test_constant_angle_zero_velocity(self):
        """Constant angle series has zero angular velocity."""
        angles = [90.0] * 10
        vel = angular_velocity(angles, fps=30.0)
        assert len(vel) == 10
        for v in vel:
            assert abs(v) < 1e-6

    def test_linear_ramp(self):
        """Linearly increasing angles produce constant velocity."""
        # 10 frames, 0 to 90 degrees, at 30 fps
        angles = np.linspace(0, 90, 10).tolist()
        vel = angular_velocity(angles, fps=30.0)
        assert len(vel) == 10
        # Interior points should all be ~same velocity
        # 90 degrees over 9 intervals at 30fps = 90 / (9/30) = 300 deg/sec
        expected = 90.0 / (9.0 / 30.0)
        for v in vel[1:-1]:  # skip edges (forward/backward diff)
            assert abs(v - expected) < 1.0

    def test_single_frame(self):
        """Single frame returns [0.0]."""
        assert angular_velocity([45.0], fps=30.0) == [0.0]

    def test_two_frames(self):
        """Two frames: velocity = (angle_diff) * fps."""
        vel = angular_velocity([0.0, 30.0], fps=10.0)
        assert len(vel) == 2
        # Both should be ~300 deg/sec (30 deg in 0.1 sec)
        assert abs(vel[0] - 300.0) < 1.0
        assert abs(vel[1] - 300.0) < 1.0

    def test_numpy_input(self):
        """Accepts numpy array input."""
        arr = np.array([0.0, 45.0, 90.0])
        vel = angular_velocity(arr, fps=30.0)
        assert len(vel) == 3
        assert all(isinstance(v, float) for v in vel)
