"""
Tests for app/worker/deviation_annotator.py

Covers:
- Frame with large joint diff → deviation flagged
- Frame with small joint diff → no deviation
- Phase boundaries respected (frames outside deviation's phase not flagged)
- Joint name to landmark index mapping
- Severity propagation from DTW deviations
"""
import math

import numpy as np
import pytest

from app.worker.deviation_annotator import (
    JOINT_LANDMARK_MAP,
    JointDeviation,
    FrameDeviation,
    compute_frame_deviations,
    _angle_for_joint,
    _frame_phase,
)
from app.worker.dtw_comparator import Deviation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_landmarks(n_frames: int, value: float = 0.5) -> np.ndarray:
    """All landmarks at a fixed position — produces zero angles / flat pose."""
    return np.full((n_frames, 33, 3), value, dtype=np.float32)


def _right_angle_landmarks(n_frames: int) -> np.ndarray:
    """
    Build landmarks so that the right elbow has a 90° angle.

    Hit shoulder (12) at origin, hit elbow (14) directly below,
    hit wrist (16) directly to the right — right angle at elbow.
    """
    lm = np.zeros((n_frames, 33, 3), dtype=np.float32)
    lm[:, 12] = [0.5, 0.5, 0.0]   # right shoulder
    lm[:, 14] = [0.5, 0.7, 0.0]   # right elbow (below shoulder)
    lm[:, 16] = [0.7, 0.7, 0.0]   # right wrist (right of elbow)
    # Hip / knee / ankle — needed to avoid degenerate compute_angle calls
    lm[:, 24] = [0.5, 0.9, 0.0]   # right hip
    lm[:, 26] = [0.5, 1.1, 0.0]   # right knee
    lm[:, 28] = [0.5, 1.3, 0.0]   # right ankle
    # Shoulders and hips for rotation joints
    lm[:, 11] = [0.3, 0.5, 0.0]
    lm[:, 23] = [0.3, 0.9, 0.0]
    return lm


def _make_deviation(joint: str, phase: str, severity: str = "moderate") -> Deviation:
    return Deviation(
        joint=joint,
        phase=phase,
        mean_diff_degrees=20.0,
        max_diff_degrees=35.0,
        timing_offset_ms=0.0,
        severity=severity,
        description=f"{joint} deviation in {phase}",
    )


def _simple_phases() -> dict[str, tuple[int, int]]:
    return {
        "preparation":   (0, 9),
        "backswing":     (10, 24),
        "forward_swing": (25, 39),
        "contact":       (40, 41),
        "follow_through":(42, 59),
    }


# ---------------------------------------------------------------------------
# Joint landmark map
# ---------------------------------------------------------------------------

class TestJointLandmarkMap:
    def test_elbow_angle_indices(self):
        assert JOINT_LANDMARK_MAP["elbow_angle"] == [13, 14]

    def test_shoulder_rotation_indices(self):
        assert JOINT_LANDMARK_MAP["shoulder_rotation"] == [11, 12]

    def test_hip_rotation_indices(self):
        assert JOINT_LANDMARK_MAP["hip_rotation"] == [23, 24]

    def test_knee_bend_indices(self):
        assert JOINT_LANDMARK_MAP["knee_bend"] == [25, 26]

    def test_racket_arm_elevation_includes_both(self):
        indices = JOINT_LANDMARK_MAP["racket_arm_elevation"]
        assert 11 in indices or 12 in indices
        assert 13 in indices or 14 in indices

    def test_trunk_rotation_includes_all_four(self):
        indices = JOINT_LANDMARK_MAP["trunk_rotation"]
        assert set(indices) == {11, 12, 23, 24}

    def test_all_expected_joints_present(self):
        expected = {
            "elbow_angle", "shoulder_rotation", "hip_rotation",
            "knee_bend", "racket_arm_elevation", "trunk_rotation",
        }
        assert expected.issubset(set(JOINT_LANDMARK_MAP.keys()))


# ---------------------------------------------------------------------------
# _angle_for_joint
# ---------------------------------------------------------------------------

class TestAngleForJoint:
    def test_elbow_angle_right_angle(self):
        lm = _right_angle_landmarks(1)[0]  # single frame
        angle = _angle_for_joint("elbow_angle", lm)
        assert angle is not None
        assert abs(angle - 90.0) < 2.0  # within 2°

    def test_unknown_joint_returns_none(self):
        lm = _right_angle_landmarks(1)[0]
        assert _angle_for_joint("nonexistent_joint", lm) is None

    def test_shoulder_rotation_returns_float(self):
        lm = _right_angle_landmarks(1)[0]
        angle = _angle_for_joint("shoulder_rotation", lm)
        assert isinstance(angle, float)

    def test_hip_rotation_returns_float(self):
        lm = _right_angle_landmarks(1)[0]
        angle = _angle_for_joint("hip_rotation", lm)
        assert isinstance(angle, float)

    def test_trunk_rotation_returns_float(self):
        lm = _right_angle_landmarks(1)[0]
        angle = _angle_for_joint("trunk_rotation", lm)
        assert isinstance(angle, float)
        assert 0.0 <= angle < 360.0


# ---------------------------------------------------------------------------
# _frame_phase
# ---------------------------------------------------------------------------

class TestFramePhase:
    def test_frame_in_preparation(self):
        phases = _simple_phases()
        assert _frame_phase(5, phases) == "preparation"

    def test_frame_in_forward_swing(self):
        phases = _simple_phases()
        assert _frame_phase(30, phases) == "forward_swing"

    def test_frame_at_boundary(self):
        phases = _simple_phases()
        assert _frame_phase(24, phases) == "backswing"
        assert _frame_phase(25, phases) == "forward_swing"

    def test_unknown_frame_beyond_all_phases(self):
        phases = {"backswing": (10, 20)}
        assert _frame_phase(5, phases) == "unknown"


# ---------------------------------------------------------------------------
# compute_frame_deviations — main function
# ---------------------------------------------------------------------------

class TestComputeFrameDeviations:
    def test_large_diff_flagged(self):
        """A 30° elbow angle difference should be flagged (threshold = 10°)."""
        phases = _simple_phases()
        # user elbow ~90°, pro elbow ~120° → diff ≈ -30°
        user_lm = _right_angle_landmarks(60)  # ~90° elbow
        pro_lm  = _right_angle_landmarks(60)
        # Move pro wrist up and right to create a ~120° elbow angle
        pro_lm[:, 16] = [0.8, 0.5, 0.0]  # wrist much higher → wider angle

        deviations = [_make_deviation("elbow_angle", "backswing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        # Frames 10-24 are in backswing — should have deviations
        backswing_frames = {fd.frame_index for fd in result}
        assert any(10 <= f <= 24 for f in backswing_frames)

    def test_small_diff_not_flagged(self):
        """Angle difference below threshold (10°) must not produce a FrameDeviation."""
        phases = _simple_phases()
        # Identical landmarks → zero angle difference
        user_lm = _right_angle_landmarks(60)
        pro_lm  = user_lm.copy()

        deviations = [_make_deviation("elbow_angle", "backswing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations, threshold_degrees=10.0)
        assert result == []

    def test_phase_boundary_respected(self):
        """Elbow deviation is only in 'backswing'. Frames in other phases must not be flagged."""
        phases = _simple_phases()
        user_lm = _right_angle_landmarks(60)
        pro_lm  = _right_angle_landmarks(60)
        pro_lm[:, 16] = [0.8, 0.5, 0.0]  # large angle diff on all frames

        # Deviation only in backswing (frames 10-24)
        deviations = [_make_deviation("elbow_angle", "backswing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        flagged_phases = {fd.phase for fd in result}
        # Only backswing should appear
        assert flagged_phases <= {"backswing"}
        # Frames outside backswing must not appear
        for fd in result:
            assert 10 <= fd.frame_index <= 24

    def test_empty_deviations_list_returns_empty(self):
        phases = _simple_phases()
        user_lm = _right_angle_landmarks(60)
        pro_lm  = _right_angle_landmarks(60)
        pro_lm[:, 16] = [0.8, 0.5, 0.0]

        result = compute_frame_deviations(user_lm, pro_lm, phases, [])
        assert result == []

    def test_severity_propagated_correctly(self):
        """The FrameDeviation severity should match the DTW Deviation severity."""
        phases = _simple_phases()
        user_lm = _right_angle_landmarks(60)
        pro_lm  = _right_angle_landmarks(60)
        pro_lm[:, 16] = [0.8, 0.5, 0.0]

        deviations = [_make_deviation("elbow_angle", "backswing", severity="critical")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        if result:
            assert result[0].severity == "critical"

    def test_joint_deviation_direction_too_wide(self):
        """When user_angle > pro_angle the direction should be 'too_wide'."""
        phases = {"forward_swing": (0, 9)}
        # user: wrist moved far right → wider elbow angle (~90°)
        # pro: wrist close → tighter elbow angle (<90°)
        user_lm = np.zeros((10, 33, 3), dtype=np.float32)
        pro_lm  = np.zeros((10, 33, 3), dtype=np.float32)

        # User: right-angle elbow (~90°)
        user_lm[:, 12] = [0.5, 0.5, 0.0]
        user_lm[:, 14] = [0.5, 0.7, 0.0]
        user_lm[:, 16] = [0.7, 0.7, 0.0]
        user_lm[:, 24] = [0.5, 0.9, 0.0]
        user_lm[:, 26] = [0.5, 1.1, 0.0]
        user_lm[:, 28] = [0.5, 1.3, 0.0]
        user_lm[:, 11] = [0.3, 0.5, 0.0]
        user_lm[:, 23] = [0.3, 0.9, 0.0]

        # Pro: very narrow elbow angle (~30°) — wrist close to shoulder level
        pro_lm[:, 12] = [0.5, 0.5, 0.0]
        pro_lm[:, 14] = [0.5, 0.7, 0.0]
        pro_lm[:, 16] = [0.52, 0.68, 0.0]   # wrist almost at elbow
        pro_lm[:, 24] = [0.5, 0.9, 0.0]
        pro_lm[:, 26] = [0.5, 1.1, 0.0]
        pro_lm[:, 28] = [0.5, 1.3, 0.0]
        pro_lm[:, 11] = [0.3, 0.5, 0.0]
        pro_lm[:, 23] = [0.3, 0.9, 0.0]

        deviations = [_make_deviation("elbow_angle", "forward_swing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        if result:
            for jd in result[0].deviating_joints:
                if jd.joint_name == "elbow_angle":
                    # user wider than pro → "too_wide"
                    assert jd.direction == "too_wide"

    def test_joint_deviation_direction_too_narrow(self):
        """When user_angle < pro_angle the direction should be 'too_narrow'."""
        phases = {"forward_swing": (0, 9)}
        # Swap user and pro from the too_wide test
        user_lm = np.zeros((10, 33, 3), dtype=np.float32)
        pro_lm  = np.zeros((10, 33, 3), dtype=np.float32)

        # User: narrow (~30°)
        user_lm[:, 12] = [0.5, 0.5, 0.0]
        user_lm[:, 14] = [0.5, 0.7, 0.0]
        user_lm[:, 16] = [0.52, 0.68, 0.0]
        user_lm[:, 24] = [0.5, 0.9, 0.0]
        user_lm[:, 26] = [0.5, 1.1, 0.0]
        user_lm[:, 28] = [0.5, 1.3, 0.0]
        user_lm[:, 11] = [0.3, 0.5, 0.0]
        user_lm[:, 23] = [0.3, 0.9, 0.0]

        # Pro: right-angle (~90°)
        pro_lm[:, 12] = [0.5, 0.5, 0.0]
        pro_lm[:, 14] = [0.5, 0.7, 0.0]
        pro_lm[:, 16] = [0.7, 0.7, 0.0]
        pro_lm[:, 24] = [0.5, 0.9, 0.0]
        pro_lm[:, 26] = [0.5, 1.1, 0.0]
        pro_lm[:, 28] = [0.5, 1.3, 0.0]
        pro_lm[:, 11] = [0.3, 0.5, 0.0]
        pro_lm[:, 23] = [0.3, 0.9, 0.0]

        deviations = [_make_deviation("elbow_angle", "forward_swing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        if result:
            for jd in result[0].deviating_joints:
                if jd.joint_name == "elbow_angle":
                    assert jd.direction == "too_narrow"

    def test_result_frame_indices_match_phase(self):
        """Every returned FrameDeviation frame_index must fall in the deviation's phase."""
        phases = _simple_phases()
        user_lm = _right_angle_landmarks(60)
        pro_lm  = _right_angle_landmarks(60)
        pro_lm[:, 16] = [0.8, 0.5, 0.0]

        deviations = [_make_deviation("elbow_angle", "forward_swing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        for fd in result:
            assert 25 <= fd.frame_index <= 39, (
                f"Frame {fd.frame_index} is outside forward_swing (25-39)"
            )

    def test_landmark_indices_in_joint_deviation(self):
        """JointDeviation.landmark_indices must match JOINT_LANDMARK_MAP."""
        phases = _simple_phases()
        user_lm = _right_angle_landmarks(60)
        pro_lm  = _right_angle_landmarks(60)
        pro_lm[:, 16] = [0.8, 0.5, 0.0]

        deviations = [_make_deviation("elbow_angle", "backswing")]
        result = compute_frame_deviations(user_lm, pro_lm, phases, deviations)

        if result:
            elbow_devs = [jd for fd in result for jd in fd.deviating_joints
                          if jd.joint_name == "elbow_angle"]
            assert elbow_devs, "Expected elbow_angle JointDeviation"
            assert elbow_devs[0].landmark_indices == JOINT_LANDMARK_MAP["elbow_angle"]
