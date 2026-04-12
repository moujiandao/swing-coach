"""
Canonical 3D pose normalization for angle-invariant overlay rendering.

Phase 2 of the Angle-Invariant Swing Analysis Sprint.

Transforms MediaPipe world_landmarks into a canonical coordinate frame:
  1. Translate pelvis (midpoint of left_hip + right_hip) to origin
  2. Compute torso facing direction from shoulder-hip plane
  3. Rotate all landmarks so facing direction aligns with +Z axis

This makes poses from different camera angles comparable in 3D space.
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)

# BlazePose landmark indices
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12


def _rotation_matrix_align_z(facing: np.ndarray) -> np.ndarray:
    """
    Compute a 3x3 rotation matrix that rotates `facing` to align with +Z axis.

    Uses Rodrigues' rotation formula. If facing is already aligned (or anti-aligned)
    with +Z, returns identity (or 180-degree rotation around Y).
    """
    facing = facing / (np.linalg.norm(facing) + 1e-8)
    target = np.array([0.0, 0.0, 1.0])

    dot = np.dot(facing, target)
    if dot > 0.9999:
        return np.eye(3, dtype=np.float32)
    if dot < -0.9999:
        # 180-degree rotation around Y axis
        return np.array([[-1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float32)

    cross = np.cross(facing, target)
    skew = np.array([
        [0, -cross[2], cross[1]],
        [cross[2], 0, -cross[0]],
        [-cross[1], cross[0], 0],
    ], dtype=np.float64)

    R = np.eye(3) + skew + skew @ skew * (1.0 / (1.0 + dot))
    return R.astype(np.float32)


def canonicalize(world_landmarks: np.ndarray) -> np.ndarray:
    """
    Transform a sequence of 3D world landmarks into a canonical coordinate frame.

    Args:
        world_landmarks: (num_frames, 33, 3) array of 3D world coordinates.

    Returns:
        (num_frames, 33, 3) array in canonical frame: pelvis at origin,
        torso facing +Z direction.

    The function processes each frame independently so that per-frame body
    rotation is normalized while preserving relative limb positions.
    """
    if world_landmarks is None or world_landmarks.ndim != 3:
        raise ValueError("world_landmarks must be a 3D array of shape (frames, 33, 3)")

    num_frames, num_landmarks, num_coords = world_landmarks.shape
    if num_coords != 3:
        raise ValueError(f"Expected 3 coordinates per landmark, got {num_coords}")

    canonical = np.zeros_like(world_landmarks)

    for i in range(num_frames):
        frame = world_landmarks[i]  # (33, 3)

        # 1. Translate pelvis to origin
        pelvis = (frame[LEFT_HIP] + frame[RIGHT_HIP]) / 2.0
        centered = frame - pelvis

        # 2. Compute facing direction from shoulder-hip plane
        # The torso plane is defined by the vectors: left_hip->right_hip and
        # mid_hip->mid_shoulder. The normal to this plane is the facing direction.
        hip_vec = centered[RIGHT_HIP] - centered[LEFT_HIP]
        mid_shoulder = (centered[LEFT_SHOULDER] + centered[RIGHT_SHOULDER]) / 2.0
        up_vec = mid_shoulder  # pelvis is at origin, so mid_shoulder IS the up vector

        facing = np.cross(hip_vec, up_vec)
        facing_norm = np.linalg.norm(facing)

        if facing_norm < 1e-6:
            # Degenerate frame (landmarks collapsed) - skip rotation
            canonical[i] = centered
            continue

        # 3. Rotate so facing direction aligns with +Z
        R = _rotation_matrix_align_z(facing)
        canonical[i] = (R @ centered.T).T

    return canonical
