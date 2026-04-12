"""
Tests for Phase 2, Unit 2: Orthographic projection from canonical 3D to 2D.

Verifies that projected coordinates land in valid ranges and that the
projection preserves relative landmark positions.
"""
import numpy as np
import pytest

from app.worker.projection import orthographic_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_canonical_sequence(num_frames: int = 5) -> np.ndarray:
    """
    Create a synthetic canonical 3D landmark sequence.
    Pelvis at origin, body spans roughly [-0.4, 0.4] in X and [-0.8, 0.6] in Y.
    """
    base = np.zeros((33, 3), dtype=np.float32)
    # Hips symmetric around origin
    base[23] = [-0.15, 0.0, 0.0]   # left hip
    base[24] = [0.15, 0.0, 0.0]    # right hip
    # Shoulders
    base[11] = [-0.20, 0.45, 0.0]  # left shoulder
    base[12] = [0.20, 0.45, 0.0]   # right shoulder
    # Head
    base[0] = [0.0, 0.60, 0.05]
    # Ankles
    base[27] = [-0.15, -0.80, 0.0]
    base[28] = [0.15, -0.80, 0.0]
    # Wrists (arms out to sides)
    base[15] = [-0.40, 0.25, 0.0]
    base[16] = [0.40, 0.25, 0.0]

    sequence = np.stack([base] * num_frames)
    # Add slight variation per frame
    for i in range(num_frames):
        sequence[i, 16, 1] += i * 0.02  # right wrist moves up over time
    return sequence


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProjectionShape:
    """Output shape and type checks."""

    def test_output_shape_matches_input(self):
        seq = _make_canonical_sequence(3)
        result = orthographic_project(seq)
        assert result.shape == (3, 33, 3)

    def test_output_dtype_is_float32(self):
        seq = _make_canonical_sequence(1)
        result = orthographic_project(seq)
        assert result.dtype == np.float32

    def test_rejects_2d_input(self):
        with pytest.raises(ValueError):
            orthographic_project(np.zeros((33, 3)))

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            orthographic_project(None)


class TestProjectionRange:
    """Projected 2D coords should be in a reasonable range near [0, 1]."""

    def test_coords_centered_around_half(self):
        seq = _make_canonical_sequence(5)
        result = orthographic_project(seq)

        xs = result[:, :, 0]
        ys = result[:, :, 1]

        # Mean should be near 0.5 (centered)
        assert 0.3 < np.mean(xs) < 0.7, f"X mean {np.mean(xs):.3f} not near 0.5"
        assert 0.3 < np.mean(ys) < 0.7, f"Y mean {np.mean(ys):.3f} not near 0.5"

    def test_coords_within_bounds(self):
        seq = _make_canonical_sequence(5)
        result = orthographic_project(seq)

        xs = result[:, :, 0]
        ys = result[:, :, 1]

        # Should roughly be in [-0.1, 1.1] (allowing slight overflow from padding)
        assert np.all(xs > -0.5), f"X min {xs.min():.3f} too negative"
        assert np.all(xs < 1.5), f"X max {xs.max():.3f} too large"
        assert np.all(ys > -0.5), f"Y min {ys.min():.3f} too negative"
        assert np.all(ys < 1.5), f"Y max {ys.max():.3f} too large"

    def test_depth_preserved(self):
        """Z coordinate from canonical frame should be preserved in output."""
        seq = _make_canonical_sequence(1)
        seq[0, 0, 2] = 0.123  # set a specific Z value
        result = orthographic_project(seq)
        assert result[0, 0, 2] == pytest.approx(0.123, abs=1e-5)


class TestProjectionRelativePositions:
    """Relative positions should be preserved by the projection."""

    def test_right_shoulder_right_of_left_shoulder(self):
        seq = _make_canonical_sequence(1)
        result = orthographic_project(seq)
        # In canonical frame, right shoulder X > left shoulder X
        # After projection, this should still hold
        assert result[0, 12, 0] > result[0, 11, 0], (
            "Right shoulder should have larger X than left shoulder"
        )

    def test_head_above_hips(self):
        seq = _make_canonical_sequence(1)
        result = orthographic_project(seq)
        # Head Y in world is positive (above pelvis), but screen Y is inverted
        # so head should have smaller Y value (higher on screen)
        head_y = result[0, 0, 1]
        hip_y = (result[0, 23, 1] + result[0, 24, 1]) / 2
        assert head_y < hip_y, "Head should be above hips on screen (smaller Y)"


class TestProjectionScale:
    """Custom scale parameter should affect output range."""

    def test_larger_scale_wider_range(self):
        seq = _make_canonical_sequence(1)
        small = orthographic_project(seq, scale=0.5)
        large = orthographic_project(seq, scale=2.0)

        small_range = small[0, :, 0].max() - small[0, :, 0].min()
        large_range = large[0, :, 0].max() - large[0, :, 0].min()

        assert large_range > small_range, "Larger scale should produce wider X range"

    def test_custom_center(self):
        seq = _make_canonical_sequence(1)
        result = orthographic_project(seq, center=(0.3, 0.7))
        xs = result[0, :, 0]
        ys = result[0, :, 1]
        # Mean should be shifted toward the custom center
        assert 0.1 < np.mean(xs) < 0.5
        assert 0.5 < np.mean(ys) < 0.9
