"""
Claude API coaching feedback generator.

Stage 5 of the worker pipeline: ComparisonResult → CoachingFeedback.

Calls Claude with structured swing deviation data and parses a JSON response
into actionable coaching advice with specific drills.
"""
import json
import logging
from dataclasses import dataclass, field

import anthropic

from app.config import get_settings
from app.worker.dtw_comparator import ComparisonResult, Deviation

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 2000
_TEMPERATURE = 0.3


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Fix:
    title: str           # e.g. "Late hip rotation"
    explanation: str     # what's happening and why it matters (2-3 sentences)
    target_metric: str   # which joint/angle to improve
    current_value: str   # "Your hip rotation starts 80ms after your shoulder"
    target_value: str    # "Pro reference shows hip leading shoulder by 20ms"


@dataclass
class Drill:
    name: str            # e.g. "Shadow swing with pause at trophy position"
    description: str     # step-by-step instructions (3-5 sentences)
    duration: str        # e.g. "10 minutes"
    frequency: str       # e.g. "Before each practice session"
    focus_area: str      # which Fix title this addresses


@dataclass
class CoachingFeedback:
    summary: str                        # 2-3 sentence overview
    overall_assessment: str             # "beginner" | "intermediate" | "advanced" | "pro-level"
    priority_fixes: list[Fix] = field(default_factory=list)   # top 3, ordered by impact
    positive_notes: list[str] = field(default_factory=list)   # 2-3 things going well
    drill_plan: list[Drill] = field(default_factory=list)     # drills for priority fixes


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert tennis coach with 20 years of experience analyzing player technique.
You are reviewing biomechanical data comparing a student's {stroke_type} to a reference \
swing from {pro_reference_name}.

Your role:
- Provide specific, actionable feedback grounded in the data provided
- Never give generic advice like "practice more" — every recommendation must reference \
the specific deviations measured
- Drills should be progressive: start with the most impactful issue, build toward full swing
- Be encouraging but honest about what needs work
- Limit priority_fixes to the 3 most impactful issues (not all deviations)

IMPORTANT: Respond ONLY with valid JSON matching this exact schema — no markdown, \
no prose, no code blocks:

{{
  "summary": "string (2-3 sentences overall impression)",
  "overall_assessment": "beginner|intermediate|advanced|pro-level",
  "priority_fixes": [
    {{
      "title": "string (short label, e.g. 'Late hip rotation')",
      "explanation": "string (2-3 sentences: what is happening and why it hurts the stroke)",
      "target_metric": "string (joint/phase, e.g. 'hip_rotation during forward_swing')",
      "current_value": "string (describe the student's measurement)",
      "target_value": "string (describe what the pro reference shows)"
    }}
  ],
  "positive_notes": ["string", "string"],
  "drill_plan": [
    {{
      "name": "string (drill name)",
      "description": "string (3-5 sentences of step-by-step instructions)",
      "duration": "string (e.g. '10 minutes')",
      "frequency": "string (e.g. 'Before each practice session')",
      "focus_area": "string (must match a priority_fixes title exactly)"
    }}
  ]
}}

GOLDEN RULES OF TENNIS TECHNIQUE (apply these when analyzing deviations):
1. FOOTWORK FIRST: The player must move to the ball and establish a balanced base before \
initiating the backswing. Late footwork causes rushed, arm-heavy swings.
2. HIGH ELBOW BACKSWING: During the backswing, the hitting elbow should maintain elevation \
- a low elbow reduces the torque available for the forward swing and leads to flat, \
powerless contact.
3. BALANCE THROUGH CONTACT: The player must stay balanced on both feet while hitting through \
the contact point. Falling off-balance leads to inconsistent contact and loss of control.
4. FOLLOW-THROUGH TO LEFT POCKET: On the follow-through, the racquet tip should point \
diagonally downward toward the left side pocket of the player's pants (for right-handers). \
This ensures full extension and proper racquet path.

When recommending drills, use real tennis training methodology:
- Shadow swings with pause points at each phase
- Ball-drop drills for contact point consistency
- Resistance band work for kinetic chain activation
- Wall rally drills for rhythm and timing
- Cone footwork patterns specific to the stroke being analyzed
Do NOT invent drills. Only recommend drills that real tennis coaches use."""


def _build_user_message(comparison: ComparisonResult) -> str:
    lines = [
        f"Overall similarity score: {comparison.overall_score:.1f}/100",
        "",
        "Phase scores (0-100, higher = closer to pro):",
    ]
    for phase, score in comparison.phase_scores.items():
        lines.append(f"  {phase}: {score:.1f}")

    if comparison.swing_tempo:
        t = comparison.swing_tempo
        lines.append("")
        lines.append("Swing tempo (backswing duration / forward swing duration):")
        lines.append(f"  Player ratio: {t['user_ratio']:.2f}:1")
        lines.append(f"  Pro ratio:    {t['pro_ratio']:.2f}:1")
        lines.append(f"  Similarity:   {t['similarity']:.1f}/100")

    lines.append("")
    if comparison.deviations:
        lines.append(f"Detected deviations ({len(comparison.deviations)} total, worst first):")
        for d in comparison.deviations:
            lines.append(
                f"  [{d.severity.upper()}] {d.joint} during {d.phase}: "
                f"mean diff {d.mean_diff_degrees:+.1f}°, "
                f"max diff {d.max_diff_degrees:.1f}°, "
                f"timing offset {d.timing_offset_ms:+.0f}ms"
            )
            lines.append(f"    → {d.description}")
    else:
        lines.append("No significant deviations detected — swing closely matches the reference.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> CoachingFeedback:
    """Parse Claude's JSON response into a CoachingFeedback dataclass."""
    data = json.loads(raw)

    fixes = [
        Fix(
            title=f["title"],
            explanation=f["explanation"],
            target_metric=f["target_metric"],
            current_value=f["current_value"],
            target_value=f["target_value"],
        )
        for f in data.get("priority_fixes", [])
    ]

    drills = [
        Drill(
            name=d["name"],
            description=d["description"],
            duration=d["duration"],
            frequency=d["frequency"],
            focus_area=d["focus_area"],
        )
        for d in data.get("drill_plan", [])
    ]

    return CoachingFeedback(
        summary=data["summary"],
        overall_assessment=data["overall_assessment"],
        priority_fixes=fixes[:3],  # enforce max 3
        positive_notes=data.get("positive_notes", []),
        drill_plan=drills,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_coaching_feedback(
    comparison: ComparisonResult,
    stroke_type: str,
    pro_reference_name: str,
    critique_context: str | None = None,
) -> CoachingFeedback:
    """
    Call Claude API to generate structured coaching feedback from swing comparison data.

    Args:
        comparison: Output of compare_swing() with scores and deviations.
        stroke_type: e.g. "forehand", "backhand_one"
        pro_reference_name: e.g. "federer" (used in the system prompt)
        critique_context: Optional critique from LLM-as-judge to inject as a follow-up
            message, requesting regeneration that addresses identified weaknesses.

    Returns:
        CoachingFeedback with summary, fixes, drills, and positive notes.

    Raises:
        ValueError: if Claude's response cannot be parsed as valid JSON after retry.
        anthropic.APIError: on API-level failures (rate limits, auth errors, etc.).
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    system = _SYSTEM_PROMPT.format(
        stroke_type=stroke_type,
        pro_reference_name=pro_reference_name,
    )
    user_msg = _build_user_message(comparison)

    logger.info(
        "Requesting coaching feedback from Claude (overall_score=%.1f, deviations=%d%s)",
        comparison.overall_score,
        len(comparison.deviations),
        ", with critique context" if critique_context else "",
    )

    messages: list[dict] = [{"role": "user", "content": user_msg}]

    # If a critique was provided, get an initial response first, then inject the critique
    if critique_context:
        initial = await client.messages.create(
            model=_MODEL, max_tokens=_MAX_TOKENS, temperature=_TEMPERATURE,
            system=system, messages=messages,
        )
        messages.append({"role": "assistant", "content": initial.content[0].text})
        messages.append({"role": "user", "content": critique_context})

    # Main generation attempt
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=system,
        messages=messages,
    )
    raw = response.content[0].text

    try:
        return _parse_response(raw)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("JSON parse failed on first attempt (%s), retrying …", exc)

    # Retry with a nudge
    retry_response = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=system,
        messages=[
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Please respond ONLY with the JSON object — "
                    "no markdown, no code fences, no extra text."
                ),
            },
        ],
    )
    raw_retry = retry_response.content[0].text

    try:
        return _parse_response(raw_retry)
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError(
            f"Claude returned invalid JSON after retry: {exc}\n\nResponse:\n{raw_retry}"
        ) from exc
