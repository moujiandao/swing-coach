"""
Camera-angle-invariant feature extraction from pose landmark sequences.

Extracts joint angles (in degrees) that are stable across different camera
perspectives, unlike raw XY landmark positions. These features feed into
the 'angle' distance mode of the DTW comparator.

MediaPipe BlazePose landmark indices:
  11=L_SHOULDER, 12=R_SHOULDER, 13=L_ELBOW, 14=R_ELBOW,
  15=L_WRIST, 16=R_WRIST, 23=L_HIP, 24=R_HIP,
  25=L_KNEE, 26=R_KNEE, 27=L_ANKLE, 28=R_ANKLE
"""
import logging

import numpy as np

from app.worker.angle_utils import angular_velocity, compute_angle_3pt, compute_segment_angle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MediaPipe landmark indices (BlazePose 33-point model)
# ---------------------------------------------------------------------------
_LM = {
    "L_SHOULDER": 11, "R_SHOULDER": 12,
    "L_ELBOW": 13,    "R_ELBOW": 14,
    "L_WRIST": 15,    "R_WRIST": 16,
    "L_HIP": 23,      "R_HIP": 24,
    "L_KNEE": 25,     "R_KNEE": 26,
    "L_ANKLE": 27,    "R_ANKLE": 28,
    "NOSE": 0,
}

# Angle feature keys - this is the canonical list of features produced
ANGLE_FEATURE_KEYS = [
    "elbow_flexion_hit",
    "elbow_flexion_nonhit",
    "shoulder_abduction_hit",
    "shoulder_rotation_est",
    "hip_rotation_est",
    "knee_bend_hit",
    "knee_bend_nonhit",
    "wrist_deviation_hit",
    "trunk_lateral_tilt",
]

VELOCITY_FEATURE_KEYS = [
    "elbow_flexion_hit_velocity",
    "shoulder_abduction_hit_velocity",
    "hip_rotation_est_velocity",
    "knee_bend_hit_velocity",
]


def extract_angle_features(
    landmarks_sequence: np.ndarray,
    fps: float,
    handedness: str = "right",
) -> dict[str, np.ndarray]:
    """
    Extract camera-angle-invariant features from a landmark sequence.

    Args:
        landmarks_sequence: (N, 33, 3) array of normalized x,y,z landmarks.
        fps: Frames per second of the source video.
        handedness: "right" or "left" - determines hitting arm.

    Returns:
        Dict mapping feature name -> (N,) float32 array.
        Keys include all ANGLE_FEATURE_KEYS and VELOCITY_FEATURE_KEYS.
    """
    if landmarks_sequence.ndim != 3 or landmarks_sequence.shape[1] < 33:
        raise ValueError(
            f"Expected landmarks shape (N, 33, 3), got {landmarks_sequence.shape}"
        )

    n = landmarks_sequence.shape[0]

    # Select hitting/non-hitting side indices
    if handedness == "left":
        hit_s, hit_e, hit_w = _LM["L_SHOULDER"], _LM["L_ELBOW"], _LM["L_WRIST"]
        hit_h, hit_k, hit_a = _LM["L_HIP"], _LM["L_KNEE"], _LM["L_ANKLE"]
        non_s, non_e, non_w = _LM["R_SHOULDER"], _LM["R_ELBOW"], _LM["R_WRIST"]
        non_h, non_k, non_a = _LM["R_HIP"], _LM["R_KNEE"], _LM["R_ANKLE"]
    else:
        hit_s, hit_e, hit_w = _LM["R_SHOULDER"], _LM["R_ELBOW"], _LM["R_WRIST"]
        hit_h, hit_k, hit_a = _LM["R_HIP"], _LM["R_KNEE"], _LM["R_ANKLE"]
        non_s, non_e, non_w = _LM["L_SHOULDER"], _LM["L_ELBOW"], _LM["L_WRIST"]
        non_h, non_k, non_a = _LM["L_HIP"], _LM["L_KNEE"], _LM["L_ANKLE"]

    def lm(idx: int) -> np.ndarray:
        return landmarks_sequence[:, idx, :]  # (N, 3)

    features: dict[str, np.ndarray] = {}

    # --- Joint angles (per frame) ---

    # Elbow flexion: angle at elbow (shoulder-elbow-wrist)
    features["elbow_flexion_hit"] = np.array(
        [compute_angle_3pt(lm(hit_s)[i], lm(hit_e)[i], lm(hit_w)[i]) for i in range(n)],
        dtype=np.float32,
    )
    features["elbow_flexion_nonhit"] = np.array(
        [compute_angle_3pt(lm(non_s)[i], lm(non_e)[i], lm(non_w)[i]) for i in range(n)],
        dtype=np.float32,
    )

    # Shoulder abduction: angle at shoulder (elbow-shoulder-hip)
    features["shoulder_abduction_hit"] = np.array(
        [compute_angle_3pt(lm(hit_e)[i], lm(hit_s)[i], lm(hit_h)[i]) for i in range(n)],
        dtype=np.float32,
    )

    # Shoulder rotation (estimated from 2D projection): angle of shoulder line vs horizontal
    # This is a projection-based estimate, not true 3D rotation.
    # TODO(brian): In Phase 2 with world_landmarks, replace with true 3D shoulder rotation
    features["shoulder_rotation_est"] = np.array(
        [compute_segment_angle(lm(_LM["L_SHOULDER"])[i], lm(_LM["R_SHOULDER"])[i]) for i in range(n)],
        dtype=np.float32,
    )

    # Hip rotation (estimated from 2D projection): angle of hip line vs horizontal
    features["hip_rotation_est"] = np.array(
        [compute_segment_angle(lm(_LM["L_HIP"])[i], lm(_LM["R_HIP"])[i]) for i in range(n)],
        dtype=np.float32,
    )

    # Knee bend: angle at knee (hip-knee-ankle)
    features["knee_bend_hit"] = np.array(
        [compute_angle_3pt(lm(hit_h)[i], lm(hit_k)[i], lm(hit_a)[i]) for i in range(n)],
        dtype=np.float32,
    )
    features["knee_bend_nonhit"] = np.array(
        [compute_angle_3pt(lm(non_h)[i], lm(non_k)[i], lm(non_a)[i]) for i in range(n)],
        dtype=np.float32,
    )

    # Wrist deviation: angle at wrist (elbow-wrist-index_finger or elbow-wrist-hip as proxy)
    # Using elbow-wrist-hip_same_side as a proxy for wrist angle since MediaPipe
    # hand landmarks aren't always reliable at tennis video distances.
    # TODO(brian): Consider using hand landmarks (index finger tip = 20/19) if detection is reliable
    features["wrist_deviation_hit"] = np.array(
        [compute_angle_3pt(lm(hit_e)[i], lm(hit_w)[i], lm(hit_h)[i]) for i in range(n)],
        dtype=np.float32,
    )

    # Trunk lateral tilt: angle formed by midpoint(shoulders)-midpoint(hips)-vertical reference
    # Approximated as the segment angle of the trunk midline relative to vertical (90 deg = upright)
    mid_shoulder = (lm(_LM["L_SHOULDER"]) + lm(_LM["R_SHOULDER"])) / 2.0  # (N, 3)
    mid_hip = (lm(_LM["L_HIP"]) + lm(_LM["R_HIP"])) / 2.0               # (N, 3)
    features["trunk_lateral_tilt"] = np.array(
        [compute_segment_angle(mid_hip[i], mid_shoulder[i]) for i in range(n)],
        dtype=np.float32,
    )

    # --- Angular velocities (degrees/second) ---
    for base_key, vel_key in [
        ("elbow_flexion_hit", "elbow_flexion_hit_velocity"),
        ("shoulder_abduction_hit", "shoulder_abduction_hit_velocity"),
        ("hip_rotation_est", "hip_rotation_est_velocity"),
        ("knee_bend_hit", "knee_bend_hit_velocity"),
    ]:
        vel = angular_velocity(features[base_key].tolist(), fps)
        features[vel_key] = np.array(vel, dtype=np.float32)

    logger.info(
        "Angle features extracted: %d frames, %d features",
        n, len(features),
    )

    return features
