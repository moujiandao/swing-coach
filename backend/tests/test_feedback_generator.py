"""
Tests for app/worker/feedback_generator.py

Live API tests are skipped unless ANTHROPIC_API_KEY is set in the environment.
Parse/structure tests run without any API key.
"""
import json
import os

import pytest

from app.worker.dtw_comparator import ComparisonResult, Deviation
from app.worker.feedback_generator import (
    CoachingFeedback,
    Drill,
    Fix,
    _build_user_message,
    _parse_response,
    generate_coaching_feedback,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DEVIATIONS = [
    Deviation(
        joint="elbow_angle",
        phase="forward_swing",
        mean_diff_degrees=-23.5,
        max_diff_degrees=31.0,
        timing_offset_ms=-45.0,
        severity="critical",
        description="Elbow Angle is 24° tighter than reference during forward swing (critical)",
    ),
    Deviation(
        joint="hip_rotation",
        phase="forward_swing",
        mean_diff_degrees=18.2,
        max_diff_degrees=26.0,
        timing_offset_ms=80.0,
        severity="moderate",
        description="Hip Rotation is 18° wider than reference during forward swing (moderate)",
    ),
    Deviation(
        joint="knee_bend",
        phase="backswing",
        mean_diff_degrees=12.0,
        max_diff_degrees=15.5,
        timing_offset_ms=0.0,
        severity="minor",
        description="Knee Bend is 12° wider than reference during backswing (minor)",
    ),
]

_COMPARISON = ComparisonResult(
    overall_score=58.3,
    phase_scores={
        "preparation":   82.1,
        "backswing":     71.4,
        "forward_swing": 44.2,
        "contact":       39.8,
        "follow_through":68.5,
    },
    deviations=_DEVIATIONS,
)


# ---------------------------------------------------------------------------
# _build_user_message (no API needed)
# ---------------------------------------------------------------------------

class TestBuildUserMessage:
    def test_contains_overall_score(self):
        msg = _build_user_message(_COMPARISON)
        assert "58.3" in msg

    def test_contains_all_phase_scores(self):
        msg = _build_user_message(_COMPARISON)
        for phase in ["preparation", "backswing", "forward_swing", "contact", "follow_through"]:
            assert phase in msg

    def test_contains_deviation_details(self):
        msg = _build_user_message(_COMPARISON)
        assert "elbow_angle" in msg
        assert "CRITICAL" in msg
        assert "forward_swing" in msg

    def test_no_deviations_message(self):
        empty = ComparisonResult(
            overall_score=95.0,
            phase_scores={"preparation": 95.0, "backswing": 95.0,
                          "forward_swing": 95.0, "contact": 95.0, "follow_through": 95.0},
            deviations=[],
        )
        msg = _build_user_message(empty)
        assert "No significant deviations" in msg


# ---------------------------------------------------------------------------
# _parse_response (no API needed)
# ---------------------------------------------------------------------------

def _valid_json_response(num_fixes: int = 2) -> str:
    fixes = [
        {
            "title": f"Fix {i + 1}",
            "explanation": f"Explanation for fix {i + 1} covering the biomechanical issue.",
            "target_metric": "elbow_angle during forward_swing",
            "current_value": "Elbow 24° too bent at contact",
            "target_value": "Pro shows elbow at 155° at contact",
        }
        for i in range(num_fixes)
    ]
    return json.dumps({
        "summary": "Overall a solid swing with some technique issues to address.",
        "overall_assessment": "intermediate",
        "priority_fixes": fixes,
        "positive_notes": ["Good follow-through extension", "Consistent ball toss position"],
        "drill_plan": [
            {
                "name": "Slow-motion shadow swing",
                "description": "Stand at the baseline without a ball. "
                               "Perform the swing in slow motion focusing on elbow extension. "
                               "Pause at the contact point for two seconds.",
                "duration": "10 minutes",
                "frequency": "Before each practice session",
                "focus_area": "Fix 1",
            }
        ],
    })


class TestParseResponse:
    def test_parses_valid_json(self):
        result = _parse_response(_valid_json_response())
        assert isinstance(result, CoachingFeedback)

    def test_summary_populated(self):
        result = _parse_response(_valid_json_response())
        assert len(result.summary) > 0

    def test_overall_assessment_populated(self):
        result = _parse_response(_valid_json_response())
        assert result.overall_assessment in {"beginner", "intermediate", "advanced", "pro-level"}

    def test_priority_fixes_capped_at_3(self):
        # Even if JSON has 4 fixes, we should get max 3
        data = json.loads(_valid_json_response(num_fixes=4))
        result = _parse_response(json.dumps(data))
        assert len(result.priority_fixes) <= 3

    def test_fix_fields_populated(self):
        result = _parse_response(_valid_json_response(num_fixes=1))
        fix = result.priority_fixes[0]
        assert isinstance(fix, Fix)
        assert fix.title
        assert fix.explanation
        assert fix.target_metric
        assert fix.current_value
        assert fix.target_value

    def test_drill_fields_populated(self):
        result = _parse_response(_valid_json_response())
        drill = result.drill_plan[0]
        assert isinstance(drill, Drill)
        assert drill.name
        assert drill.description
        assert drill.duration
        assert drill.frequency
        assert drill.focus_area

    def test_positive_notes_populated(self):
        result = _parse_response(_valid_json_response())
        assert len(result.positive_notes) >= 1

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("this is not json")

    def test_missing_required_key_raises(self):
        bad = json.dumps({"overall_assessment": "intermediate"})  # missing "summary"
        with pytest.raises(KeyError):
            _parse_response(bad)


# ---------------------------------------------------------------------------
# Live API tests — skipped without key
# ---------------------------------------------------------------------------

_has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


@pytest.mark.skipif(not _has_api_key, reason="ANTHROPIC_API_KEY not set")
@pytest.mark.asyncio
class TestLiveFeedbackGenerator:
    async def test_returns_coaching_feedback(self):
        result = await generate_coaching_feedback(
            comparison=_COMPARISON,
            stroke_type="forehand",
            pro_reference_name="synthetic",
        )
        assert isinstance(result, CoachingFeedback)

    async def test_priority_fixes_at_most_3(self):
        result = await generate_coaching_feedback(
            comparison=_COMPARISON,
            stroke_type="forehand",
            pro_reference_name="synthetic",
        )
        assert len(result.priority_fixes) <= 3

    async def test_summary_is_non_empty(self):
        result = await generate_coaching_feedback(
            comparison=_COMPARISON,
            stroke_type="forehand",
            pro_reference_name="synthetic",
        )
        assert len(result.summary) > 20

    async def test_drill_references_known_fix(self):
        result = await generate_coaching_feedback(
            comparison=_COMPARISON,
            stroke_type="forehand",
            pro_reference_name="synthetic",
        )
        fix_titles = {f.title for f in result.priority_fixes}
        for drill in result.drill_plan:
            assert drill.focus_area in fix_titles, (
                f"Drill '{drill.name}' references '{drill.focus_area}' "
                f"which is not in priority_fixes: {fix_titles}"
            )

    async def test_overall_assessment_valid_value(self):
        result = await generate_coaching_feedback(
            comparison=_COMPARISON,
            stroke_type="forehand",
            pro_reference_name="synthetic",
        )
        assert result.overall_assessment in {"beginner", "intermediate", "advanced", "pro-level"}

    async def test_feedback_references_deviation_data(self):
        """At least one fix should mention a joint name from the deviations."""
        result = await generate_coaching_feedback(
            comparison=_COMPARISON,
            stroke_type="forehand",
            pro_reference_name="synthetic",
        )
        deviation_joints = {"elbow", "hip", "knee"}
        any_reference = any(
            any(j in fix.explanation.lower() or j in fix.title.lower() for j in deviation_joints)
            for fix in result.priority_fixes
        )
        assert any_reference, "No fix mentioned any of the deviation joints"
