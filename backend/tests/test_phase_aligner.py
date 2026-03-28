"""
Tests for app/worker/phase_aligner.py

Covers:
- Identical phase lengths → 1:1 mapping
- Different phase lengths → interpolation
- Missing phase handling
- Tempo ratio calculation
- resample_landmarks shape and value validation
"""
import numpy as np
import pytest

from app.worker.phase_aligner import (
    PHASE_ORDER,
    PhaseAlignmentResult,
    PhaseBoundary,
    align_phases,
    resample_landmarks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_phases(frame_count: int) -> dict[str, tuple[int, int]]:
    """Build evenly-divided 5-phase dict for a given frame count."""
    n = frame_count
    boundaries = [
        (0,           n // 5 - 1),
        (n // 5,      2 * n // 5 - 1),
        (2 * n // 5,  3 * n // 5 - 1),
        (3 * n // 5,  3 * n // 5 + 1),           # contact is narrow
        (3 * n // 5 + 2, n - 1),
    ]
    return dict(zip(PHASE_ORDER, boundaries))


# ---------------------------------------------------------------------------
# align_phases — identical lengths
# ---------------------------------------------------------------------------

class TestAlignPhasesIdentical:
    """When user and pro have the same frame count and identical phases the
    mapping must be exactly 1:1 (frame i → frame i)."""

    def test_mapping_is_identity(self):
        phases = _simple_phases(60)
        result = align_phases(phases, phases, 60, 60)
        assert result.frame_mapping == list(range(60))

    def test_total_counts_preserved(self):
        phases = _simple_phases(60)
        result = align_phases(phases, phases, 60, 60)
        assert result.total_user_frames == 60
        assert result.total_pro_frames == 60

    def test_tempo_ratio_is_one(self):
        phases = _simple_phases(60)
        result = align_phases(phases, phases, 60, 60)
        for pb in result.phase_boundaries.values():
            assert abs(pb.tempo_ratio - 1.0) < 1e-6

    def test_all_five_phases_in_boundaries(self):
        phases = _simple_phases(60)
        result = align_phases(phases, phases, 60, 60)
        assert set(result.phase_boundaries.keys()) == set(PHASE_ORDER)


# ---------------------------------------------------------------------------
# align_phases — different lengths (interpolation)
# ---------------------------------------------------------------------------

class TestAlignPhasesDifferentLengths:
    """User has 90 frames, pro has 60.  Each phase is proportionally longer."""

    def setup_method(self):
        self.user_phases = _simple_phases(90)
        self.pro_phases  = _simple_phases(60)
        self.result = align_phases(self.user_phases, self.pro_phases, 90, 60)

    def test_mapping_length_equals_user_frame_count(self):
        assert len(self.result.frame_mapping) == 90

    def test_mapping_values_in_pro_range(self):
        for pro_frame in self.result.frame_mapping:
            assert 0 <= pro_frame < 60

    def test_first_frame_maps_to_pro_first_frame(self):
        # User frame 0 should map to pro frame 0
        assert self.result.frame_mapping[0] == 0

    def test_last_frame_maps_to_pro_last_frame(self):
        # User frame 89 should map to pro frame 59
        assert self.result.frame_mapping[89] == 59

    def test_mapping_is_non_decreasing(self):
        m = self.result.frame_mapping
        for i in range(len(m) - 1):
            assert m[i] <= m[i + 1], f"Mapping decreased at frame {i}: {m[i]} → {m[i+1]}"

    def test_tempo_ratio_approximately_1_5(self):
        # 90 / 60 = 1.5 for proportionally-divided phases.
        # Contact is a fixed narrow window (2 frames each) so its ratio is 1.0;
        # exclude it from this check.
        for name, pb in self.result.phase_boundaries.items():
            if name == "contact":
                continue
            assert abs(pb.tempo_ratio - 1.5) < 0.2, (
                f"{name}: expected tempo_ratio ~1.5, got {pb.tempo_ratio}"
            )

    def test_phase_boundary_user_durations(self):
        for name, pb in self.result.phase_boundaries.items():
            u_start, u_end = self.user_phases[name]
            assert pb.user_duration_frames == u_end - u_start + 1

    def test_phase_boundary_pro_durations(self):
        for name, pb in self.result.phase_boundaries.items():
            p_start, p_end = self.pro_phases[name]
            assert pb.pro_duration_frames == p_end - p_start + 1


# ---------------------------------------------------------------------------
# align_phases — missing phases
# ---------------------------------------------------------------------------

class TestAlignPhasesMissing:
    """Phases absent from either swing should be skipped in boundaries and
    their frames filled by nearest-neighbour from adjacent mapped frames."""

    def test_missing_phase_not_in_boundaries(self):
        user_phases = _simple_phases(60)
        pro_phases  = {k: v for k, v in _simple_phases(60).items() if k != "contact"}
        result = align_phases(user_phases, pro_phases, 60, 60)
        assert "contact" not in result.phase_boundaries

    def test_missing_phase_frames_still_mapped(self):
        """Even if a phase is absent, every user frame gets a valid pro frame."""
        user_phases = _simple_phases(60)
        pro_phases  = {k: v for k, v in _simple_phases(60).items() if k != "backswing"}
        result = align_phases(user_phases, pro_phases, 60, 60)
        assert len(result.frame_mapping) == 60
        for pro_frame in result.frame_mapping:
            assert 0 <= pro_frame < 60

    def test_all_phases_missing_from_pro_fills_with_zero(self):
        """If no shared phases exist, every frame maps to pro frame 0."""
        user_phases = {"preparation": (0, 59)}
        pro_phases  = {"backswing": (0, 29)}  # no overlap in names
        result = align_phases(user_phases, pro_phases, 60, 30)
        assert all(f == 0 for f in result.frame_mapping)

    def test_partial_missing_produces_correct_boundary_count(self):
        user_phases = _simple_phases(60)
        pro_phases  = {k: v for k, v in _simple_phases(60).items()
                       if k in ("backswing", "forward_swing")}
        result = align_phases(user_phases, pro_phases, 60, 60)
        assert len(result.phase_boundaries) == 2


# ---------------------------------------------------------------------------
# align_phases — tempo ratio edge cases
# ---------------------------------------------------------------------------

class TestTempoRatio:
    def test_user_slower_ratio_greater_than_one(self):
        # User phase is 20 frames, pro is 10 → ratio 2.0
        user_phases = {"forward_swing": (0, 19)}
        pro_phases  = {"forward_swing": (0, 9)}
        result = align_phases(user_phases, pro_phases, 20, 10)
        pb = result.phase_boundaries["forward_swing"]
        assert abs(pb.tempo_ratio - 2.0) < 1e-6

    def test_user_faster_ratio_less_than_one(self):
        # User phase is 5 frames, pro is 10 → ratio 0.5
        user_phases = {"forward_swing": (0, 4)}
        pro_phases  = {"forward_swing": (0, 9)}
        result = align_phases(user_phases, pro_phases, 5, 10)
        pb = result.phase_boundaries["forward_swing"]
        assert abs(pb.tempo_ratio - 0.5) < 1e-6

    def test_single_frame_phase_does_not_crash(self):
        user_phases = {"contact": (10, 10)}
        pro_phases  = {"contact": (5, 5)}
        result = align_phases(user_phases, pro_phases, 20, 10)
        assert "contact" in result.phase_boundaries


# ---------------------------------------------------------------------------
# resample_landmarks
# ---------------------------------------------------------------------------

class TestResampleLandmarks:
    def test_output_shape_matches_target(self):
        lm = np.random.rand(30, 33, 3).astype(np.float32)
        out = resample_landmarks(lm, 60)
        assert out.shape == (60, 33, 3)

    def test_downsample_shape(self):
        lm = np.random.rand(90, 33, 3).astype(np.float32)
        out = resample_landmarks(lm, 45)
        assert out.shape == (45, 33, 3)

    def test_same_length_returns_copy(self):
        lm = np.random.rand(30, 33, 3).astype(np.float32)
        out = resample_landmarks(lm, 30)
        assert out.shape == (30, 33, 3)
        np.testing.assert_array_almost_equal(out, lm)

    def test_first_and_last_frames_preserved(self):
        """Endpoint values must be exactly preserved after resampling."""
        lm = np.random.rand(20, 33, 3).astype(np.float32)
        out = resample_landmarks(lm, 40)
        np.testing.assert_array_almost_equal(out[0],  lm[0],  decimal=5)
        np.testing.assert_array_almost_equal(out[-1], lm[-1], decimal=5)

    def test_linear_motion_preserved(self):
        """A landmark moving linearly should stay linear after resampling."""
        n = 10
        lm = np.zeros((n, 33, 3), dtype=np.float32)
        # landmark 0, coordinate 0: goes from 0 to 1 linearly
        lm[:, 0, 0] = np.linspace(0, 1, n)
        out = resample_landmarks(lm, 20)
        expected = np.linspace(0, 1, 20)
        np.testing.assert_array_almost_equal(out[:, 0, 0], expected, decimal=5)

    def test_output_dtype_float32(self):
        lm = np.random.rand(10, 33, 3).astype(np.float32)
        out = resample_landmarks(lm, 15)
        assert out.dtype == np.float32
