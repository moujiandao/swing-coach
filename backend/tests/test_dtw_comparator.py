"""
Tests for app/worker/dtw_comparator.py and app/pro_references/loader.py
"""
import tempfile
from pathlib import Path

import numpy as np
import pytest

from app.pro_references.loader import ProReferenceDB, save_reference
from app.worker.dtw_comparator import (
    ComparisonResult,
    Deviation,
    _PHASE_WEIGHTS,
    compare_swing,
    compute_base_score,
)
from app.worker.feature_engine import FeatureExtractionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PHASE_NAMES = ["preparation", "backswing", "forward_swing", "contact", "follow_through"]
_N = 60

_PHASES: dict[str, tuple[int, int]] = {
    "preparation":   (0,  9),
    "backswing":     (10, 24),
    "forward_swing": (25, 38),
    "contact":       (37, 41),
    "follow_through":(42, _N - 1),
}


def _make_angles(n: int = _N, seed: int = 0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    keys = [
        "elbow_angle", "shoulder_rotation", "hip_rotation",
        "trunk_rotation", "knee_bend", "racket_arm_elevation"
    ]
    return {k: rng.uniform(80.0, 170.0, n).astype(np.float32) for k in keys}


def _make_features(angles: dict, phases: dict = _PHASES, n: int = _N) -> FeatureExtractionResult:
    return FeatureExtractionResult(
        joint_angles=angles,
        velocities={
            "wrist_speed": np.ones(n, dtype=np.float32),
            "elbow_speed": np.ones(n, dtype=np.float32),
            "hip_speed":   np.ones(n, dtype=np.float32),
        },
        phases=phases,
        contact_frame=38,
    )


def _make_reference(angles: dict, phases: dict = _PHASES) -> dict:
    return {
        "player": "test_pro",
        "stroke_type": "forehand",
        "joint_angles": angles,
        "phases": phases,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# compare_swing — identical inputs
# ---------------------------------------------------------------------------

class TestIdenticalSwing:
    def test_overall_score_near_100(self):
        angles = _make_angles(seed=1)
        user = _make_features(angles)
        ref  = _make_reference(angles)
        result = compare_swing(user, ref, fps=30.0)
        assert result.overall_score > 95.0, f"Expected ~100, got {result.overall_score:.1f}"

    def test_all_phase_scores_near_100(self):
        angles = _make_angles(seed=2)
        user = _make_features(angles)
        ref  = _make_reference(angles)
        result = compare_swing(user, ref, fps=30.0)
        for phase, score in result.phase_scores.items():
            assert score > 90.0, f"Phase {phase}: expected ~100, got {score:.1f}"

    def test_no_deviations_for_identical(self):
        angles = _make_angles(seed=3)
        user = _make_features(angles)
        ref  = _make_reference(angles)
        result = compare_swing(user, ref, fps=30.0)
        assert result.deviations == [], f"Expected no deviations, got {result.deviations}"


# ---------------------------------------------------------------------------
# compare_swing — very different inputs
# ---------------------------------------------------------------------------

class TestDifferentSwing:
    def test_overall_score_low(self):
        # User angles wildly different from pro — 150° constant offset across all joints
        user_angles = _make_angles(seed=10)
        pro_angles = {k: (v + 150.0) % 360.0 for k, v in _make_angles(seed=10).items()}
        user = _make_features(user_angles)
        ref  = _make_reference(pro_angles)
        result = compare_swing(user, ref, fps=30.0)
        assert result.overall_score < 50.0, f"Expected low score, got {result.overall_score:.1f}"

    def test_deviations_present(self):
        user_angles = _make_angles(seed=11)
        pro_angles = {k: (v + 150.0) % 360.0 for k, v in _make_angles(seed=11).items()}
        user = _make_features(user_angles)
        ref  = _make_reference(pro_angles)
        result = compare_swing(user, ref, fps=30.0)
        assert len(result.deviations) > 0

    def test_deviations_sorted_by_severity(self):
        user_angles = _make_angles(seed=12)
        pro_angles = {k: (v + 150.0) % 360.0 for k, v in _make_angles(seed=12).items()}
        user = _make_features(user_angles)
        ref  = _make_reference(pro_angles)
        result = compare_swing(user, ref, fps=30.0)
        severity_order = {"critical": 0, "moderate": 1, "minor": 2}
        orders = [severity_order[d.severity] for d in result.deviations]
        assert orders == sorted(orders), "Deviations not sorted by severity"


# ---------------------------------------------------------------------------
# ComparisonResult structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_overall_score_in_0_100(self):
        user = _make_features(_make_angles(seed=20))
        ref  = _make_reference(_make_angles(seed=21))
        result = compare_swing(user, ref, fps=30.0)
        assert 0.0 <= result.overall_score <= 100.0

    def test_phase_scores_keys(self):
        user = _make_features(_make_angles(seed=22))
        ref  = _make_reference(_make_angles(seed=22))
        result = compare_swing(user, ref, fps=30.0)
        assert set(result.phase_scores.keys()) == set(_PHASE_NAMES)

    def test_deviation_fields(self):
        user_angles = _make_angles(seed=30)
        pro_angles = {k: v + 80.0 for k, v in _make_angles(seed=30).items()}
        user = _make_features(user_angles)
        ref  = _make_reference(pro_angles)
        result = compare_swing(user, ref, fps=30.0)
        if result.deviations:
            d = result.deviations[0]
            assert isinstance(d.joint, str)
            assert isinstance(d.phase, str)
            assert isinstance(d.mean_diff_degrees, float)
            assert isinstance(d.max_diff_degrees, float)
            assert isinstance(d.timing_offset_ms, float)
            assert d.severity in {"critical", "moderate", "minor"}
            assert isinstance(d.description, str) and len(d.description) > 0

    def test_deviation_description_human_readable(self):
        user_angles = _make_angles(seed=40)
        pro_angles = {k: v + 90.0 for k, v in _make_angles(seed=40).items()}
        user = _make_features(user_angles)
        ref  = _make_reference(pro_angles)
        result = compare_swing(user, ref, fps=30.0)
        for d in result.deviations:
            assert "°" in d.description or "deg" in d.description.lower() or any(c.isdigit() for c in d.description)


# ---------------------------------------------------------------------------
# Phase weighting
# ---------------------------------------------------------------------------

class TestPhaseWeighting:
    def test_forward_swing_and_contact_dominate(self):
        """
        Make only forward_swing + contact wrong; other phases perfect.
        Overall score should be notably lower than a swing where only
        preparation is wrong.
        """
        base_angles = _make_angles(seed=50)

        # Swing A: only forward_swing + contact have 80° offset
        angles_a = {k: v.copy() for k, v in base_angles.items()}
        for k in angles_a:
            angles_a[k][25:42] += 80.0  # forward_swing + contact range
        user_a = _make_features(angles_a)

        # Swing B: only preparation has 80° offset
        angles_b = {k: v.copy() for k, v in base_angles.items()}
        for k in angles_b:
            angles_b[k][0:10] += 80.0  # preparation range only
        user_b = _make_features(angles_b)

        ref = _make_reference(base_angles)

        score_a = compare_swing(user_a, ref, fps=30.0).overall_score
        score_b = compare_swing(user_b, ref, fps=30.0).overall_score

        # forward_swing (0.35) + contact (0.30) = 0.65 weight
        # preparation = 0.05 weight → swing A should score worse
        assert score_a < score_b, (
            f"Expected swing with bad forward_swing/contact ({score_a:.1f}) to "
            f"score lower than swing with bad preparation ({score_b:.1f})"
        )


# ---------------------------------------------------------------------------
# ProReferenceDB
# ---------------------------------------------------------------------------

class TestProReferenceDB:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            angles = _make_angles(seed=60)
            save_reference(
                player="testpro",
                stroke_type="forehand",
                joint_angles=angles,
                phases=_PHASES,
                data_dir=tmpdir,
            )
            db = ProReferenceDB(data_dir=tmpdir)
            db.load_all()
            ref = db.get_reference("testpro", "forehand")
            assert ref is not None
            assert ref["player"] == "testpro"
            assert ref["stroke_type"] == "forehand"

    def test_loaded_angles_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            angles = _make_angles(seed=61)
            save_reference(
                player="testpro",
                stroke_type="backhand_one",
                joint_angles=angles,
                phases=_PHASES,
                data_dir=tmpdir,
            )
            db = ProReferenceDB(data_dir=tmpdir)
            db.load_all()
            ref = db.get_reference("testpro", "backhand_one")
            for key, arr in angles.items():
                assert key in ref["joint_angles"], f"Missing angle: {key}"
                np.testing.assert_allclose(ref["joint_angles"][key], arr, rtol=1e-5)

    def test_loaded_phases_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_reference(
                player="testpro",
                stroke_type="forehand",
                joint_angles=_make_angles(seed=62),
                phases=_PHASES,
                data_dir=tmpdir,
            )
            db = ProReferenceDB(data_dir=tmpdir)
            db.load_all()
            ref = db.get_reference("testpro", "forehand")
            for phase, (s, e) in _PHASES.items():
                loaded = ref["phases"][phase]
                assert loaded == (s, e), f"Phase {phase}: expected {(s,e)}, got {loaded}"

    def test_get_reference_returns_none_for_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = ProReferenceDB(data_dir=tmpdir)
            db.load_all()
            assert db.get_reference("nobody", "smash") is None

    def test_list_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for player, stroke in [("federer", "forehand"), ("nadal", "forehand")]:
                save_reference(
                    player=player,
                    stroke_type=stroke,
                    joint_angles=_make_angles(),
                    phases=_PHASES,
                    data_dir=tmpdir,
                )
            db = ProReferenceDB(data_dir=tmpdir)
            db.load_all()
            available = db.list_available()
            assert len(available) == 2
            players = {a["player"] for a in available}
            assert players == {"federer", "nadal"}

    def test_empty_dir_loads_zero_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = ProReferenceDB(data_dir=tmpdir)
            db.load_all()
            assert db.references == {}

    def test_no_common_joints_raises(self):
        user_angles = {"elbow_angle": np.ones(_N, dtype=np.float32) * 90.0}
        pro_angles  = {"knee_bend": np.ones(_N, dtype=np.float32) * 150.0}
        user = _make_features(user_angles)
        ref  = _make_reference(pro_angles)
        with pytest.raises(ValueError, match="No common joint"):
            compare_swing(user, ref, fps=30.0)


# ---------------------------------------------------------------------------
# Synthetic reference integration
# ---------------------------------------------------------------------------

class TestSyntheticReference:
    def test_generate_and_compare(self):
        """Generate a synthetic reference and compare a near-identical swing — expect high score."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from generate_synthetic_reference import build_synthetic_forehand

        joint_angles, phases = build_synthetic_forehand(n=60, fps=30.0)
        ref = {
            "player": "synthetic",
            "stroke_type": "forehand",
            "joint_angles": joint_angles,
            "phases": phases,
            "metadata": {},
        }
        # Slightly perturbed user swing
        noisy_angles = {k: v + np.random.default_rng(99).normal(0, 2, len(v)).astype(np.float32)
                        for k, v in joint_angles.items()}
        user = _make_features(noisy_angles, phases=phases)
        result = compare_swing(user, ref, fps=30.0)
        assert result.overall_score > 70.0, f"Expected high score for near-identical swing, got {result.overall_score:.1f}"


# ---------------------------------------------------------------------------
# compute_base_score
# ---------------------------------------------------------------------------

class TestBaseScore:
    def _make_base_features(self, n: int = _N, seed: int = 0) -> FeatureExtractionResult:
        rng = np.random.default_rng(seed)
        return FeatureExtractionResult(
            joint_angles={
                "stance_width": rng.uniform(0.2, 0.5, n).astype(np.float32),
                "knee_bend": rng.uniform(140.0, 170.0, n).astype(np.float32),
                "hip_rotation": rng.uniform(20.0, 60.0, n).astype(np.float32),
                "elbow_angle": rng.uniform(80.0, 170.0, n).astype(np.float32),
            },
            velocities={
                "hip_speed": rng.uniform(50.0, 200.0, n).astype(np.float32),
                "wrist_speed": rng.uniform(100.0, 300.0, n).astype(np.float32),
            },
            phases=_PHASES,
            contact_frame=38,
        )

    def _make_base_ref(self, features: FeatureExtractionResult) -> dict:
        return {
            "player": "test_pro",
            "stroke_type": "forehand",
            "joint_angles": features.joint_angles,
            "velocities": features.velocities,
            "phases": _PHASES,
            "metadata": {},
        }

    def test_identical_base_score_near_100(self):
        features = self._make_base_features(seed=70)
        ref = self._make_base_ref(features)
        score = compute_base_score(features, ref)
        assert score > 95.0, f"Expected ~100 for identical, got {score:.1f}"

    def test_different_base_score_low(self):
        features = self._make_base_features(seed=71)
        ref_features = self._make_base_features(seed=72)
        # Add very large offset to make them clearly different
        for k in ["stance_width", "knee_bend", "hip_rotation"]:
            ref_features.joint_angles[k] = ref_features.joint_angles[k] + 200.0
        ref_features.velocities["hip_speed"] = ref_features.velocities["hip_speed"] + 1000.0
        ref = self._make_base_ref(ref_features)
        score = compute_base_score(features, ref)
        assert score < 80.0, f"Expected notably lower score for different, got {score:.1f}"

    def test_base_score_in_0_100(self):
        features = self._make_base_features(seed=73)
        ref = self._make_base_ref(self._make_base_features(seed=74))
        score = compute_base_score(features, ref)
        assert 0.0 <= score <= 100.0

    def test_base_score_missing_features_returns_50(self):
        """When no lower-body features exist, fallback to 50."""
        features = FeatureExtractionResult(
            joint_angles={"elbow_angle": np.ones(_N, dtype=np.float32)},
            velocities={"wrist_speed": np.ones(_N, dtype=np.float32)},
            phases=_PHASES,
            contact_frame=38,
        )
        ref = {"joint_angles": {"elbow_angle": np.ones(_N)}, "velocities": {}}
        score = compute_base_score(features, ref)
        assert score == 50.0

    def test_base_score_partial_features(self):
        """Score computes correctly with only some base features available."""
        features = FeatureExtractionResult(
            joint_angles={
                "knee_bend": np.linspace(140, 170, _N).astype(np.float32),
                "hip_rotation": np.linspace(20, 60, _N).astype(np.float32),
            },
            velocities={},
            phases=_PHASES,
            contact_frame=38,
        )
        ref = {
            "joint_angles": {
                "knee_bend": np.linspace(140, 170, _N).astype(np.float32),
                "hip_rotation": np.linspace(20, 60, _N).astype(np.float32),
            },
            "velocities": {},
        }
        score = compute_base_score(features, ref)
        assert score > 90.0, f"Expected high score for identical partial, got {score:.1f}"
