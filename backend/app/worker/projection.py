"""
Orthographic projection from canonical 3D landmarks to 2D.

Phase 2 of the Angle-Invariant Swing Analysis Sprint.

Drops the Z coordinate and applies scaling/centering so the resulting 2D
landmarks are in the same [0, 1] normalized range that the frontend expects
from regular MediaPipe 2D landmarks.
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)


def orthographic_project(
    canonical_3d: np.ndarray,
    scale: float = 1.0,
    center: tuple[float, float] = (0.5, 0.5),
) -> np.ndarray:
    """
    Project canonical 3D landmarks to 2D via orthographic projection.

    Args:
        canonical_3d: (num_frames, 33, 3) canonical 3D landmarks (pelvis-centered).
        scale: Scaling factor applied after normalization. Default 1.0 fills
               roughly the [0, 1] range.
        center: (cx, cy) offset so the projected skeleton is centered at this
                point in normalized coordinates. Default (0.5, 0.5) centers it.

    Returns:
        (num_frames, 33, 3) array where:
          - [:, :, 0] = projected x in [0, 1] (roughly)
          - [:, :, 1] = projected y in [0, 1] (roughly)
          - [:, :, 2] = original z (depth) preserved for optional use
    """
    if canonical_3d is None or canonical_3d.ndim != 3:
        raise ValueError("canonical_3d must be a 3D array of shape (frames, 33, 3)")

    num_frames = canonical_3d.shape[0]

    # Extract X and Y from canonical frame.
    # In canonical frame: X = left/right, Y = up/down, Z = facing direction.
    # For orthographic projection we view along Z, keeping X and Y.
    xs = canonical_3d[:, :, 0]  # (frames, 33)
    ys = canonical_3d[:, :, 1]  # (frames, 33)
    zs = canonical_3d[:, :, 2]  # (frames, 33) - preserved

    # Normalize across ALL frames so the skeleton proportions are consistent.
    # Find the global bounding box of all non-zero landmarks.
    all_x = xs.ravel()
    all_y = ys.ravel()

    # Use percentile to be robust against outlier landmarks
    x_range = np.percentile(all_x, 97.5) - np.percentile(all_x, 2.5)
    y_range = np.percentile(all_y, 97.5) - np.percentile(all_y, 2.5)
    max_range = max(x_range, y_range, 1e-6)

    # Scale so the skeleton fits in roughly [-0.4, 0.4] (leaving padding),
    # then shift to center at (cx, cy).
    norm_scale = 0.8 * scale / max_range

    projected = np.zeros_like(canonical_3d)
    projected[:, :, 0] = xs * norm_scale + center[0]
    # Negate Y because screen coordinates have Y increasing downward,
    # but world coordinates have Y increasing upward.
    projected[:, :, 1] = -ys * norm_scale + center[1]
    projected[:, :, 2] = zs  # preserve depth

    return projected
