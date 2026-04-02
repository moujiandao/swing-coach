"""
Tests for Task 1.5: MediaPipe pose estimation.

All tests mock the MediaPipe PoseLandmarker so:
  - No model download (~29 MB) is required during CI
  - Tests run in milliseconds
  - Logic (shapes, interpolation, detection rate) is tested deterministically

The ValueError / blank-frames path is also mocked (landmarker returns no poses)
since we're unit-testing the business logic, not the ML model itself.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.worker.pose_estimator import (
    LANDMARK_NAMES,
    N_LANDMARKS,
    PoseEstimationResult,
    _interpolate_missing,
    extract_poses,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_landmark(x=0.5, y=0.5, z=0.0, visibility=0.9):
    lm = MagicMock()
    lm.x = x
    lm.y = y
    lm.z = z
    lm.visibility = visibility
    return lm


def _make_pose_result(has_pose: bool = True) -> MagicMock:
    """Return a mock PoseLandmarkerResult."""
    result = MagicMock()
    if has_pose:
        # Vary x slightly per call so frames aren't identical — aids interpolation tests.
        lms = [_fake_landmark(x=0.5 + (i * 0.001)) for i in range(N_LANDMARKS)]
        result.pose_landmarks = [lms]
    else:
        result.pose_landmarks = []
    return result


@contextmanager
def _patched_landmarker(per_frame_results: list[MagicMock]):
    """
    Patch away everything that touches the filesystem or ML model:
      - _ensure_model      → returns a dummy path string
      - cv2.imread         → returns a 240x320x3 white numpy array
      - mp.Image           → passes through (we only care about .detect())
      - PoseLandmarker.create_from_options → yields a mock whose .detect()
        returns successive entries from per_frame_results
    """
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
# Output shape tests
# ---------------------------------------------------------------------------


def test_landmarks_shape(blank_frame_paths):
    n = len(blank_frame_paths)
    results = [_make_pose_result(has_pose=True)] * n

    with _patched_landmarker(results):
        result = extract_poses(blank_frame_paths)

    assert result.landmarks.shape == (n, N_LANDMARKS, 3), (
        f"Expected ({n}, {N_LANDMARKS}, 3), got {result.landmarks.shape}"
    )


def test_visibility_shape(blank_frame_paths):
    n = len(blank_frame_paths)
    results = [_make_pose_result(has_pose=True)] * n

    with _patched_landmarker(results):
        result = extract_poses(blank_frame_paths)

    assert result.visibility.shape == (n, N_LANDMARKS)


def test_output_is_numpy_not_mediapipe(blank_frame_paths):
    """Landmarks and visibility must be numpy arrays, not mediapipe objects."""
    results = [_make_pose_result(has_pose=True)] * len(blank_frame_paths)

    with _patched_landmarker(results):
        result = extract_poses(blank_frame_paths)

    assert isinstance(result.landmarks, np.ndarray)
    assert isinstance(result.visibility, np.ndarray)


# ---------------------------------------------------------------------------
# Detection rate
# ---------------------------------------------------------------------------


def test_detection_rate_all_frames(blank_frame_paths):
    n = len(blank_frame_paths)
    results = [_make_pose_result(has_pose=True)] * n

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.frames_processed == n
    assert r.frames_with_pose == n
    assert r.detection_rate == pytest.approx(1.0)


def test_detection_rate_partial(blank_frame_paths):
    """6 of 10 frames detected → detection_rate = 0.6, should not raise."""
    n = len(blank_frame_paths)
    results = [_make_pose_result(has_pose=(i < 6)) for i in range(n)]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.frames_with_pose == 6
    assert r.detection_rate == pytest.approx(0.6)
    # Trailing undetected frames (6-9) should be trimmed
    assert r.frames_processed == 6


def test_raises_when_detection_rate_below_threshold(blank_frame_paths):
    """<15% frames with a pose should raise ValueError (configurable threshold)."""
    n = len(blank_frame_paths)
    # Only 1 out of 10 detected → 10%, below default 15% threshold
    results = [_make_pose_result(has_pose=(i < 1)) for i in range(n)]

    with _patched_landmarker(results):
        with pytest.raises(ValueError, match="15%"):
            extract_poses(blank_frame_paths)


def test_raises_when_no_frames_detected(blank_frame_paths):
    """Zero detections should also raise ValueError."""
    results = [_make_pose_result(has_pose=False)] * len(blank_frame_paths)

    with _patched_landmarker(results):
        with pytest.raises(ValueError):
            extract_poses(blank_frame_paths)


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def test_interpolation_fills_gaps():
    """
    Test _interpolate_missing directly: frames 0 and 4 detected, frames 1-3
    should be interpolated between them.
    """
    n_frames = 5

    lm_start = np.zeros((N_LANDMARKS, 3), dtype=np.float32)
    lm_end = np.ones((N_LANDMARKS, 3), dtype=np.float32)
    vis_start = np.zeros(N_LANDMARKS, dtype=np.float32)
    vis_end = np.ones(N_LANDMARKS, dtype=np.float32)

    raw_lm = [lm_start, None, None, None, lm_end]
    raw_vis = [vis_start, None, None, None, vis_end]
    detected = {0, 4}

    out_lm, out_vis = _interpolate_missing(raw_lm, raw_vis, detected, n_frames)

    # Frame 0 and 4 should be exact
    np.testing.assert_array_equal(out_lm[0], lm_start)
    np.testing.assert_array_equal(out_lm[4], lm_end)

    # Frame 2 should be the midpoint (t=0.5)
    expected_mid = 0.5 * lm_start + 0.5 * lm_end
    np.testing.assert_allclose(out_lm[2], expected_mid, atol=1e-6)

    # No NaNs anywhere
    assert not np.any(np.isnan(out_lm))
    assert not np.any(np.isnan(out_vis))


def test_interpolation_edge_copy_before():
    """
    Frames before the first detection should copy the first detected frame.
    """
    n_frames = 5
    lm_known = np.full((N_LANDMARKS, 3), 0.7, dtype=np.float32)
    vis_known = np.full(N_LANDMARKS, 0.8, dtype=np.float32)

    raw_lm = [None, None, lm_known, None, None]
    raw_vis = [None, None, vis_known, None, None]
    detected = {2}

    out_lm, out_vis = _interpolate_missing(raw_lm, raw_vis, detected, n_frames)

    for i in range(5):
        np.testing.assert_allclose(out_lm[i], lm_known, atol=1e-6)


def test_small_gaps_are_interpolated_in_extract(blank_frame_paths):
    """
    After extract_poses with small gaps (1 frame), no frame in landmarks
    should be all-zeros since these gaps are within the max_gap limit.
    """
    n = len(blank_frame_paths)
    # Frames 2 and 5 are missing; rest detected (single-frame gaps)
    results = [
        _make_pose_result(has_pose=(i not in {2, 5})) for i in range(n)
    ]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    for i in range(r.frames_processed):
        assert not np.all(r.landmarks[i] == 0), f"Frame {i} was not interpolated"


# ---------------------------------------------------------------------------
# Landmark map
# ---------------------------------------------------------------------------


def test_landmark_names_covers_all_33():
    assert len(LANDMARK_NAMES) == N_LANDMARKS
    assert set(LANDMARK_NAMES.keys()) == set(range(33))


def test_key_landmarks_present():
    """Spot-check the landmarks the feature engine will use."""
    key_indices = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
    for idx in key_indices:
        assert idx in LANDMARK_NAMES, f"Landmark index {idx} missing from LANDMARK_NAMES"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_raises_on_empty_frame_list():
    with pytest.raises(ValueError, match="empty"):
        extract_poses([])


def test_single_frame_works(blank_frame_paths):
    results = [_make_pose_result(has_pose=True)]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths[:1])

    assert r.landmarks.shape == (1, N_LANDMARKS, 3)
    assert r.detection_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------


def test_trims_leading_undetected_frames(blank_frame_paths):
    """First 3 frames undetected → trimmed, result starts at frame 3."""
    n = len(blank_frame_paths)
    # Frames 0-2 undetected, 3-9 detected
    results = [_make_pose_result(has_pose=(i >= 3)) for i in range(n)]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.frames_processed == 7  # frames 3-9
    assert r.landmarks.shape[0] == 7


def test_trims_trailing_undetected_frames(blank_frame_paths):
    """Last 4 frames undetected → trimmed."""
    n = len(blank_frame_paths)
    # Frames 0-5 detected, 6-9 undetected
    results = [_make_pose_result(has_pose=(i < 6)) for i in range(n)]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.frames_processed == 6  # frames 0-5


def test_trims_both_ends(blank_frame_paths):
    """Leading and trailing undetected frames both trimmed."""
    n = len(blank_frame_paths)
    # Frames 2-7 detected, 0-1 and 8-9 undetected
    results = [_make_pose_result(has_pose=(2 <= i <= 7)) for i in range(n)]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.frames_processed == 6  # frames 2-7
    assert r.frames_with_pose == 6


# ---------------------------------------------------------------------------
# Detection mask
# ---------------------------------------------------------------------------


def test_detection_mask_all_detected(blank_frame_paths):
    results = [_make_pose_result(has_pose=True)] * len(blank_frame_paths)

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.detection_mask.dtype == bool
    assert np.all(r.detection_mask)


def test_detection_mask_partial(blank_frame_paths):
    """Frames 2 and 5 are undetected (within trimmed range)."""
    n = len(blank_frame_paths)
    results = [_make_pose_result(has_pose=(i not in {2, 5})) for i in range(n)]

    with _patched_landmarker(results):
        r = extract_poses(blank_frame_paths)

    assert r.detection_mask[0] == True
    assert r.detection_mask[2] == False
    assert r.detection_mask[5] == False


# ---------------------------------------------------------------------------
# Gap capping
# ---------------------------------------------------------------------------


def test_large_gap_leaves_zeros():
    """Gap of 8 frames (> max_gap=5) should leave landmarks as zeros."""
    n_frames = 12

    lm_start = np.full((N_LANDMARKS, 3), 0.5, dtype=np.float32)
    lm_end = np.full((N_LANDMARKS, 3), 0.8, dtype=np.float32)
    vis_start = np.full(N_LANDMARKS, 0.9, dtype=np.float32)
    vis_end = np.full(N_LANDMARKS, 0.9, dtype=np.float32)

    # Detected at frame 0 and frame 9 (gap of 8 frames in between)
    raw_lm = [lm_start] + [None] * 8 + [lm_end, None, None]
    raw_vis = [vis_start] + [None] * 8 + [vis_end, None, None]
    detected = {0, 9}

    out_lm, out_vis = _interpolate_missing(raw_lm, raw_vis, detected, n_frames, max_gap=5)

    # Frames 1-8 should be zeros (gap too large)
    for i in range(1, 9):
        assert np.all(out_lm[i] == 0), f"Frame {i} should be zeros (large gap)"
        assert np.all(out_vis[i] == 0), f"Frame {i} visibility should be zeros"


def test_small_gap_is_interpolated():
    """Gap of 3 frames (<= max_gap=5) should be interpolated normally."""
    n_frames = 6

    lm_start = np.zeros((N_LANDMARKS, 3), dtype=np.float32)
    lm_end = np.ones((N_LANDMARKS, 3), dtype=np.float32)
    vis_start = np.zeros(N_LANDMARKS, dtype=np.float32)
    vis_end = np.ones(N_LANDMARKS, dtype=np.float32)

    raw_lm = [lm_start, None, None, None, lm_end, None]
    raw_vis = [vis_start, None, None, None, vis_end, None]
    detected = {0, 4}

    out_lm, out_vis = _interpolate_missing(raw_lm, raw_vis, detected, n_frames, max_gap=5)

    # Frame 2 should be midpoint (interpolated)
    expected_mid = 0.5 * lm_start + 0.5 * lm_end
    np.testing.assert_allclose(out_lm[2], expected_mid, atol=1e-6)
