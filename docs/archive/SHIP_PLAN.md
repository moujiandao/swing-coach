# SHIP_PLAN.md — SwingCoach MVP Demo-Ready

**Goal:** Working locally end-to-end, polished enough to record a portfolio demo video.  
**Demo money shot:** Upload video → skeleton overlay on video → read coaching feedback with drills.  
**Not required for ship:** Deployment (Railway/Vercel), auth, mobile, ComparisonView with pro overlay.  
**Branch strategy:** Gate 0 on `main`. Agents B and C on worktrees, merge back for Gate 3.

---

## Gate 0: Merge & Diagnose (Brian, manual, ~2 hours)

This gate is sequential and requires your eyes. No agent can do this.

### 0.1 Merge and baseline
- [ ] Merge `feature/pro-reference-v2` → `main`
- [ ] `cd backend && uv run pytest tests/ -v` — confirm 298 tests still pass
- [ ] `cd frontend && npm run build` — confirm clean build
- **AC:** Green across the board on main.

### 0.2 Real video pipeline run
- [ ] Start full stack locally (redis, backend, worker, frontend)
- [ ] Upload a real tennis swing video through the UI
- [ ] Let the pipeline complete (FFmpeg → MediaPipe → DTW → Claude feedback)
- [ ] **Document every issue you see** in a new file: `BUGS.md`
- **AC:** Pipeline runs start-to-finish without crashing. BUGS.md exists with categorized issues.

### 0.3 Diagnose skeleton alignment
Run the pipeline, then inspect the Analysis page. For each issue, note which category:

| Symptom | Likely root cause | How to confirm |
|---|---|---|
| Skeleton floats above/below the person | Canvas coordinate transform doesn't match video dimensions | Resize browser window — if skeleton shifts relative to video, it's a scaling bug in `SkeletonOverlay.jsx` |
| Joints are in roughly right positions but connections cross wrong body parts | `landmark_connections` bone pair indices are wrong in `models.py` | Print the connection pairs and compare to MediaPipe's documented skeleton topology |
| Skeleton is correct on some frames, drifts on others | MediaPipe confidence drops on fast motion frames → noisy landmarks | Check `pose_estimator.py` — are you filtering on landmark visibility/confidence? |
| Pro skeleton drifts relative to user skeleton over time | Phase alignment resampling accumulates error | Compare `frame_mapping` values — do the phase boundaries match? |

- [ ] Categorize the skeleton issue in BUGS.md with root cause hypothesis
- [ ] If it's a canvas scaling bug: note the specific component and the mismatch (video resolution vs canvas dimensions vs landmark coordinate space)
- **AC:** Root cause identified with enough specificity for an agent to fix it.

### 0.4 Catalog coaching feedback quality
- [ ] Read the Claude-generated coaching feedback for your real swing
- [ ] Note in BUGS.md:
  - Which phase scores feel inaccurate and in which direction (too high? too low?)
  - Which drill recommendations don't make sense biomechanically
  - What a good coach (you) would actually say differently
  - Write 3-5 bullet points of your coaching philosophy that Claude is missing
- [ ] Run `scripts/eval_feedback_quality.py --analysis-id <uuid>` — note the rubric scores
- **AC:** BUGS.md has a "Coaching Quality" section with specific, actionable critique.

### 0.5 Write BUGS.md
The output of Gate 0 is a single file that becomes the task backlog for Agents B and C.

```markdown
# BUGS.md

## Skeleton Alignment
- Root cause: [canvas scaling | bone pairs | MediaPipe noise | phase drift]
- Specific files: [which files]
- Reproduction: [exact steps]

## Phase Score Accuracy
- Which phases are off: [list]
- Direction: [scoring too high / too low / inconsistent]
- Suspected cause: [DTW threshold | feature extraction | phase boundaries]

## Coaching Feedback Quality
- Missing coaching philosophy: [your bullets]
- Bad drill recommendations: [specific examples]
- Tone/style issues: [too generic / wrong level / etc.]

## Frontend Polish
- [ ] [specific UI issues you noticed during the real video test]

## Other Bugs
- [ ] [anything else from your recent chat-based fixes that isn't in CLAUDE.md]
```

- **AC:** BUGS.md is specific enough that an agent reading it + CLAUDE.md can fix each item without asking you questions.

---

## Agent B: Frontend Polish (Claude Code worktree)

**Scope:** `frontend/src/` only. Cannot modify backend code.  
**Stop hook:** `cd frontend && npm run build && npm run lint`  
**Worktree:** `git worktree add ../swing-coach-frontend feature/frontend-polish`

These tasks target only the pages visible in the demo video: Upload and Analysis.

### B.1 Fix skeleton overlay alignment
- [ ] Fix the root cause identified in Gate 0.3
- [ ] Skeleton lines align with the person in the video across the full swing
- [ ] Test at multiple video resolutions (1080p, 720p, phone vertical)
- **AC:** Skeleton tracks the person accurately on the real test video. No drift, no offset.
- **Depends on:** Gate 0.3 diagnosis (if root cause is backend/MediaPipe, this moves to Agent C)

### B.2 Upload page polish
- [ ] Clean drag-and-drop zone with clear affordance
- [ ] Upload progress indicator (not just a spinner)
- [ ] Processing status with stage labels ("Extracting frames..." → "Analyzing pose..." → "Generating feedback...")
- [ ] Error state if upload fails or video is too long/large
- **AC:** Upload flow feels professional, not prototype-y. No console errors.

### B.3 Analysis results page polish
- [ ] Coaching feedback card with clear hierarchy: summary → priority fixes → drills → positive notes
- [ ] Phase score visualization (bar chart or radar chart — whatever's cleanest)
- [ ] Skeleton overlay toggle (show/hide)
- [ ] Overall score displayed prominently
- [ ] Responsive at 1280px and 1440px (desktop recording widths)
- **AC:** Results page looks portfolio-worthy in a screen recording.

### B.4 Loading and empty states
- [ ] Skeleton loading state while analysis processes (not a blank page)
- [ ] "No analyses yet" state on History page
- [ ] Smooth transition from processing → results
- **AC:** No blank screens, no layout jumps during the demo flow.

---

## Agent C: Analysis Quality Tuning (Claude Code worktree)

**Scope:** `backend/` only. Cannot modify frontend code.  
**Stop hook:** `cd backend && uv run pytest tests/ -v`  
**Worktree:** `git worktree add ../swing-coach-backend feature/analysis-tuning`

This is the hardest and most important workstream. The demo lives or dies on whether the coaching feedback sounds like a real coach.

### C.1 Fix known open issues
- [ ] Tune stance_width deviation threshold from 10° to 0.05 normalized units in `deviation_annotator.py`
- [ ] Fix head_movement direction label to use correct field semantics (per CLAUDE.md open issue)
- [ ] Any other bugs cataloged in BUGS.md "Other Bugs" section
- **AC:** All CLAUDE.md open issues resolved. Tests pass.

### C.2 Tune phase scores (if identified as inaccurate in Gate 0.4)
- [ ] Review DTW scoring in `dtw_comparator.py` — are the phase-level scores on a meaningful scale?
- [ ] If scores cluster too tightly (e.g., everything is 60-75): adjust normalization or scoring curve
- [ ] If specific phases always score wrong: check `feature_engine.py` phase boundary detection for that stroke type
- [ ] Add at least 2 assertions in tests that validate score ranges for the synthetic reference
- **AC:** Phase scores for the real test video match Brian's expert assessment within ±10 points.
- **Depends on:** Gate 0.4 specifics.

### C.3 Tune coaching feedback prompt
This is the product differentiator. The prompt in `feedback_generator.py` needs Brian's coaching voice.

- [ ] Inject Brian's coaching philosophy bullets (from BUGS.md) into the Claude system prompt
- [ ] Add a `coaching_context` field to the feedback request that accepts optional per-swing notes
- [ ] Structure the prompt to prioritize:
  1. The single most important thing to fix (not a laundry list)
  2. A specific drill with rep count and focus cue
  3. What the player is doing well (reinforcement)
- [ ] Add guardrails: drills must be physically possible, cues must reference body parts not abstract concepts
- [ ] Run `eval_feedback_quality.py` after changes — scores should improve
- **AC:** Claude's feedback for the real test video reads like something Brian would actually say to a student. Drill recommendations are biomechanically sound.

### C.4 Skeleton data quality (if Gate 0.3 points to backend)
- [ ] If MediaPipe landmarks are noisy: add confidence filtering in `pose_estimator.py` (drop landmarks below threshold, interpolate)
- [ ] If phase alignment drifts: review `phase_aligner.py` resampling logic
- [ ] If bone connections are wrong: fix `landmark_connections` in `models.py` against MediaPipe's BlazePose topology
- **AC:** Landmarks exported via `/api/analysis/{id}/overlay` are clean enough for the frontend to render accurately.
- **Depends on:** Gate 0.3 diagnosis. Skip if root cause is purely frontend.

---

## Gate 3: Integration & Demo Prep (Brian, manual, ~1-2 hours)

### 3.1 Merge and resolve
- [ ] Merge `feature/frontend-polish` → `main`
- [ ] Merge `feature/analysis-tuning` → `main`
- [ ] Resolve any conflicts (should be minimal — agents touched different directories)
- [ ] `uv run pytest tests/ -v` — all green
- [ ] `npm run build` — clean
- **AC:** Main branch has all changes, no regressions.

### 3.2 Final real-video validation
- [ ] Run full pipeline with the same real video from Gate 0
- [ ] Verify: skeleton aligns, scores feel right, feedback sounds like you
- [ ] If anything is off: create a targeted fix task, do NOT loop back to the agents
- **AC:** You'd be comfortable showing this to a fellow tennis coach.

### 3.3 Record demo video
- [ ] Screen record the full flow: open app → upload video → watch processing → view results
- [ ] Optionally: voiceover explaining what the app does and why the feedback is meaningful
- [ ] Export as MP4 for portfolio site / LinkedIn / GitHub README
- **AC:** Demo video exists and makes you look like someone who ships.

---

## What's Explicitly Deferred

These are real features but they don't make the demo video better. Cut them ruthlessly.

| Feature | Why deferred |
|---|---|
| Feedback rating UI (rate/correct Claude's output) | Valuable for V2 quality loop, but for MVP just tune the prompt directly |
| ComparisonView with pro overlay | Demo only needs single-skeleton overlay + coaching text |
| Deployment to Railway/Vercel | Demo is a screen recording, not a live URL |
| Auth / user accounts | Single-user local demo |
| Pro Library upload UI polish | Demo can use pre-loaded synthetic or CLI-built reference |
| `ENABLE_LLM_EVAL_REPAIR=true` in production | No production yet |
| Mobile responsive | Screen recording will be at desktop resolution |
| History page polish beyond empty state | Demo shows one analysis, not a history |

---

## Execution Checklist

```
Day 1 (you, ~2-3 hrs)
├── Gate 0: Merge, run real video, diagnose, write BUGS.md
├── Create worktrees
├── Write agent prompts referencing CLAUDE.md + SHIP_PLAN.md + BUGS.md
└── Launch Agent B and Agent C in parallel Claude Code sessions

Day 2 (agents run, you review, ~1-2 hrs active)
├── Review Agent B PR (frontend polish)
├── Review Agent C PR (analysis tuning)
├── Request changes if needed (be specific, not "make it better")
└── Agents iterate on feedback

Day 3 (you, ~1-2 hrs)
├── Gate 3: Merge, final validation, record demo
└── Ship it
```

## Agent Launch Prompts

### Agent B prompt:
```
Read CLAUDE.md and SHIP_PLAN.md (Gates B.1-B.4). Read BUGS.md for the 
skeleton alignment diagnosis and frontend issues.

You own frontend polish. Execute tasks B.1 through B.4 in order.
After each task, run: npm run build && npm run lint
Do not modify any files in backend/.
Commit after each completed task with prefix "polish: ..."
```

### Agent C prompt:
```
Read CLAUDE.md and SHIP_PLAN.md (Gates C.1-C.4). Read BUGS.md for the 
phase score issues and coaching feedback critique.

You own analysis quality. Execute tasks C.1 through C.4 in order.
After each task, run: uv run pytest tests/ -v
Do not modify any files in frontend/.
Commit after each completed task with prefix "tune: ..."
```
