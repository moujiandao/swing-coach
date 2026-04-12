"""
Geometric utility functions for angle-invariant swing analysis.

These operate on raw 2D/3D point coordinates and produce angle measurements
in degrees. Used by angle_features.py to build camera-angle-independent
feature vectors for DTW comparison.
"""
import numpy as np


def compute_angle_3pt(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> float:
    """
    Angle in degrees at vertex *b* formed by rays b->a and b->c.

    Works with 2D (x,y) or 3D (x,y,z) points. Uses the first min(len, 3)
    components so it handles both MediaPipe 2D and 3D landmarks.

    Returns value in [0, 180].
    """
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    c = np.asarray(c, dtype=np.float64).ravel()

    # Use up to 3 dimensions
    ndim = min(len(a), len(b), len(c), 3)
    ba = a[:ndim] - b[:ndim]
    bc = c[:ndim] - b[:ndim]

    norm_ba = np.linalg.norm(ba)
    norm_bc = np.linalg.norm(bc)
    if norm_ba < 1e-9 or norm_bc < 1e-9:
        return 0.0

    cos_val = np.dot(ba, bc) / (norm_ba * norm_bc)
    cos_val = np.clip(cos_val, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_val)))


def compute_segment_angle(
    a: np.ndarray,
    b: np.ndarray,
) -> float:
    """
    Angle of the directed segment a->b relative to the positive x-axis.

    Returns value in [0, 360). Uses only x,y components.
    """
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()

    dx = b[0] - a[0]
    dy = b[1] - a[1]
    angle = float(np.degrees(np.arctan2(dy, dx)))
    return angle % 360.0


def angular_velocity(
    angles: list[float] | np.ndarray,
    fps: float,
) -> list[float]:
    """
    First-order angular velocity from a time series of angle values (degrees).

    Uses central differences (numpy.gradient) scaled by fps.
    Returns a list of the same length as input, in degrees/second.
    """
    arr = np.asarray(angles, dtype=np.float64)
    if len(arr) < 2:
        return [0.0] * len(arr)

    # np.gradient uses central differences interior, forward/backward at edges
    grad = np.gradient(arr, 1.0 / fps)
    return [float(v) for v in grad]
