"""
Process a real pro player video into a reference .npz file.

Usage:
    python scripts/build_pro_references.py \
        --video path/to/video.mp4 \
        --stroke forehand \
        --player federer \
        [--handedness right] \
        [--data-dir backend/app/pro_references/data]

Requires: ffmpeg on PATH, mediapipe model cache (~29MB, auto-downloaded).
"""
import argparse
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

# Allow running from project root
_BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from app.pro_references.loader import save_reference          # noqa: E402
from app.worker.frame_extractor import extract_frames         # noqa: E402
from app.worker.pose_estimator import extract_poses           # noqa: E402
from app.worker.feature_engine import extract_features        # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_reference(
    video_path: str,
    player: str,
    stroke_type: str,
    handedness: str = "right",
    data_dir: str | None = None,
) -> Path:
    """
    End-to-end pipeline: video → .npz reference file.

    Returns the path to the saved file.
    """
    with tempfile.TemporaryDirectory() as frames_dir:
        # 1. Extract frames
        logger.info("Extracting frames from %s …", video_path)
        frame_result = extract_frames(video_path, output_dir=frames_dir)
        frame_paths = frame_result.frame_paths
        fps = frame_result.fps
        logger.info("Extracted %d frames at %.1f fps", len(frame_paths), fps)

        # 2. Pose estimation
        logger.info("Running pose estimation …")
        pose_result = extract_poses(frame_paths)
        logger.info(
            "Detection rate: %.0f%% (%d/%d frames)",
            pose_result.detection_rate * 100,
            pose_result.frames_with_pose,
            pose_result.frames_processed,
        )

        # 3. Feature extraction
        logger.info("Extracting features …")
        features = extract_features(
            landmarks=pose_result.landmarks,
            fps=fps,
            stroke_type=stroke_type,
            handedness=handedness,
        )

    # 4. Save reference
    out_path = save_reference(
        player=player,
        stroke_type=stroke_type,
        joint_angles=features.joint_angles,
        phases=features.phases,
        metadata={
            "fps": fps,
            "handedness": handedness,
            "source": "real_video",
            "contact_frame": features.contact_frame,
        },
        data_dir=data_dir,
    )
    logger.info("Saved reference → %s", out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a pro reference swing .npz from video"
    )
    parser.add_argument("--video",      required=True,  help="Path to input video file")
    parser.add_argument("--player",     required=True,  help="Player name (e.g. federer)")
    parser.add_argument("--stroke",     required=True,  help="Stroke type (e.g. forehand)")
    parser.add_argument("--handedness", default="right", choices=["right", "left"])
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Output directory (default: backend/app/pro_references/data)",
    )
    args = parser.parse_args()

    out = build_reference(
        video_path=args.video,
        player=args.player,
        stroke_type=args.stroke,
        handedness=args.handedness,
        data_dir=args.data_dir,
    )
    print(f"Done → {out}")


if __name__ == "__main__":
    main()
