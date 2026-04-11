# SwingCoach MVP Polish Plan
## Goal
A user uploads a swing video and gets an accurate full-body assessment comparing them to a pro — covering arm, elbow, shoulder, trunk, legs, knees, width of stance, trunk rotation, acceleration, head movement, left arm position before and after shot.

---

## Context

The existing pipeline tracks 6 joint angles (elbow, shoulder_rotation, hip_rotation, trunk_rotation, knee_bend, racket_arm_elevation) and 3 velocity metrics. It covers most of the body but is missing 4 critical metrics the user asked for: **stance width, head movement, left arm position, and acceleration**. The existing DTW comparison, deviation annotation, and Claude feedback generation will pick up new metrics automatically once added to `feature_engine.py`.

The test suite has 102 passing structural tests but **zero accuracy validation** — no golden references, no LLM-as-judge, no feedback quality checks.

This plan has 4 tracks executed in sequence (A → B → C → D).

---

## Track A: Full-Body Feature Expansion

**Files changed:** `feature_engine.py`, `deviation_annotator.py`, `models.py`

### New metrics to add to `feature_engine.py`

All use existing BlazePose landmarks already in the `(N, 33, 3)` array.

| Metric | Landmarks | Formula | Dict |
|---|---|---|---|
| `left_elbow_angle` | 11 (L shoulder), 13 (L elbow), 15 (L wrist) | `compute_angle(shoulder, elbow, wrist)` for non-hitting arm | `joint_angles` |
| `left_arm_elevation` | 13 (L elbow), 11 (L shoulder), 23 (L hip) | `compute_angle(elbow, shoulder, hip)` for non-hitting arm | `joint_angles` |
| `stance_width` | 27 (L ankle), 28 (R ankle) | `sqrt((lm27x - lm28x)² + (lm27y - lm28y)²)` — normalized distance | `joint_angles` |
| `head_movement` | 0 (nose), 11+12 midpoint | `lm[0].y - (lm[11].y + lm[12].y) / 2` — signed vertical offset | `joint_angles` |
| `wrist_acceleration` | derived | `savgol_filter(wrist_speed, ..., deriv=1)` — 2nd derivative of wrist position | `velocities` |

Implementation pattern in `feature_engine.py`:
```python
# Non-hitting arm setup (add after existing hit/front assignment)
non_hit = _L if handedness == "right" else _R

# New angle calculations (add to joint_angles dict)
left_elbow_angle   = np.array([compute_angle(non_hit_shoulder[i], non_hit_elbow[i], non_hit_wrist[i]) for i in range(n)], dtype=np.float32)
left_arm_elevation = np.array([compute_angle(non_hit_elbow[i], non_hit_shoulder[i], non_hit_hip[i])   for i in range(n)], dtype=np.float32)
stance_width       = np.sqrt((lm[:,27,0]-lm[:,28,0])**2 + (lm[:,27,1]-lm[:,28,1])**2).astype(np.float32)
head_movement      = (lm[:,0,1] - (lm[:,11,1]+lm[:,12,1])/2).astype(np.float32)

# Acceleration (add to velocities dict)
wrist_acceleration = savgol_filter(wrist_speed, window_length=_window, polyorder=_polyorder, deriv=1, delta=1.0/fps)
```

### Changes to `deviation_annotator.py`

Add 4 entries to `JOINT_LANDMARK_MAP`:
```python
"left_elbow_angle":   [11, 13],
"left_arm_elevation": [11, 13, 23],
"stance_width":       [27, 28],
"head_movement":      [0, 11, 12],
```

Add per-metric direction labels dict to avoid misleading "too_wide"/"too_narrow" for all metrics:
```python
_DIRECTION_LABELS = {
    "default":        ("too_wide", "too_narrow"),
    "stance_width":   ("too_wide", "too_narrow"),
    "head_movement":  ("too_low",  "too_high"),
}
```

Add `_angle_for_joint` branches for each new metric.

### Changes to `models.py`

Add head landmark connections to `LANDMARK_CONNECTIONS`:
```python
[0, 7],   # nose → left ear
[0, 8],   # nose → right ear  
[7, 11],  # left ear → left shoulder
[8, 12],  # right ear → right shoulder
```

### Update tests
- `test_feature_engine.py`: Update `expected` joint keys set to include all 10 keys. Add `TestNewMetrics` class with 8 new tests (stance_width distance math, head_movement zero case, left_elbow_angle right angle, left_arm_uses_opposite_side, wrist_acceleration shape).
- `test_deviation_annotator.py`: Update `expected` joint map set. Add `TestNewMetricAnnotations` with 4 new tests.

---

## Track B: Deterministic Eval Harness

**New file:** `backend/app/worker/evals.py`  
**Modified:** `backend/app/worker/tasks.py`  
**New test:** `backend/tests/test_evals.py`

### 9 deterministic checks (no LLM cost)

```python
@dataclass
class EvalResult:
    passed: bool
    issues: list[str]
    score: int  # checks passed out of total

def run_pipeline_evals(features, comparison, feedback, frame_deviations, frame_mapping, num_user_frames) -> EvalResult
```

| # | Check | Failure condition |
|---|---|---|
| 1 | Feature completeness | Any of 10 expected joint keys missing from `features.joint_angles` |
| 2 | Score bounds | `overall_score` or any `phase_score` outside `[0, 100]` |
| 3 | Frame consistency | `len(frame_mapping) != num_user_frames` |
| 4 | Phase coverage | Any of 5 phase names missing from `phase_scores` |
| 5 | Schema completeness | `summary` empty, `overall_assessment` invalid, `priority_fixes` empty |
| 6 | Fix alignment | A `priority_fix.target_metric` contains no word matching any deviation joint name |
| 7 | Numeric values in fixes | `current_value` or `target_value` contains no digit character |
| 8 | Deviation severity ordering | A lower-severity deviation appears before a higher-severity one in sorted list |
| 9 | Drill-fix linkage | A `drill.focus_area` doesn't exactly match any `fix.title` |

Integrate into `tasks.py` after step 10 (Claude feedback):
```python
eval_result = run_pipeline_evals(...)
coaching_dict["eval_passed"] = eval_result.passed
coaching_dict["eval_issues"] = eval_result.issues
logger.info("[%s] Pipeline eval: passed=%s issues=%d", analysis_id, eval_result.passed, len(eval_result.issues))
```

No DB schema change needed — `coaching_feedback` is already a JSON column.

---

## Track C: LLM-as-Judge Feedback Quality

**New file:** `scripts/eval_feedback_quality.py`  
**Modified:** `backend/app/worker/feedback_generator.py` (add optional `critique_context` param)

### Rubric (additive scoring, 0–10, passing threshold: 7)

| Sub-score | Points | Question |
|---|---|---|
| Specificity | 0–3 | Does feedback reference actual measured angles/values from the deviation data? |
| Alignment | 0–3 | Does each priority_fix correspond to an actual detected deviation joint? |
| Actionability | 0–2 | Are drills step-by-step and specific (not generic "practice more")? |
| Completeness | 0–2 | Are all critical/moderate deviations addressed in priority_fixes? |

Single Claude API call with structured rubric prompt returning:
```json
{
  "specificity_score": 0-3, "specificity_critique": "...",
  "alignment_score": 0-3,   "alignment_critique": "...",
  "actionability_score": 0-2, "actionability_critique": "...",
  "completeness_score": 0-2,  "completeness_critique": "...",
  "total_score": 0-10
}
```

### Self-repair loop

If `total_score < 7`, re-call `generate_coaching_feedback` with the critique injected as a follow-up message:
```
"Your feedback scored {N}/10. Issues: {critiques}. 
Regenerate addressing these, citing specific measured angles from the deviation data."
```

CLI invocation:
```bash
uv run python scripts/eval_feedback_quality.py --analysis-id <uuid> [--max-retries 1]
```

Output: JSON report to stdout with `original_score`, `final_score`, `attempts`, `passed`, `final_feedback`.

**Offline only by default.** Can be wired into `tasks.py` with a `ENABLE_LLM_EVAL_REPAIR=false` config flag if Brian decides to enable it in production.

---

## Track D: Frontend Polish

**Files changed:** `FrameDeviationPanel.jsx`, `ComparisonView.jsx`, `landmarks.js`  
**No change needed:** `DualSkeletonCanvas.jsx` (head connections flow from backend `LANDMARK_CONNECTIONS` automatically)

### `FrameDeviationPanel.jsx` — body region grouping
Replace flat joint list with grouped display:
```js
const BODY_REGIONS = {
  "Hitting Arm":      ["elbow_angle", "racket_arm_elevation"],
  "Non-Hitting Arm":  ["left_elbow_angle", "left_arm_elevation"],
  "Torso":            ["shoulder_rotation", "hip_rotation", "trunk_rotation"],
  "Legs & Stance":    ["knee_bend", "stance_width"],
  "Head":             ["head_movement"],
}
```
Only render region headers when that region has active deviations.

### `ComparisonView.jsx` + `landmarks.js` — stance width indicator
Add helper to `landmarks.js`:
```js
export function getStanceWidthDeviation(frameDeviations, frameIndex) { ... }
```

Small inline display below canvas:
```jsx
{stanceWidthDev != null && (
  <div className="text-xs text-gray-400 mt-1 font-mono">
    Stance: <span className={stanceWidthDev > 0 ? 'text-amber-400' : 'text-green-400'}>
      {stanceWidthDev > 0 ? '+' : ''}{stanceWidthDev.toFixed(3)} vs pro
    </span>
  </div>
)}
```

---

## Decisions Required from Brian Before Track A

**Decision 1 — Field naming for non-angle metrics**  
`diff_degrees` / `user_angle` / `pro_angle` in `JointDeviation` are misleading for `stance_width` (normalized distance) and `head_movement` (signed offset).  
- Option A: Rename globally to `diff_value` / `user_value` / `pro_value` (clean, requires frontend update)  
- Option B: Keep current names, accept semantic imprecision (zero extra work)  
- **Recommendation: Option B for now** — the display still works and correctness is unaffected.

**Decision 2 — Production self-repair**  
Should LLM-as-judge auto-repair run in the production pipeline (adds ~1 Claude call per analysis) or remain an offline-only script?  
- **Recommendation: offline-only** to start. Add `ENABLE_LLM_EVAL_REPAIR` config flag so you can toggle it.

---

## What Requires Brian to Define "Good" (not automatable)

- Threshold for "critical" stance width deviation (currently 10° maps to degrees; for normalized distance, 10° is meaningless — need to set e.g. `0.05` normalized units)
- Expected head movement range for each stroke type (forehand vs serve have very different head behavior)
- What "good" left arm position looks like per pro (Federer left arm wraps high; Nadal wraps low — the pro reference swing defines this implicitly via DTW, so this is actually handled automatically)

---

## Verification

After implementation:
1. `uv run pytest tests/ -v` — all 102 existing + ~20 new tests pass
2. Run `scripts/generate_synthetic_reference.py` then `scripts/test_e2e_v2.py` — overlay data includes all 10 joint keys
3. Run `scripts/eval_feedback_quality.py --analysis-id <uuid>` against a completed analysis — verify rubric scores print
4. Check frontend: frame deviation panel shows "Legs & Stance" and "Head" groups, head skeleton bones drawn, stance width delta visible below canvas

---

## Critical Files

| File | Change |
|---|---|
| `backend/app/worker/feature_engine.py` | Add 4 joint metrics + wrist_acceleration |
| `backend/app/worker/deviation_annotator.py` | Add 4 entries to JOINT_LANDMARK_MAP, direction labels |
| `backend/app/models.py` | Add 4 head landmark connections |
| `backend/app/worker/feedback_generator.py` | Add `extra_context` param, inject acceleration at contact |
| `backend/app/worker/tasks.py` | Call `run_pipeline_evals` after feedback step |
| `backend/app/worker/evals.py` | **New file** — 9 deterministic checks |
| `backend/tests/test_feature_engine.py` | Update expected keys, add 8 new tests |
| `backend/tests/test_deviation_annotator.py` | Update expected map, add 4 new tests |
| `backend/tests/test_evals.py` | **New file** — 9 check tests |
| `scripts/eval_feedback_quality.py` | **New file** — LLM-as-judge + self-repair |
| `frontend/src/components/FrameDeviationPanel.jsx` | Body region grouping |
| `frontend/src/components/ComparisonView.jsx` | Stance width indicator |
| `frontend/src/lib/landmarks.js` | `getStanceWidthDeviation` helper |
