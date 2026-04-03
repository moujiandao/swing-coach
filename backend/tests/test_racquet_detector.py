"""
Tests for the YOLO racquet detector module.

Uses mocked YOLO output to avoid requiring the actual model during CI.
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.worker.racquet_detector import (
    RacquetDetection,
    RacquetDetectionResult,
    _bbox_to_centerline,
    _interpolate_detections,
    detect_racquets,
    deserialize_detections,
    serialize_detections,
)


# ---------------------------------------------------------------------------
# _bbox_to_centerline tests
# ---------------------------------------------------------------------------


def test_bbox_to_centerline_vertical_racquet():
    """A tall bbox should produce a vertical center-line."""
    bx, by, tx, ty = _bbox_to_centerline(
        x1=90, y1=10, x2=110, y2=210,
        img_w=200, img_h=300,
    )
    # Width=20, height=200 → vertical long axis
    # Center is (100, 110)
    # base = bottom (closer to player), tip = top
    assert by > ty, "Base should be below tip for vertical racquet"
    assert abs(bx - tx) < 0.01, "X should be nearly the same for vertical"


def test_bbox_to_centerline_horizontal_racquet():
    """A wide bbox should produce a horizontal center-line."""
    bx, by, tx, ty = _bbox_to_centerline(
        x1=10, y1=90, x2=210, y2=110,
        img_w=300, img_h=200,
    )
    # Width=200, height=20 → horizontal long axis
    assert abs(by - ty) < 0.01, "Y should be nearly the same for horizontal"


def test_bbox_to_centerline_with_wrist():
    """When wrist is provided, base should be the end closer to wrist."""
    # Wrist is at normalized (0.5, 0.9) — near the bottom
    bx, by, tx, ty = _bbox_to_centerline(
        x1=40, y1=10, x2=60, y2=190,
        img_w=100, img_h=200,
        wrist_xy=(0.5, 0.9),
    )
    # Bottom end is at y=190/200=0.95, top is at y=10/200=0.05
    # Wrist is at 0.9, so base should be near bottom
    assert by > ty, "Base should be closer to the wrist (bottom)"


def test_bbox_to_centerline_normalized_range():
    """Output coordinates should be in [0, 1] range."""
    bx, by, tx, ty = _bbox_to_centerline(
        x1=10, y1=20, x2=90, y2=180,
        img_w=100, img_h=200,
    )
    for val in [bx, by, tx, ty]:
        assert 0.0 <= val <= 1.0, f"Coordinate {val} outside [0,1] range"


# ---------------------------------------------------------------------------
# _interpolate_detections tests
# ---------------------------------------------------------------------------


def test_interpolate_fills_short_gap():
    """Gaps <= max_gap should be filled by interpolation."""
    d0 = RacquetDetection(0.1, 0.2, 0.3, 0.4, 0.9)
    d4 = RacquetDetection(0.5, 0.6, 0.7, 0.8, 0.8)
    detections = [d0, None, None, None, d4]  # gap of 3

    result = _interpolate_detections(detections, max_gap=5)
    assert result[0] is d0
    assert result[4] is d4
    # Middle frame (index 2) should be halfway between d0 and d4
    mid = result[2]
    assert mid is not None
    assert abs(mid.base_x - 0.3) < 0.01
    assert abs(mid.tip_x - 0.5) < 0.01
    assert mid.confidence == 0.0  # interpolated


def test_interpolate_skips_large_gap():
    """Gaps > max_gap should remain None."""
    d0 = RacquetDetection(0.1, 0.2, 0.3, 0.4, 0.9)
    d7 = RacquetDetection(0.5, 0.6, 0.7, 0.8, 0.8)
    detections = [d0, None, None, None, None, None, None, d7]  # gap of 6

    result = _interpolate_detections(detections, max_gap=3)
    # Frames 1-6 should still be None (gap=6 > max_gap=3)
    for i in range(1, 7):
        assert result[i] is None


def test_interpolate_edge_copy():
    """Leading/trailing None frames should copy nearest detection."""
    d2 = RacquetDetection(0.5, 0.5, 0.5, 0.5, 0.9)
    detections = [None, None, d2, None, None]

    result = _interpolate_detections(detections, max_gap=5)
    # Frames 0 and 1 should copy d2
    assert result[0] is not None
    assert result[0].base_x == d2.base_x
    # Frames 3 and 4 should copy d2
    assert result[3] is not None
    assert result[4] is not None


def test_interpolate_empty_list():
    """Empty input should return empty output."""
    assert _interpolate_detections([]) == []


def test_interpolate_all_none():
    """All-None input should remain all-None."""
    result = _interpolate_detections([None, None, None])
    assert all(d is None for d in result)


# ---------------------------------------------------------------------------
# serialize / deserialize round-trip
# ---------------------------------------------------------------------------


def test_serialize_roundtrip():
    """Serialize → deserialize should preserve data."""
    detections = [
        RacquetDetection(0.1234, 0.2345, 0.3456, 0.4567, 0.891),
        None,
        RacquetDetection(0.5678, 0.6789, 0.7890, 0.8901, 0.950),
    ]
    serialized = serialize_detections(detections)
    assert serialized[1] is None
    assert len(serialized[0]) == 5
    assert len(serialized[2]) == 5

    deserialized = deserialize_detections(serialized)
    assert deserialized[1] is None
    assert abs(deserialized[0].base_x - 0.1234) < 0.001
    assert abs(deserialized[2].confidence - 0.950) < 0.001


def test_serialize_empty():
    assert serialize_detections([]) == []
    assert deserialize_detections([]) == []


# ---------------------------------------------------------------------------
# detect_racquets with mocked YOLO
# ---------------------------------------------------------------------------


def _make_mock_box(cls_id, conf, xyxy):
    """Create a mock YOLO box object matching ultralytics tensor API."""
    box = MagicMock()
    box.cls = [cls_id]
    box.conf = [conf]
    # YOLO returns tensor-like objects with .tolist() method
    xyxy_mock = MagicMock()
    xyxy_mock.tolist.return_value = xyxy
    box.xyxy = [xyxy_mock]
    return box


@patch("app.worker.racquet_detector._load_model")
def test_detect_racquets_with_detections(mock_load, tmp_path):
    """detect_racquets should produce detections when YOLO finds a racquet."""
    # Create minimal test frames (10x10 black images)
    frame_paths = []
    for i in range(5):
        p = tmp_path / f"frame_{i:05d}.png"
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        import cv2
        cv2.imwrite(str(p), img)
        frame_paths.append(str(p))

    # Mock YOLO model
    mock_model = MagicMock()
    mock_load.return_value = mock_model

    # Each frame returns one tennis racket detection (class 38)
    mock_result = MagicMock()
    mock_result.boxes = [_make_mock_box(38, 0.85, [20, 10, 40, 90])]
    mock_model.predict.return_value = [mock_result]

    result = detect_racquets(frame_paths)
    assert isinstance(result, RacquetDetectionResult)
    assert result.detection_rate == 1.0
    assert len(result.detections) == 5
    for d in result.detections:
        assert d is not None
        assert d.confidence == 0.85


@patch("app.worker.racquet_detector._load_model")
def test_detect_racquets_no_detections(mock_load, tmp_path):
    """When YOLO finds no racquets, all detections should be None."""
    frame_paths = []
    for i in range(3):
        p = tmp_path / f"frame_{i:05d}.png"
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        import cv2
        cv2.imwrite(str(p), img)
        frame_paths.append(str(p))

    mock_model = MagicMock()
    mock_load.return_value = mock_model

    mock_result = MagicMock()
    mock_result.boxes = []  # No detections
    mock_model.predict.return_value = [mock_result]

    result = detect_racquets(frame_paths)
    assert result.detection_rate == 0.0
    assert all(d is None for d in result.detections)


@patch("app.worker.racquet_detector._load_model")
def test_detect_racquets_filters_non_racket_classes(mock_load, tmp_path):
    """Only COCO class 38 (tennis racket) should be accepted."""
    frame_paths = []
    for i in range(2):
        p = tmp_path / f"frame_{i:05d}.png"
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        import cv2
        cv2.imwrite(str(p), img)
        frame_paths.append(str(p))

    mock_model = MagicMock()
    mock_load.return_value = mock_model

    # Return a person (class 0) instead of a racquet
    mock_result = MagicMock()
    mock_result.boxes = [_make_mock_box(0, 0.95, [10, 10, 80, 80])]
    mock_model.predict.return_value = [mock_result]

    result = detect_racquets(frame_paths)
    assert result.detection_rate == 0.0


@patch("app.worker.racquet_detector._load_model")
def test_detect_racquets_uses_wrist_landmarks(mock_load, tmp_path):
    """When wrist landmarks are provided, base should be near the wrist."""
    p = tmp_path / "frame_00000.png"
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    import cv2
    cv2.imwrite(str(p), img)

    mock_model = MagicMock()
    mock_load.return_value = mock_model

    # Racquet bbox: tall, centered at (100, 100)
    mock_result = MagicMock()
    mock_result.boxes = [_make_mock_box(38, 0.9, [80, 10, 120, 190])]
    mock_model.predict.return_value = [mock_result]

    # Wrist at bottom of image (normalized 0.5, 0.9)
    wrist_lm = np.array([[0.5, 0.9]], dtype=np.float32)

    result = detect_racquets([str(p)], wrist_landmarks=wrist_lm)
    d = result.detections[0]
    assert d is not None
    # Base should be the end closer to wrist (bottom)
    assert d.base_y > d.tip_y


def test_detect_racquets_empty_input():
    """Empty frame_paths should return empty result."""
    result = detect_racquets([])
    assert result.detection_rate == 0.0
    assert len(result.detections) == 0
