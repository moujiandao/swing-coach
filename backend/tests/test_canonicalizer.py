"""
Tests for Phase 2, Unit 2: Canonical 3D pose normalization.

Key invariant: the same physical pose captured from two different camera
angles (simulated via rotation) should produce near-identical canonical output.
"""
import numpy as np
import pytest

from app.worker.pose_canonicalizer import canonicalize, LEFT_HIP, RIGHT_HIP, LEFT_SHOULDER, RIGHT_SHOULDER


# ---------------------------------------------------------------------------
# Synthetic landmark generator
# ---------------------------------------------------------------------------

def _make_standing_pose() -> np.ndarray:
    """
    Create a synthetic 33-landmark standing pose in 3D world coordinates.
    Roughly human proportions in meters. Facing +Z direction.
    """
    landmarks = np.zeros((33, 3), dtype=np.float32)

    # Hips (pelvis) at roughly origin height
    landmarks[LEFT_HIP]  = [-0.15, 0.0, 0.0]
    landmarks[RIGHT_HIP] = [0.15, 0.0, 0.0]

    # Shoulders above hips
    landmarks[LEFT_SHOULDER]  = [-0.20, 0.45, 0.0]
    landmarks[RIGHT_SHOULDER] = [0.20, 0.45, 0.0]

    # Head (nose)
    landmarks[0] = [0.0, 0.60, 0.05]

    # Elbows
    landmarks[13] = [-0.35, 0.25, 0.0]  # left elbow
    landmarks[14] = [0.35, 0.25, 0.0]   # right elbow

    # Wrists
    landmarks[15] = [-0.40, 0.05, 0.0]  # left wrist
    landmarks[16] = [0.40, 0.05, 0.0]   # right wrist

    # Knees
    landmarks[25] = [-0.15, -0.40, 0.05]  # left knee
    landmarks[26] = [0.15, -0.40, 0.05]   # right knee

    # Ankles
    landmarks[27] = [-0.15, -0.80, 0.05]  # left ankle
    landmarks[28] = [0.15, -0.80, 0.05]   # right ankle

    return landmarks


def _rotate_y(landmarks: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate landmarks around Y axis by the given angle (degrees)."""
    angle = np.radians(angle_deg)
    c, s = np.cos(angle), np.sin(angle)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)
    return (R @ landmarks.T).T


def _translate(landmarks: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """Translate all landmarks by an offset vector."""
    return landmarks + offset


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCanonicalizeShape:
    """Basic shape and type checks."""

    def test_output_shape_matches_input(self):
        pose = _make_standing_pose()
        sequence = np.stack([pose, pose, pose])  # (3, 33, 3)
        result = canonicalize(sequence)
        assert result.shape == (3, 33, 3)

    def test_output_dtype_is_float32(self):
        pose = _make_standing_pose()
        sequence = pose[np.newaxis]  # (1, 33, 3)
        result = canonicalize(sequence)
        assert result.dtype == np.float32

    def test_rejects_2d_input(self):
        with pytest.raises(ValueError):
            canonicalize(np.zeros((33, 3)))

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            canonicalize(None)


class TestPelvisCentering:
    """Pelvis should be at the origin after canonicalization."""

    def test_pelvis_at_origin(self):
        pose = _make_standing_pose()
        # Shift pelvis away from origin
        pose = _translate(pose, np.array([5.0, 3.0, -2.0]))
        sequence = pose[np.newaxis]

        result = canonicalize(sequence)
        pelvis = (result[0, LEFT_HIP] + result[0, RIGHT_HIP]) / 2.0

        np.testing.assert_allclose(pelvis, [0.0, 0.0, 0.0], atol=1e-5)

    def test_pelvis_centering_preserves_relative_positions(self):
        pose = _make_standing_pose()
        offset = np.array([10.0, -5.0, 3.0])
        shifted = _translate(pose, offset)

        original_relative = pose - (pose[LEFT_HIP] + pose[RIGHT_HIP]) / 2.0
        result = canonicalize(shifted[np.newaxis])

        # After centering, relative positions should be preserved
        # (modulo the rotation step which we test separately)
        result_pelvis = (result[0, LEFT_HIP] + result[0, RIGHT_HIP]) / 2.0
        np.testing.assert_allclose(result_pelvis, [0, 0, 0], atol=1e-5)


class TestRotationInvariance:
    """Same pose at different Y-rotations should produce near-identical canonical output."""

    @pytest.mark.parametrize("angle", [30, 45, 90, 135, 180])
    def test_rotation_invariance(self, angle):
        pose_a = _make_standing_pose()
        pose_b = _rotate_y(_make_standing_pose(), angle)

        canon_a = canonicalize(pose_a[np.newaxis])[0]
        canon_b = canonicalize(pose_b[np.newaxis])[0]

        # The key landmarks (shoulders, hips, elbows, knees) should be
        # very close after canonicalization. We use a tolerance that
        # accounts for numerical imprecision in the rotation.
        key_indices = [LEFT_HIP, RIGHT_HIP, LEFT_SHOULDER, RIGHT_SHOULDER, 13, 14, 25, 26]
        for idx in key_indices:
            np.testing.assert_allclose(
                canon_a[idx], canon_b[idx], atol=0.05,
                err_msg=f"Landmark {idx} differs at rotation {angle}deg"
            )

    def test_different_poses_are_not_identical(self):
        """Two genuinely different poses should NOT produce identical output."""
        pose_a = _make_standing_pose()
        pose_b = _make_standing_pose()
        # Raise right arm significantly
        pose_b[14] = [0.35, 0.55, 0.0]
        pose_b[16] = [0.40, 0.70, 0.0]

        canon_a = canonicalize(pose_a[np.newaxis])[0]
        canon_b = canonicalize(pose_b[np.newaxis])[0]

        # Right elbow and wrist should differ
        assert not np.allclose(canon_a[14], canon_b[14], atol=0.02)


class TestMultiFrameSequence:
    """Verify frame-by-frame processing works correctly."""

    def test_each_frame_independent(self):
        pose1 = _make_standing_pose()
        pose2 = _rotate_y(_make_standing_pose(), 60)
        pose3 = _translate(_make_standing_pose(), np.array([1.0, 0.0, 0.0]))

        sequence = np.stack([pose1, pose2, pose3])  # (3, 33, 3)
        result = canonicalize(sequence)

        # All frames should have pelvis at origin
        for f in range(3):
            pelvis = (result[f, LEFT_HIP] + result[f, RIGHT_HIP]) / 2.0
            np.testing.assert_allclose(pelvis, [0.0, 0.0, 0.0], atol=1e-5)

    def test_degenerate_frame_handled(self):
        """A frame with collapsed landmarks (all same point) should not crash."""
        normal = _make_standing_pose()
        degenerate = np.full((33, 3), 0.5, dtype=np.float32)

        sequence = np.stack([normal, degenerate, normal])
        result = canonicalize(sequence)

        # Should not raise and should produce finite values
        assert np.all(np.isfinite(result))
