"""
Generate a synthetic pro reference swing for testing and development.

Creates plausible joint angle curves for a right-hand forehand using
parameterized sine curves that approximate the kinetic chain timing
of a professional forehand (preparation → backswing → contact → follow-through).

Usage:
    python scripts/generate_synthetic_reference.py
    python scripts/generate_synthetic_reference.py --player synthetic --stroke forehand
"""
import argparse
import sys
from pathlib import Path

import numpy as np

# Allow running from project root or scripts/ directory
_BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from app.pro_references.loader import save_reference  # noqa: E402


def _sine_curve(
    n: int,
    start: float,
    end: float,
    phase_shift: float = 0.0,
    amplitude: float = 1.0,
) -> np.ndarray:
    """Smooth sinusoidal transition from start to end angle over n frames."""
    t = np.linspace(0.0, np.pi, n)
    # Sine goes 0 → 1 → 0; shift it to go start → peak → end
    mid = (start + end) / 2.0
    offset = (end - start) / 2.0
    return (mid + amplitude * offset * np.sin(t + phase_shift)).astype(np.float32)


def build_synthetic_forehand(n: int = 60, fps: float = 30.0) -> tuple[dict, dict]:
    """
    Return (joint_angles, phases) for a synthetic right-hand forehand.

    Kinetic chain timing (approximate frame offsets for 60-frame / 2-second clip):
    - Preparation:   frames 0-9    (hips/shoulders square to baseline)
    - Backswing:     frames 10-24  (shoulder rotates back, elbow bends)
    - Forward swing: frames 25-39  (hip leads, shoulder unwinds, elbow extends)
    - Contact:       frames 37-41  (peak wrist speed, arm nearly straight)
    - Follow-through:frames 42-59  (arm crosses body, shoulder rotates through)
    """
    t = np.linspace(0.0, 2.0 * np.pi, n).astype(np.float32)

    # --- elbow_angle ---
    # Starts ~160° (nearly straight), bends to ~90° during backswing,
    # extends to ~170° at contact, then bends again in follow-through.
    elbow = np.piecewise(
        t,
        [t < 0.33 * np.pi, (t >= 0.33 * np.pi) & (t < 0.83 * np.pi),
         (t >= 0.83 * np.pi) & (t < 1.3 * np.pi), t >= 1.3 * np.pi],
        [
            lambda x: np.full_like(x, 160.0),
            lambda x: 160.0 - 70.0 * np.sin((x - 0.33 * np.pi) / 0.5 * np.pi / 2),
            lambda x: 90.0 + 80.0 * np.sin((x - 0.83 * np.pi) / 0.47 * np.pi / 2),
            lambda x: np.full_like(x, 120.0),
        ],
    ).astype(np.float32)

    # --- shoulder_rotation (angle of shoulder line, degrees) ---
    # 90° = square to net, increases (opens) through the swing.
    shoulder_rotation = (90.0 + 40.0 * np.sin(t - 0.3)).astype(np.float32) % 360.0

    # --- hip_rotation ---
    # Hips lead the shoulders by ~0.2 rad (kinetic chain).
    hip_rotation = (88.0 + 42.0 * np.sin(t - 0.1)).astype(np.float32) % 360.0

    # --- trunk_rotation (shoulder - hip) ---
    trunk_rotation = (shoulder_rotation - hip_rotation) % 360.0

    # --- knee_bend ---
    # Front knee bends through backswing, straightens at contact.
    knee_bend = (155.0 + 20.0 * np.sin(t + 0.5)).astype(np.float32)

    # --- racket_arm_elevation ---
    # Upper arm rises during backswing, drops at contact.
    racket_arm_elevation = (80.0 + 30.0 * np.sin(t - 0.4)).astype(np.float32)

    joint_angles = {
        "elbow_angle":           elbow,
        "shoulder_rotation":     shoulder_rotation,
        "hip_rotation":          hip_rotation,
        "trunk_rotation":        trunk_rotation,
        "knee_bend":             knee_bend,
        "racket_arm_elevation":  racket_arm_elevation,
    }

    phases = {
        "preparation":   (0,  9),
        "backswing":     (10, 24),
        "forward_swing": (25, 38),
        "contact":       (37, 41),
        "follow_through":(42, n - 1),
    }

    return joint_angles, phases


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic pro reference swing")
    parser.add_argument("--player",  default="synthetic", help="Player name tag")
    parser.add_argument("--stroke",  default="forehand",  help="Stroke type tag")
    parser.add_argument("--frames",  type=int, default=60, help="Number of frames")
    parser.add_argument("--fps",     type=float, default=30.0, help="Frames per second")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Output directory (default: backend/app/pro_references/data)",
    )
    args = parser.parse_args()

    joint_angles, phases = build_synthetic_forehand(n=args.frames, fps=args.fps)

    out_path = save_reference(
        player=args.player,
        stroke_type=args.stroke,
        joint_angles=joint_angles,
        phases=phases,
        metadata={"fps": args.fps, "source": "synthetic"},
        data_dir=args.data_dir,
    )
    print(f"Saved synthetic reference → {out_path}")


if __name__ == "__main__":
    main()
