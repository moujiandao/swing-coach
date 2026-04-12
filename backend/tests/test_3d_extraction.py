"""
Tests for Phase 2, Unit 1: 3D world_landmarks extraction.

Verifies that PoseEstimationResult includes world_landmarks (3D real-world
coordinates) alongside the existing 2D normalized landmarks.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.worker.pose_estimator import (
    N_LANDMARKS,
    PoseEstimationResult,
    extract_poses,
)


# ---------------------------------------------------------------------------
# Helpers — mirrors test_pose_estimator.py mock pattern
# ---------------------------------------------------------------------------

def _fake_landmark(x=0.5, y=0.5, z=0.0, visibility=0.9):
    lm = MagicMock()
    lm.x = x
    lm.y = y
    lm.z = z
    lm.visibility = visibility
    return lm


def _make_pose_result(has_pose: bool = True, has_world: bool = True) -> MagicMock:
    """Return a mock PoseLandmarkerResult with optional world landmarks."""
    result = MagicMock()
    if has_pose:
        lms = [_fake_landmark(x=0.5 + (i * 0.001)) for i in range(N_LANDMARKS)]
        result.pose_landmarks = [lms]
        if has_world:
            # World landmarks: meter-scale coords (different range from normalized)
            wlms = [_fake_landmark(x=0.1 * i, y=-0.3 + 0.02 * i, z=0.05 * i)
                     for i in range(N_LANDMARKS)]
            result.pose_world_landmarks = [wlms]
        else:
            result.pose_world_landmarks = []
    else:
        result.pose_landmarks = []
        result.pose_world_landmarks = []
    return result


@contextmanager
def _patched_landmarker(per_frame_results: list[MagicMock]):
    mock_detector = MagicMock()
    mock_detector.detect.side_effect = per_frame_results
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_detector)
    mock_cm.__exit__ = MagicMock(return_value=False)

    blank_bgr = np.ones((240, 320, 3), dtype=np.uint8) * 255

    with (
        patch("app.worker.pose_estimator._ensure_model", return_value="/fake/model.task"),
        patch("app.worker.pose_estimator.cv2.imread", return_value=blank_bgr),
        patch("app.worker.pose_estimator.cv2.cvtColor", return_value=blank_bgr),
        patch("app.worker.pose_estimator.mp.Image"),
        patch(
            "app.worker.pose_estimator._PoseLandmarker.create_from_options",
            return_value=mock_cm,
        ),
    ):
        yield mock_detector


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorldLandmarksPresent:
    """Verify world_landmarks field exists and has correct shape."""

    def test_world_landmarks_shape(self, blank_frame_paths):
        n = len(blank_frame_paths)
        results = [_make_pose_result(has_pose=True, has_world=True)] * n

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths)

        assert result.world_landmarks is not None, "world_landmarks should not be None"
        assert result.world_landmarks.shape == (n, N_LANDMARKS, 3), (
            f"Expected ({n}, {N_LANDMARKS}, 3), got {result.world_landmarks.shape}"
        )

    def test_world_landmarks_have_xyz(self, blank_frame_paths):
        """Each world landmark should have x, y, z coordinates."""
        n = len(blank_frame_paths)
        results = [_make_pose_result(has_pose=True, has_world=True)] * n

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths)

        assert result.world_landmarks is not None
        # Check a single frame/landmark has 3 coords
        single = result.world_landmarks[0, 0]
        assert single.shape == (3,), f"Expected (3,) per landmark, got {single.shape}"
        # Values should be finite
        assert np.all(np.isfinite(result.world_landmarks)), "All world landmark coords should be finite"

    def test_world_landmarks_differ_from_2d(self, blank_frame_paths):
        """World landmarks (meter-scale) should differ from normalized 2D landmarks."""
        n = len(blank_frame_paths)
        results = [_make_pose_result(has_pose=True, has_world=True)] * n

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths)

        assert result.world_landmarks is not None
        # The mock data uses different ranges, so arrays should not be equal
        assert not np.allclose(result.landmarks, result.world_landmarks), (
            "World landmarks should have different values from 2D landmarks"
        )


class TestWorldLandmarksFallback:
    """Verify graceful behavior when world landmarks are unavailable."""

    def test_no_world_landmarks_returns_none(self, blank_frame_paths):
        """When MediaPipe doesn't provide world landmarks, field should be None."""
        n = len(blank_frame_paths)
        results = [_make_pose_result(has_pose=True, has_world=False)] * n

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths)

        assert result.world_landmarks is None, (
            "world_landmarks should be None when not available from MediaPipe"
        )

    def test_2d_landmarks_still_valid_without_world(self, blank_frame_paths):
        """2D landmarks should work normally even without world landmarks."""
        n = len(blank_frame_paths)
        results = [_make_pose_result(has_pose=True, has_world=False)] * n

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths)

        assert result.landmarks.shape == (n, N_LANDMARKS, 3)
        assert result.visibility.shape == (n, N_LANDMARKS)


class TestWorldLandmarksInterpolation:
    """Verify gap-filling works for world landmarks like it does for 2D."""

    def test_interpolation_fills_gaps(self, blank_frame_paths):
        """A missing frame between two detected frames should be interpolated."""
        # 5 frames: detected, missing, detected, detected, detected
        results = [
            _make_pose_result(has_pose=True, has_world=True),
            _make_pose_result(has_pose=False),
            _make_pose_result(has_pose=True, has_world=True),
            _make_pose_result(has_pose=True, has_world=True),
            _make_pose_result(has_pose=True, has_world=True),
        ]

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths[:5])

        assert result.world_landmarks is not None
        # Frame 1 was missing but should be interpolated (not all zeros)
        frame1_3d = result.world_landmarks[1]
        assert not np.allclose(frame1_3d, 0.0), (
            "Interpolated frame should not be all zeros"
        )


class TestWorldLandmarksCoexistence:
    """Verify world_landmarks coexists with all existing fields."""

    def test_all_result_fields_present(self, blank_frame_paths):
        n = len(blank_frame_paths)
        results = [_make_pose_result(has_pose=True, has_world=True)] * n

        with _patched_landmarker(results):
            result = extract_poses(blank_frame_paths)

        assert isinstance(result, PoseEstimationResult)
        assert result.landmarks is not None
        assert result.visibility is not None
        assert result.detection_mask is not None
        assert result.frames_processed == n
        assert result.frames_with_pose == n
        assert result.detection_rate == 1.0
        assert result.world_landmarks is not None
