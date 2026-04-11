# Architecture - SwingCoach MVP

Detailed pipeline data flow and API schema reference. For project conventions, session state, and common commands, see [CLAUDE.md](../CLAUDE.md).

---

## Pro Reference Upload Pipeline

```
User uploads pro video via Pro Library UI
  |
POST /api/pro-references -> create ProReference record (status=pending) + presigned S3 URL
  |
POST /api/pro-references/{id}/confirm -> enqueue RQ job (status=processing)
  |
RQ Worker (pro_reference_tasks.py):
  FFmpeg -> frames
  MediaPipe -> landmarks (N, 33, 3)
  YOLO racquet detection -> per-frame racquet positions (non-fatal)
  Feature Engine -> joint_angles, velocities, phases
  cv2 -> thumbnail JPEG -> S3
  np.savez -> .npz (landmarks + features + racquet + metadata) -> local data/ dir
  DB update -> status=ready, npz_path, frame_count, fps
```

---

## Analysis Pipeline (full flow with overlay)

```
Input: MP4/MOV video (max 30s, ideally 120fps slow-mo)
  |
FFmpeg -> frames/ directory (PNG files at native FPS)
  |
MediaPipe -> pose_landmarks: np.ndarray, shape (num_frames, 33, 3)
             detection_mask: bool array (real detections vs interpolated)
  |
YOLO Racquet Detection (non-fatal) ->
  racquet_data: list[dict]  # per-frame bbox, centerline base/tip endpoints
  |
Feature Engine ->
  joint_angles: dict[str, np.ndarray]  # per-joint angle timeseries
    keys: elbow_angle, shoulder_rotation, hip_rotation, knee_bend,
          racket_arm_elevation, trunk_rotation, left_elbow_angle,
          left_arm_elevation, stance_width, head_movement
  velocities: dict[str, np.ndarray]    # per-joint velocity timeseries
    keys: wrist_speed, elbow_speed, hip_speed, wrist_acceleration
  phases: dict[str, tuple[int, int]]   # frame ranges per phase
    keys: preparation, backswing, forward_swing, contact, follow_through
  | (keyframe JPEGs extracted at phase boundaries -> S3)
  |
Pro Reference Loader -> load .npz (DB-backed path or filesystem fallback)
  |
DTW Comparator ->
  overall_score: float (0-100, higher = more similar to pro)
  phase_scores: dict[str, float]       # per-phase similarity + "base" for lower body
  deviations: list[Deviation]          # ranked list of biggest differences
    Deviation: {joint, phase, angle_diff, timing_diff, description}
  |
Phase Aligner (phase_aligner.py) ->
  frame_mapping: list[int]             # user_frame -> pro_frame (per-phase linear interp)
  phase_boundaries: dict[str, PhaseBoundary]  # tempo_ratio per phase
  aligned_pro_landmarks: np.ndarray    # pro landmarks resampled to user frame count
  |
Deviation Annotator (deviation_annotator.py) ->
  frame_deviations: list[FrameDeviation]  # per-frame joint annotations (severity, direction)
  |
Pipeline Evals (evals.py) ->
  9 deterministic checks (feature completeness, score bounds, frame consistency,
  phase coverage, schema completeness, fix alignment, numeric values,
  severity ordering, drill-fix linkage)
  |
Claude Feedback (feedback_generator.py) ->
  summary: str                         # 2-3 sentence overview
  overall_assessment: str              # rating tier
  priority_fixes: list[Fix]            # top 3 things to work on
    Fix: {title, explanation, target_metric, current_value, target_value, drill}
  positive_notes: list[str]            # what's going well
  drill_plan: list[Drill]             # structured drill recommendations
  eval_passed: bool                    # pipeline eval result
  eval_issues: list[str]              # any failing checks
  |
DB write: pose_data, aligned_pro_landmarks, frame_mapping, frame_deviations,
          phase_boundaries, fps, keyframe_s3_keys, coaching_feedback,
          racquet_data, detection_mask
```

---

## Overlay Endpoint (GET /api/analysis/{id}/overlay)

```
DB -> Analysis record
  |
Return OverlayResponse:
  user_landmarks: list[frame][landmark][x,y,z]
  pro_landmarks: list[frame][landmark][x,y,z]   # phase-aligned, same frame count
  frame_mapping: list[int]
  frame_deviations: list[FrameDeviation]
  phase_boundaries: dict[str, PhaseBoundary]
  fps: float
  landmark_connections: list[list[int]]          # 16 bone pairs (body + head connections)
  video_url: str | None                          # presigned S3 URL
  keyframe_urls: dict[str, str] | None           # phase -> presigned S3 URL
  racquet_data: list[dict] | None                # per-frame YOLO racquet positions
  pro_racquet_data: list[dict] | None            # pro reference racquet positions
  detection_mask: list[bool] | None              # true = real detection, false = interpolated
```

---

## Key Data Structures

### FeatureExtractionResult
- `joint_angles`: 10 keys (see pipeline above)
- `velocities`: 4 keys (see pipeline above)
- `phases`: 5 keys (preparation, backswing, forward_swing, contact, follow_through)
- `contact_frame`: int

### LANDMARK_CONNECTIONS (models.py)
16 bone pairs for skeleton rendering:
- 12 body connections (shoulders, elbows, wrists, hips, knees, ankles, torso)
- 4 head connections (nose-ears, ears-shoulders)

### Coaching Feedback (Claude API structured output)
The feedback prompt includes 4 golden rules of tennis technique and real drill methodology.
An optional `critique_context` param enables the LLM-as-judge self-repair loop
(see `scripts/eval_feedback_quality.py`).
