"""
FFmpeg-based frame extraction for the SwingCoach pipeline.

Stage 1 of the worker pipeline: video → PNG frames.
"""
import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

logger = logging.getLogger(__name__)

# Fail fast at import time if ffmpeg/ffprobe are missing.
if not shutil.which("ffmpeg"):
    raise RuntimeError(
        "ffmpeg is not installed or not on PATH. "
        "Install with: brew install ffmpeg  (macOS) or  apt install ffmpeg  (Linux)"
    )
if not shutil.which("ffprobe"):
    raise RuntimeError(
        "ffprobe is not installed or not on PATH. It is bundled with ffmpeg."
    )


@dataclass
class FrameExtractionResult:
    frame_paths: list[str]   # sorted paths to extracted PNGs
    fps: float               # FPS of extracted frames
    duration_seconds: float  # video duration
    total_frames: int        # number of frames extracted
    resolution: tuple[int, int]  # (width, height) of source video


def _probe_video(video_path: str) -> dict:
    """
    Run ffprobe and return {duration_seconds, fps, width, height}.
    Raises RuntimeError if the file cannot be probed or has no video stream.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {video_path}")

    stream = streams[0]

    # r_frame_rate is the true frame rate (e.g. "30/1", "120/1", "30000/1001").
    fps_str = stream.get("r_frame_rate") or stream.get("avg_frame_rate", "30/1")
    fps = float(Fraction(fps_str))

    # duration: stream-level first, then tag (Matroska stores it as HH:MM:SS.mmm).
    duration_str = stream.get("duration")
    if not duration_str or duration_str == "N/A":
        tags = stream.get("tags", {})
        duration_str = tags.get("DURATION", "0")
        if ":" in duration_str:
            h, m, s = duration_str.split(":")
            duration_seconds = float(h) * 3600 + float(m) * 60 + float(s)
        else:
            duration_seconds = float(duration_str)
    else:
        duration_seconds = float(duration_str)

    return {
        "duration_seconds": duration_seconds,
        "fps": fps,
        "width": int(stream["width"]),
        "height": int(stream["height"]),
    }


def extract_frames(
    video_path: str,
    output_dir: str,
    target_fps: int | None = None,
) -> FrameExtractionResult:
    """
    Extract frames from a video file using FFmpeg.

    Args:
        video_path: Path to the input video file.
        output_dir: Directory to write frame PNGs (created if absent).
        target_fps: If set, downsample to this FPS. If None, native FPS is used
                    except when source > 60fps, where we auto-downsample to 30
                    to keep processing fast.

    Returns:
        FrameExtractionResult with frame_paths, fps, duration_seconds,
        total_frames, and resolution.

    Raises:
        ValueError: video is longer than MAX_VIDEO_DURATION_SECONDS.
        RuntimeError: ffprobe/ffmpeg fails or no video stream found.
    """
    from app.config import get_settings

    settings = get_settings()
    t0 = time.monotonic()

    # --- 1. Probe ---
    probe = _probe_video(video_path)
    source_fps = probe["fps"]
    duration_seconds = probe["duration_seconds"]
    width = probe["width"]
    height = probe["height"]

    logger.info(
        "Probed %s: duration=%.2fs fps=%.2f resolution=%dx%d",
        video_path, duration_seconds, source_fps, width, height,
    )

    # --- 2. Duration guard ---
    if duration_seconds > settings.max_video_duration_seconds:
        raise ValueError(
            f"Video duration {duration_seconds:.1f}s exceeds the "
            f"{settings.max_video_duration_seconds}s limit"
        )

    # --- 3. Resolve output FPS ---
    if target_fps is None:
        if source_fps > 60:
            target_fps = settings.frame_extraction_fps
            logger.info(
                "Source FPS %.2f > 60; downsampling to %d fps", source_fps, target_fps
            )
        else:
            target_fps = int(round(source_fps))

    output_fps = float(target_fps)

    # --- 4. Extract ---
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_pattern = str(Path(output_dir) / "frame_%05d.png")

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"fps={target_fps}",
        "-vsync", "vfr",
        output_pattern,
        "-y",
    ]

    logger.debug("ffmpeg cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg frame extraction failed for {video_path}:\n{result.stderr.strip()}"
        )

    # --- 5. Collect results ---
    frame_paths = sorted(str(p) for p in Path(output_dir).glob("frame_*.png"))
    total_frames = len(frame_paths)

    elapsed = time.monotonic() - t0
    logger.info(
        "Extracted %d frames at %g fps in %.2fs (video=%.2fs)",
        total_frames, output_fps, elapsed, duration_seconds,
    )

    return FrameExtractionResult(
        frame_paths=frame_paths,
        fps=output_fps,
        duration_seconds=duration_seconds,
        total_frames=total_frames,
        resolution=(width, height),
    )
