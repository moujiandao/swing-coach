"""
Deterministic pipeline eval harness — Track B.

Runs 9 structural checks on pipeline output after Claude feedback is generated.
Zero LLM cost: all checks are rule-based. Results are stored in coaching_feedback
as eval_passed / eval_issues.
"""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_EXPECTED_JOINT_KEYS = {
    "elbow_angle", "shoulder_rotation", "hip_rotation", "trunk_rotation",
    "knee_bend", "racket_arm_elevation",
    "left_elbow_angle", "left_arm_elevation", "stance_width", "head_movement",
}

_EXPECTED_PHASES = {
    "preparation", "backswing", "forward_swing", "contact", "follow_through",
}

_VALID_ASSESSMENTS = {"beginner", "intermediate", "advanced", "pro-level"}

_SEVERITY_ORDER = {"critical": 0, "moderate": 1, "minor": 2}


@dataclass
class EvalResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    score: int = 0          # number of checks passed
    total: int = 9


def run_pipeline_evals(
    features,             # FeatureExtractionResult
    comparison,           # ComparisonResult
    feedback: dict,       # asdict(CoachingFeedback) — already serialized
    frame_deviations: list | None,
    frame_mapping: list | None,
    num_user_frames: int,
) -> EvalResult:
    """
    Run 9 deterministic checks on a completed pipeline result.

    Returns EvalResult with passed=True only if all checks pass.
    Issues contains human-readable descriptions of each failure.
    """
    issues: list[str] = []
    passed_count = 0

    # --- Check 1: Feature completeness ---
    missing_keys = _EXPECTED_JOINT_KEYS - set(features.joint_angles.keys())
    if missing_keys:
        issues.append(f"Check 1 (feature completeness): missing joint keys: {sorted(missing_keys)}")
    else:
        passed_count += 1

    # --- Check 2: Score bounds ---
    score_ok = True
    overall = comparison.overall_score
    if not (0 <= overall <= 100):
        issues.append(f"Check 2 (score bounds): overall_score={overall:.2f} outside [0, 100]")
        score_ok = False
    for phase, score in comparison.phase_scores.items():
        if not (0 <= score <= 100):
            issues.append(f"Check 2 (score bounds): phase_score[{phase}]={score:.2f} outside [0, 100]")
            score_ok = False
    if score_ok:
        passed_count += 1

    # --- Check 3: Frame consistency ---
    if frame_mapping is None:
        # No frame mapping generated (pro landmarks unavailable) — skip gracefully
        passed_count += 1
    elif len(frame_mapping) != num_user_frames:
        issues.append(
            f"Check 3 (frame consistency): frame_mapping length {len(frame_mapping)} "
            f"!= num_user_frames {num_user_frames}"
        )
    else:
        passed_count += 1

    # --- Check 4: Phase coverage ---
    missing_phases = _EXPECTED_PHASES - set(comparison.phase_scores.keys())
    if missing_phases:
        issues.append(f"Check 4 (phase coverage): missing phases in phase_scores: {sorted(missing_phases)}")
    else:
        passed_count += 1

    # --- Check 5: Schema completeness ---
    schema_ok = True
    summary = feedback.get("summary", "")
    if not summary or not summary.strip():
        issues.append("Check 5 (schema): summary is empty")
        schema_ok = False
    assessment = feedback.get("overall_assessment", "")
    if assessment not in _VALID_ASSESSMENTS:
        issues.append(f"Check 5 (schema): overall_assessment='{assessment}' not in {_VALID_ASSESSMENTS}")
        schema_ok = False
    if not feedback.get("priority_fixes"):
        issues.append("Check 5 (schema): priority_fixes is empty")
        schema_ok = False
    if schema_ok:
        passed_count += 1

    # --- Check 6: Fix alignment (target_metric references a real deviation joint) ---
    deviation_joints = {d.joint for d in comparison.deviations}
    fix_alignment_ok = True
    if deviation_joints:
        # Build the set of all words that appear in any detected deviation joint name
        joint_words: set[str] = set()
        for j in deviation_joints:
            joint_words.update(j.replace("_", " ").split())
        for fix in feedback.get("priority_fixes", []):
            target = fix.get("target_metric", "")
            target_words = set(target.replace("_", " ").split())
            if not (target_words & joint_words):
                issues.append(
                    f"Check 6 (fix alignment): fix '{fix.get('title', '?')}' "
                    f"target_metric='{target}' matches no deviation joint in {sorted(deviation_joints)}"
                )
                fix_alignment_ok = False
    # No deviations → pass vacuously (nothing to align against)
    if fix_alignment_ok:
        passed_count += 1

    # --- Check 7: Numeric values in fixes ---
    numeric_ok = True
    for fix in feedback.get("priority_fixes", []):
        for field_name in ("current_value", "target_value"):
            val = fix.get(field_name, "")
            if not any(ch.isdigit() for ch in val):
                issues.append(
                    f"Check 7 (numeric values): fix '{fix.get('title', '?')}' "
                    f"{field_name}='{val}' contains no numeric digits"
                )
                numeric_ok = False
    if numeric_ok:
        passed_count += 1

    # --- Check 8: Deviation severity ordering (critical before moderate before minor) ---
    severity_ok = True
    deviations = comparison.deviations
    for i in range(len(deviations) - 1):
        curr_rank = _SEVERITY_ORDER.get(deviations[i].severity, 99)
        next_rank = _SEVERITY_ORDER.get(deviations[i + 1].severity, 99)
        if next_rank < curr_rank:
            issues.append(
                f"Check 8 (severity ordering): deviation[{i}] severity='{deviations[i].severity}' "
                f"comes before deviation[{i+1}] severity='{deviations[i+1].severity}'"
            )
            severity_ok = False
            break  # report first violation only
    if severity_ok:
        passed_count += 1

    # --- Check 9: Drill-fix linkage (focus_area matches a fix title exactly) ---
    fix_titles = {fix.get("title", "") for fix in feedback.get("priority_fixes", [])}
    drill_ok = True
    for drill in feedback.get("drill_plan", []):
        focus = drill.get("focus_area", "")
        if focus not in fix_titles:
            issues.append(
                f"Check 9 (drill-fix linkage): drill '{drill.get('name', '?')}' "
                f"focus_area='{focus}' doesn't match any fix title in {sorted(fix_titles)}"
            )
            drill_ok = False
    if drill_ok:
        passed_count += 1

    all_passed = len(issues) == 0
    logger.info(
        "Pipeline eval complete: %d/%d checks passed, issues=%d",
        passed_count, 9, len(issues),
    )
    for issue in issues:
        logger.warning("Eval issue: %s", issue)

    return EvalResult(passed=all_passed, issues=issues, score=passed_count, total=9)
