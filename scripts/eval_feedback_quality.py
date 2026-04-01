"""
LLM-as-judge feedback quality evaluator — Track C.

Loads a completed analysis from the DB, scores the Claude-generated coaching
feedback using a rubric, and optionally triggers a self-repair loop if the
score falls below the passing threshold.

Usage:
    uv --project backend run python scripts/eval_feedback_quality.py \\
        --analysis-id <uuid> [--max-retries 1]

Output: JSON to stdout with original_score, final_score, attempts, passed,
        final_feedback.

Offline only by default — not wired into the production pipeline.
Set ENABLE_LLM_EVAL_REPAIR=true in the environment to enable production repair.
"""
import argparse
import asyncio
import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Add the backend/app directory to sys.path so we can import from app.*
_BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import anthropic
from sqlalchemy import select

from app.config import get_settings
from app.models import Analysis
from app.services.db import get_session
from app.worker.dtw_comparator import ComparisonResult, Deviation
from app.worker.feedback_generator import generate_coaching_feedback

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_JUDGE_MODEL = "claude-sonnet-4-6"
_PASSING_THRESHOLD = 7


# ---------------------------------------------------------------------------
# Rubric schema
# ---------------------------------------------------------------------------

@dataclass
class RubricScore:
    specificity_score: int       # 0-3: references actual measured values
    specificity_critique: str
    alignment_score: int         # 0-3: fixes correspond to detected deviation joints
    alignment_critique: str
    actionability_score: int     # 0-2: drills are step-by-step and specific
    actionability_critique: str
    completeness_score: int      # 0-2: critical/moderate deviations addressed
    completeness_critique: str
    total_score: int             # 0-10


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """\
You are an expert evaluator of AI-generated tennis coaching feedback.
You are given:
1. The raw deviation data that was fed to the AI coach
2. The AI coach's feedback response

Score the feedback on 4 dimensions. Return ONLY valid JSON — no prose, no markdown.

Rubric:
- specificity (0-3): Does the feedback reference actual measured angles/values from the deviation data?
  3 = multiple specific numbers cited correctly
  2 = at least one specific number cited
  1 = vague references to measurements without numbers
  0 = no reference to measured data at all

- alignment (0-3): Does each priority_fix correspond to an actual detected deviation joint?
  3 = all fixes reference real detected deviation joints
  2 = most fixes reference real joints, one is off
  1 = some fixes reference real joints
  0 = fixes are disconnected from the deviation data

- actionability (0-2): Are drills step-by-step and specific (not generic)?
  2 = all drills have specific, numbered steps
  1 = drills are somewhat specific
  0 = generic advice like "practice more"

- completeness (0-2): Are all critical/moderate deviations addressed in priority_fixes?
  2 = all critical and moderate deviations mentioned
  1 = most are addressed
  0 = several critical/moderate deviations ignored

JSON schema:
{
  "specificity_score": 0-3,
  "specificity_critique": "string",
  "alignment_score": 0-3,
  "alignment_critique": "string",
  "actionability_score": 0-2,
  "actionability_critique": "string",
  "completeness_score": 0-2,
  "completeness_critique": "string",
  "total_score": 0-10
}"""


def _build_judge_message(deviation_data: str, feedback: dict) -> str:
    return f"""DEVIATION DATA:
{deviation_data}

AI COACH FEEDBACK:
{json.dumps(feedback, indent=2)}"""


def _format_deviation_data(deviations: list, phase_scores: dict, overall_score: float) -> str:
    lines = [
        f"Overall score: {overall_score:.1f}/100",
        "",
        "Phase scores:",
    ]
    for phase, score in phase_scores.items():
        lines.append(f"  {phase}: {score:.1f}")
    lines.append("")
    lines.append(f"Deviations ({len(deviations)} total):")
    for d in deviations:
        lines.append(
            f"  [{d.get('severity','?').upper()}] {d.get('joint','?')} during {d.get('phase','?')}: "
            f"mean diff {d.get('mean_diff_degrees', 0):+.1f}°, "
            f"max diff {d.get('max_diff_degrees', 0):.1f}°"
        )
        if d.get("description"):
            lines.append(f"    → {d['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core async functions
# ---------------------------------------------------------------------------

async def _load_analysis(analysis_id: str) -> Analysis:
    async with get_session() as session:
        result = await session.execute(
            select(Analysis).where(Analysis.id == uuid.UUID(analysis_id))
        )
        analysis = result.scalar_one_or_none()
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id} not found")
        if analysis.status.value != "completed":
            raise ValueError(f"Analysis {analysis_id} is not completed (status={analysis.status.value})")
        return analysis


async def _judge_feedback(
    deviation_data: str,
    feedback: dict,
    client: anthropic.AsyncAnthropic,
) -> RubricScore:
    """Call the LLM judge and parse the rubric response."""
    message = _build_judge_message(deviation_data, feedback)
    response = await client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=1000,
        temperature=0.0,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": message}],
    )
    raw = response.content[0].text
    data = json.loads(raw)
    return RubricScore(
        specificity_score=int(data["specificity_score"]),
        specificity_critique=data["specificity_critique"],
        alignment_score=int(data["alignment_score"]),
        alignment_critique=data["alignment_critique"],
        actionability_score=int(data["actionability_score"]),
        actionability_critique=data["actionability_critique"],
        completeness_score=int(data["completeness_score"]),
        completeness_critique=data["completeness_critique"],
        total_score=int(data["total_score"]),
    )


def _build_critique_context(score: RubricScore) -> str:
    critiques = []
    if score.specificity_score < 2:
        critiques.append(f"Specificity ({score.specificity_score}/3): {score.specificity_critique}")
    if score.alignment_score < 2:
        critiques.append(f"Alignment ({score.alignment_score}/3): {score.alignment_critique}")
    if score.actionability_score < 1:
        critiques.append(f"Actionability ({score.actionability_score}/2): {score.actionability_critique}")
    if score.completeness_score < 1:
        critiques.append(f"Completeness ({score.completeness_score}/2): {score.completeness_critique}")

    critique_text = "\n".join(f"- {c}" for c in critiques)
    return (
        f"Your feedback scored {score.total_score}/10. Issues:\n{critique_text}\n\n"
        "Regenerate the feedback addressing these issues, citing specific measured angles "
        "from the deviation data provided."
    )


def _reconstruct_comparison(analysis: Analysis) -> ComparisonResult:
    """Rebuild a ComparisonResult from the serialized DB fields."""
    deviations = [
        Deviation(
            joint=d["joint"],
            phase=d["phase"],
            mean_diff_degrees=d["mean_diff_degrees"],
            max_diff_degrees=d["max_diff_degrees"],
            timing_offset_ms=d["timing_offset_ms"],
            severity=d["severity"],
            description=d.get("description", ""),
        )
        for d in (analysis.deviations or [])
    ]
    return ComparisonResult(
        overall_score=analysis.overall_score or 0.0,
        phase_scores=analysis.phase_scores or {},
        deviations=deviations,
    )


async def _run_eval(analysis_id: str, max_retries: int) -> dict:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Load analysis
    analysis = await _load_analysis(analysis_id)
    feedback = analysis.coaching_feedback or {}
    comparison = _reconstruct_comparison(analysis)
    deviation_data = _format_deviation_data(
        analysis.deviations or [],
        analysis.phase_scores or {},
        analysis.overall_score or 0.0,
    )

    # First judgment
    original_score_obj = await _judge_feedback(deviation_data, feedback, client)
    original_score = original_score_obj.total_score
    final_score = original_score
    final_feedback = feedback
    attempts = 1

    # Self-repair loop
    current_score_obj = original_score_obj
    while final_score < _PASSING_THRESHOLD and attempts <= max_retries:
        logger.warning(
            "Score %d < threshold %d — attempting repair (attempt %d/%d)",
            final_score, _PASSING_THRESHOLD, attempts, max_retries,
        )
        critique = _build_critique_context(current_score_obj)
        new_feedback_obj = await generate_coaching_feedback(
            comparison=comparison,
            stroke_type=analysis.stroke_type.value,
            pro_reference_name=analysis.pro_reference,
            critique_context=critique,
        )
        new_feedback = asdict(new_feedback_obj)
        current_score_obj = await _judge_feedback(deviation_data, new_feedback, client)
        final_score = current_score_obj.total_score
        final_feedback = new_feedback
        attempts += 1

    return {
        "analysis_id": analysis_id,
        "original_score": original_score,
        "final_score": final_score,
        "attempts": attempts,
        "passed": final_score >= _PASSING_THRESHOLD,
        "rubric_detail": asdict(current_score_obj) if attempts > 1 else asdict(original_score_obj),
        "final_feedback": final_feedback,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-as-judge evaluation and optional self-repair for coaching feedback."
    )
    parser.add_argument("--analysis-id", required=True, help="UUID of a completed Analysis record")
    parser.add_argument(
        "--max-retries", type=int, default=1,
        help="Max self-repair attempts if score < 7 (default: 1)",
    )
    args = parser.parse_args()

    result = asyncio.run(_run_eval(args.analysis_id, args.max_retries))
    print(json.dumps(result, indent=2))

    if not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
