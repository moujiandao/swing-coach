"""
Tests for app/worker/evals.py — 9 deterministic pipeline checks.

Each test class corresponds to one check. Tests confirm both the passing
and failing conditions for each check.
"""
from dataclasses import dataclass, field

import numpy as np
import pytest

from app.worker.evals import run_pipeline_evals, EvalResult, _EXPECTED_JOINT_KEYS, _EXPECTED_PHASES
from app.worker.dtw_comparator import ComparisonResult, Deviation
from app.worker.feature_engine import FeatureExtractionResult


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

def _make_features(joint_keys=None) -> FeatureExtractionResult:
    """Build a minimal FeatureExtractionResult."""
    keys = joint_keys if joint_keys is not None else list(_EXPECTED_JOINT_KEYS)
    n = 30
    joint_angles = {k: np.zeros(n, dtype=np.float32) for k in keys}
    velocities = {"wrist_speed": np.zeros(n, dtype=np.float32)}
    phases = {
        "preparation": (0, 4), "backswing": (5, 12), "forward_swing": (13, 20),
        "contact": (21, 22), "follow_through": (23, 29),
    }
    return FeatureExtractionResult(joint_angles=joint_angles, velocities=velocities,
                                   phases=phases, contact_frame=21)


def _make_deviation(joint: str, severity: str = "moderate") -> Deviation:
    return Deviation(
        joint=joint, phase="forward_swing",
        mean_diff_degrees=20.0, max_diff_degrees=35.0,
        timing_offset_ms=0.0, severity=severity,
        description=f"{joint} deviation",
    )


def _make_comparison(
    overall_score: float = 72.0,
    phase_scores: dict | None = None,
    deviations: list | None = None,
) -> ComparisonResult:
    if phase_scores is None:
        phase_scores = {p: 70.0 for p in _EXPECTED_PHASES}
    if deviations is None:
        deviations = [_make_deviation("elbow_angle", "critical"),
                      _make_deviation("knee_bend", "moderate"),
                      _make_deviation("hip_rotation", "minor")]
    return ComparisonResult(
        overall_score=overall_score,
        phase_scores=phase_scores,
        deviations=deviations,
    )


def _make_feedback(
    summary: str = "Good overall effort.",
    assessment: str = "intermediate",
    priority_fixes: list | None = None,
    drill_plan: list | None = None,
) -> dict:
    if priority_fixes is None:
        priority_fixes = [
            {
                "title": "Elbow too wide",
                "explanation": "Elbow flares out during forward swing.",
                "target_metric": "elbow_angle during forward_swing",
                "current_value": "Your elbow angle averages 145°.",
                "target_value": "Pro reference shows 115° at contact.",
            }
        ]
    if drill_plan is None:
        drill_plan = [
            {
                "name": "Elbow tuck drill",
                "description": "Hold racket with arm close to body. Repeat 20x.",
                "duration": "10 minutes",
                "frequency": "Before each session",
                "focus_area": "Elbow too wide",
            }
        ]
    return {
        "summary": summary,
        "overall_assessment": assessment,
        "priority_fixes": priority_fixes,
        "drill_plan": drill_plan,
        "positive_notes": ["Good footwork."],
    }


def _run(features=None, comparison=None, feedback=None,
         frame_deviations=None, frame_mapping=None, num_user_frames=30) -> EvalResult:
    return run_pipeline_evals(
        features=features or _make_features(),
        comparison=comparison or _make_comparison(),
        feedback=feedback or _make_feedback(),
        frame_deviations=frame_deviations,
        frame_mapping=frame_mapping or list(range(num_user_frames)),
        num_user_frames=num_user_frames,
    )


# ---------------------------------------------------------------------------
# Check 1: Feature completeness
# ---------------------------------------------------------------------------

class TestCheck1FeatureCompleteness:
    def test_passes_with_all_keys(self):
        result = _run()
        assert result.score >= 1
        assert not any("Check 1" in i for i in result.issues)

    def test_fails_when_key_missing(self):
        keys = list(_EXPECTED_JOINT_KEYS - {"stance_width"})
        result = _run(features=_make_features(joint_keys=keys))
        assert any("Check 1" in i for i in result.issues)
        assert any("stance_width" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 2: Score bounds
# ---------------------------------------------------------------------------

class TestCheck2ScoreBounds:
    def test_passes_with_valid_scores(self):
        result = _run()
        assert not any("Check 2" in i for i in result.issues)

    def test_fails_when_overall_score_negative(self):
        comp = _make_comparison(overall_score=-5.0)
        result = _run(comparison=comp)
        assert any("Check 2" in i for i in result.issues)

    def test_fails_when_overall_score_over_100(self):
        comp = _make_comparison(overall_score=105.0)
        result = _run(comparison=comp)
        assert any("Check 2" in i for i in result.issues)

    def test_fails_when_phase_score_out_of_bounds(self):
        phase_scores = {p: 70.0 for p in _EXPECTED_PHASES}
        phase_scores["contact"] = 110.0
        comp = _make_comparison(phase_scores=phase_scores)
        result = _run(comparison=comp)
        assert any("Check 2" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 3: Frame consistency
# ---------------------------------------------------------------------------

class TestCheck3FrameConsistency:
    def test_passes_when_mapping_matches(self):
        result = _run(frame_mapping=list(range(30)), num_user_frames=30)
        assert not any("Check 3" in i for i in result.issues)

    def test_fails_when_mapping_wrong_length(self):
        result = _run(frame_mapping=list(range(20)), num_user_frames=30)
        assert any("Check 3" in i for i in result.issues)

    def test_passes_when_no_frame_mapping(self):
        # frame_mapping=None means pro landmarks were unavailable — skip check
        result = _run(frame_mapping=None)
        assert not any("Check 3" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 4: Phase coverage
# ---------------------------------------------------------------------------

class TestCheck4PhaseCoverage:
    def test_passes_with_all_phases(self):
        result = _run()
        assert not any("Check 4" in i for i in result.issues)

    def test_fails_when_phase_missing(self):
        phase_scores = {p: 70.0 for p in _EXPECTED_PHASES if p != "contact"}
        comp = _make_comparison(phase_scores=phase_scores)
        result = _run(comparison=comp)
        assert any("Check 4" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 5: Schema completeness
# ---------------------------------------------------------------------------

class TestCheck5SchemaCompleteness:
    def test_passes_with_valid_feedback(self):
        result = _run()
        assert not any("Check 5" in i for i in result.issues)

    def test_fails_with_empty_summary(self):
        fb = _make_feedback(summary="")
        result = _run(feedback=fb)
        assert any("Check 5" in i and "summary" in i for i in result.issues)

    def test_fails_with_invalid_assessment(self):
        fb = _make_feedback(assessment="expert")
        result = _run(feedback=fb)
        assert any("Check 5" in i and "overall_assessment" in i for i in result.issues)

    def test_fails_with_empty_priority_fixes(self):
        fb = _make_feedback(priority_fixes=[])
        result = _run(feedback=fb)
        assert any("Check 5" in i and "priority_fixes" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 6: Fix alignment
# ---------------------------------------------------------------------------

class TestCheck6FixAlignment:
    def test_passes_when_metric_matches_deviation(self):
        # "elbow_angle" is in deviations, "elbow" appears in target_metric
        result = _run()
        assert not any("Check 6" in i for i in result.issues)

    def test_fails_when_metric_has_no_matching_joint(self):
        fb = _make_feedback(priority_fixes=[{
            "title": "Mystery fix",
            "explanation": "Something is wrong.",
            "target_metric": "completely_unrelated_metric",
            "current_value": "75°",
            "target_value": "90°",
        }])
        result = _run(feedback=fb)
        assert any("Check 6" in i for i in result.issues)

    def test_passes_vacuously_with_no_deviations(self):
        comp = _make_comparison(deviations=[])
        result = _run(comparison=comp)
        assert not any("Check 6" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 7: Numeric values in fixes
# ---------------------------------------------------------------------------

class TestCheck7NumericValues:
    def test_passes_with_numeric_values(self):
        result = _run()
        assert not any("Check 7" in i for i in result.issues)

    def test_fails_when_current_value_has_no_digits(self):
        fb = _make_feedback(priority_fixes=[{
            "title": "Elbow too wide",
            "explanation": "Elbow flares.",
            "target_metric": "elbow_angle during forward_swing",
            "current_value": "way too wide",
            "target_value": "Pro reference shows 115° at contact.",
        }])
        result = _run(feedback=fb)
        assert any("Check 7" in i and "current_value" in i for i in result.issues)

    def test_fails_when_target_value_has_no_digits(self):
        fb = _make_feedback(priority_fixes=[{
            "title": "Elbow too wide",
            "explanation": "Elbow flares.",
            "target_metric": "elbow_angle during forward_swing",
            "current_value": "Your elbow angle averages 145°.",
            "target_value": "much tighter please",
        }])
        result = _run(feedback=fb)
        assert any("Check 7" in i and "target_value" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 8: Deviation severity ordering
# ---------------------------------------------------------------------------

class TestCheck8SeverityOrdering:
    def test_passes_with_correct_order(self):
        # critical → moderate → minor is correct
        deviations = [
            _make_deviation("elbow_angle", "critical"),
            _make_deviation("knee_bend", "moderate"),
            _make_deviation("hip_rotation", "minor"),
        ]
        result = _run(comparison=_make_comparison(deviations=deviations))
        assert not any("Check 8" in i for i in result.issues)

    def test_fails_when_minor_before_critical(self):
        deviations = [
            _make_deviation("hip_rotation", "minor"),
            _make_deviation("elbow_angle", "critical"),
        ]
        result = _run(comparison=_make_comparison(deviations=deviations))
        assert any("Check 8" in i for i in result.issues)

    def test_passes_with_single_deviation(self):
        result = _run(comparison=_make_comparison(deviations=[_make_deviation("elbow_angle", "critical")]))
        assert not any("Check 8" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Check 9: Drill-fix linkage
# ---------------------------------------------------------------------------

class TestCheck9DrillFixLinkage:
    def test_passes_when_focus_area_matches_fix_title(self):
        result = _run()
        assert not any("Check 9" in i for i in result.issues)

    def test_fails_when_focus_area_doesnt_match(self):
        fb = _make_feedback(
            priority_fixes=[{"title": "Elbow too wide", "explanation": "x",
                              "target_metric": "elbow_angle", "current_value": "145°", "target_value": "115°"}],
            drill_plan=[{"name": "Mystery drill", "description": "do it",
                         "duration": "10 min", "frequency": "daily",
                         "focus_area": "Nonexistent Fix Title"}],
        )
        result = _run(feedback=fb)
        assert any("Check 9" in i for i in result.issues)

    def test_passes_with_empty_drill_plan(self):
        fb = _make_feedback(drill_plan=[])
        result = _run(feedback=fb)
        assert not any("Check 9" in i for i in result.issues)


# ---------------------------------------------------------------------------
# EvalResult aggregate
# ---------------------------------------------------------------------------

class TestEvalResultAggregate:
    def test_all_pass_returns_passed_true(self):
        result = _run()
        assert result.passed is True
        assert result.score == 9
        assert result.issues == []

    def test_partial_failures_reduce_score(self):
        # Break check 1 (missing key) and check 5 (empty summary)
        features = _make_features(joint_keys=list(_EXPECTED_JOINT_KEYS - {"stance_width"}))
        fb = _make_feedback(summary="")
        result = _run(features=features, feedback=fb)
        assert result.passed is False
        assert result.score < 9
        assert len(result.issues) >= 2
