"""
Shared pytest fixtures.
"""
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage


@pytest.fixture(scope="session")
def synthetic_video_30fps(tmp_path_factory) -> str:
    """
    3-second, 30fps, 320x240 MP4 using a solid blue lavfi source.
    Created once per test session to avoid repeated ffmpeg invocations.
    """
    out = tmp_path_factory.mktemp("fixtures") / "test_30fps.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "color=c=blue:size=320x240:rate=30",
            "-t", "3",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(out),
            "-y",
        ],
        capture_output=True,
        check=True,
    )
    return str(out)


@pytest.fixture(scope="session")
def synthetic_video_120fps(tmp_path_factory) -> str:
    """
    3-second, 120fps, 320x240 MP4 — simulates slow-motion capture.
    """
    out = tmp_path_factory.mktemp("fixtures") / "test_120fps.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "color=c=red:size=320x240:rate=120",
            "-t", "3",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(out),
            "-y",
        ],
        capture_output=True,
        check=True,
    )
    return str(out)


@pytest.fixture(scope="session")
def synthetic_video_too_long(tmp_path_factory) -> str:
    """
    35-second video — exceeds the default 30s MAX_VIDEO_DURATION_SECONDS limit.
    """
    out = tmp_path_factory.mktemp("fixtures") / "test_too_long.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "color=c=green:size=320x240:rate=10",
            "-t", "35",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(out),
            "-y",
        ],
        capture_output=True,
        check=True,
    )
    return str(out)


@pytest.fixture(scope="session")
def blank_frame_paths(tmp_path_factory) -> list[str]:
    """
    10 solid-white 320x240 PNG files.

    Used by pose estimator tests that need real image files cv2 can open but
    where MediaPipe is mocked — or where we specifically want zero detections
    to trigger the ValueError path.
    """
    d = tmp_path_factory.mktemp("blank_frames")
    white = np.ones((240, 320, 3), dtype=np.uint8) * 255
    paths = []
    for i in range(10):
        p = d / f"frame_{i:05d}.png"
        PILImage.fromarray(white).save(str(p))
        paths.append(str(p))
    return paths
