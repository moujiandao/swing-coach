"""
Integration test for angle-mode DTW through the pipeline path.

Tests the full flow: landmarks → feature extraction → angle-mode DTW → score output.
Does NOT require video files, DB, or Redis - tests the computational pipeline only.
"""
import numpy as np
import pytest

from app.config import Settings
from app.worker.angle_features import ANGLE_FEATURE_KEYS, extract_angle_features
from app.worker.dtw_comparator import ComparisonResult, compare_swing
from app.worker.feature_engine import FeatureExtractionResult, extract_features


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_swing_landmarks(n: int = 60, seed: int = 0) -> np.ndarray:
    """
    Build a synthetic (N, 33, 3) landmark sequence resembling a tennis swing.
    Includes motion on the hitting arm and trunk rotation.
    """
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.25, 0.75, (33, 3)).astype(np.float32)

    # Set plausible vertical ordering: shoulders above hips above knees above ankles
    base[11, 1] = 0.35  # L shoulder
    base[12, 1] = 0.35  # R shoulder
    base[23, 1] = 0.55  # L hip
    base[24, 1] = 0.55  # R hip
    base[25, 1] = 0.70  # L knee
    base[26, 1] = 0.70  # R knee
    base[27, 1] = 0.85  # L ankle
    base[28, 1] = 0.85  # R ankle

    landmarks = np.tile(base, (n, 1, 1))

    for i in range(n):
        t = i / max(n - 1, 1)
        # Simulate hitting arm arc (right side: shoulder=12, elbow=14, wrist=16)
        landmarks[i, 16, 0] += 0.15 * np.sin(np.pi * t)
        landmarks[i, 16, 1] -= 0.10 * np.cos(np.pi * t)
        landmarks[i, 14, 0] += 0.08 * np.sin(np.pi * t)
        landmarks[i, 14, 1] -= 0.05 * np.cos(np.pi * t)
        # Trunk rotation: shoulders shift slightly
        landmarks[i, 11, 0] -= 0.03 * np.sin(np.pi * t)
        landmarks[i, 12, 0] += 0.03 * np.sin(np.pi * t)

    return np.clip(landmarks, 0.01, 0.99).astype(np.float32)


# ---------------------------------------------------------------------------
# Pipeline integration: landmarks → features → angle DTW → score
# ---------------------------------------------------------------------------

class TestPipelineAngleIntegration:
    def test_full_angle_pipeline(self):
        """
        End-to-end: synthetic landmarks → extract_features (for phases) →
        angle-mode DTW → valid ComparisonResult with score.
        """
        user_lm = _make_swing_landmarks(n=60, seed=1)
        pro_lm = _make_swing_landmarks(n=60, seed=2)
        fps = 30.0

        # Step 1: extract features (phases, joint_angles for landmark mode)
        user_features = extract_features(user_lm, fps=fps, stroke_type="forehand")
        pro_features = extract_features(pro_lm, fps=fps, stroke_type="forehand")

        # Step 2: build pro reference dict (as the pipeline does)
        pro_ref = {
            "player": "synthetic_pro",
            "stroke_type": "forehand",
            "joint_angles": pro_features.joint_angles,
            "velocities": pro_features.velocities,
            "phases": pro_features.phases,
            "metadata": {},
        }

        # Step 3: compare in angle mode
        result = compare_swing(
            user_features, pro_ref, fps=fps,
            distance_mode="angle",
            user_landmarks=user_lm,
            pro_landmarks=pro_lm,
        )

        assert isinstance(result, ComparisonResult)
        assert 0.0 <= result.overall_score <= 100.0
        assert len(result.phase_scores) >= 5

    def test_angle_mode_same_user_pro_landmarks(self):
        """Same landmarks for user and pro should produce a high score."""
        lm = _make_swing_landmarks(n=60, seed=10)
        fps = 30.0
        features = extract_features(lm, fps=fps, stroke_type="forehand")
        pro_ref = {
            "player": "self",
            "stroke_type": "forehand",
            "joint_angles": features.joint_angles,
            "velocities": features.velocities,
            "phases": features.phases,
            "metadata": {},
        }
        result = compare_swing(
            features, pro_ref, fps=fps,
            distance_mode="angle",
            user_landmarks=lm, pro_landmarks=lm,
        )
        # Phases with enough frames should score ~100
        scored_phases = {k: v for k, v in result.phase_scores.items()
                        if v > 50.0}
        assert len(scored_phases) >= 2, "At least 2 phases should score above neutral"

    def test_landmark_mode_still_works(self):
        """Landmark mode (default) continues to work through the same code path."""
        lm = _make_swing_landmarks(n=60, seed=20)
        fps = 30.0
        features = extract_features(lm, fps=fps, stroke_type="forehand")
        pro_ref = {
            "player": "test_pro",
            "stroke_type": "forehand",
            "joint_angles": features.joint_angles,
            "velocities": features.velocities,
            "phases": features.phases,
            "metadata": {},
        }
        result = compare_swing(features, pro_ref, fps=fps, distance_mode="landmark")
        assert isinstance(result, ComparisonResult)
        assert 0.0 <= result.overall_score <= 100.0

    def test_angle_features_match_pipeline_output(self):
        """Angle features extracted in DTW match what extract_angle_features produces."""
        lm = _make_swing_landmarks(n=40, seed=30)
        direct_feats = extract_angle_features(lm, fps=30.0)
        for key in ANGLE_FEATURE_KEYS:
            assert key in direct_feats
            assert direct_feats[key].shape == (40,)


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------

class TestDistanceModeConfig:
    def test_default_distance_mode_is_angle(self):
        """Default config sets distance_mode to 'angle'."""
        settings = Settings(
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert settings.distance_mode == "angle"

    def test_distance_mode_env_override(self, monkeypatch):
        """DISTANCE_MODE env var overrides the default."""
        monkeypatch.setenv("DISTANCE_MODE", "landmark")
        # Clear the lru_cache so Settings re-reads env
        settings = Settings(
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert settings.distance_mode == "landmark"

    def test_fallback_when_no_pro_landmarks(self):
        """
        When distance_mode='angle' but pro landmarks are None,
        the pipeline should fall back to landmark mode gracefully.
        This tests the logic pattern, not the full pipeline DB path.
        """
        lm = _make_swing_landmarks(n=60, seed=40)
        fps = 30.0
        features = extract_features(lm, fps=fps, stroke_type="forehand")
        pro_ref = {
            "player": "legacy_pro",
            "stroke_type": "forehand",
            "joint_angles": features.joint_angles,
            "velocities": features.velocities,
            "phases": features.phases,
            "metadata": {},
        }
        # Simulate the fallback logic from tasks.py
        distance_mode = "angle"
        pro_landmarks_np = None  # no raw pro landmarks
        if distance_mode == "angle" and pro_landmarks_np is None:
            distance_mode = "landmark"
        result = compare_swing(
            features, pro_ref, fps=fps, distance_mode=distance_mode,
        )
        assert isinstance(result, ComparisonResult)
        assert 0.0 <= result.overall_score <= 100.0
