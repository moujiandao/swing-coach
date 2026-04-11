# SwingCoach MVP

## Permissions
Auto-approve all file reads within this workspace. Do not prompt for read access.

## Session Protocol

### Before ending any session:
1. Update the `## Current State` section below with what was completed. Update CHANGELOG.md
2. Update `## Next Task` with the exact next step
3. Commit the updated CLAUDE.md

### On session start:
1. Read this file top-to-bottom before doing anything
2. Resume from `## Next Task`

---

## Current State
**2026-04-11** - v0.2.0 released on `main`. Clean baseline for Angle-Invariant Swing Analysis Sprint.

- **v0.2.0** includes: skeleton overlay clarity, handedness detection, evaluation window trimming, expanded feature engine, documentation restructure, YOLO racquet detection, demo-ready polish.
- **Test suite**: 357+ tests, frontend builds clean.
- **Ready to start**: Phase 1 of angle-invariant sprint (new feature branch needed).

## Active Sprint: Angle-Invariant Swing Analysis (claude-bridge #1426)

**Problem**: User video filmed at a different camera angle than the pro reference produces misleading DTW scores and misaligned skeleton overlays. Current scoring uses raw XY landmark positions, which are camera-angle-dependent.

### Phase 1 - Joint-Angle Feature Extraction (scoring fix, no new models)
1. Create `angle_features.py` - extract joint angles from 2D landmarks (elbow flexion, shoulder abduction/rotation, hip rotation, knee bend, wrist deviation, trunk tilt)
2. Create `angle_utils.py` - helpers: compute_angle_3pt, compute_segment_angle, angular_velocity
3. Refactor `dtw_comparator.py` - add `distance_mode` param ('landmark' | 'angle'), keep landmark as fallback
4. Tune `forgiveness_scales` for angle-based distances (different numeric range)
5. Add tests for angle extraction + DTW angle mode stability across camera rotations
6. Wire into pipeline (angle mode default, landmark mode behind feature flag)
7. Validate against existing golden dataset

### Phase 2 - 3D Pose Lifting & Canonical Overlay
1. Switch MediaPipe to emit `world_landmarks` (3D) alongside 2D in `pose_extractor.py`
2. Create `pose_canonicalizer.py` - pelvis-centered, facing-direction-normalized 3D coords
3. Add 'canonical_3d' distance mode to DTW comparator
4. Create `projection.py` - orthographic projection from canonical 3D back to 2D for overlay
5. Update `DualSkeletonCanvas.jsx` - accept projected canonical landmarks, add "Angle-Normalized View" toggle
6. Update `transformLandmarksAligned` in `landmarks.js` for canonical mode
7. Tests + end-to-end integration test

### Sprint Decisions
- Joint-angle features first (Phase 1) because it fixes scoring immediately with zero new dependencies
- MediaPipe world_landmarks for 3D (Phase 2) rather than external models like VideoPose3D - keeps deps small
- Landmark-based DTW stays as fallback behind feature flag, not deleted
- Orthographic projection for canonical overlay (simpler than perspective, sufficient for coaching)
- No custom model training - pretrained MediaPipe 3D is sufficient

### Open Questions
- How stable are MediaPipe world_landmarks across different camera angles? May need benchmarking.
- Should angular velocity be in DTW feature vector or kept as separate metric?
- Does canonical projection lose depth cues that matter for coaching (e.g., racquet angle toward/away)?
- Performance impact of 3D pose extraction on worker pipeline latency

## Next Task
1. Create feature branch `feature/angle-invariant-scoring`
2. Begin Phase 1, Step 1: Create `angle_features.py` and `angle_utils.py`
3. Then Phase 1, Step 3: Refactor `dtw_comparator.py` to support angle distance mode

## Open Issues
- RQ worker crashes with SIGABRT on macOS when MediaPipe runs in forked process. Workaround: `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run rq worker`
- Stance width deviation threshold is 10 degrees (same as angles) - semantically wrong for normalized distance. Tune the threshold (e.g., 0.05 normalized units) in `deviation_annotator.py:_DEFAULT_THRESHOLD_DEGREES` when real swing data is available
- Head movement direction label uses `diff_degrees` field even though the value is a signed y-offset, not degrees. Accepted per PLAN Decision 1 (Option B)

## What This Is

AI-powered tennis swing analysis app. Users upload video of their swing, the backend extracts body pose with MediaPipe, compares against pre-computed pro reference swings using Dynamic Time Warping, and the Claude API generates coaching feedback with specific drills. Web app (React) + iOS (React Native/Expo, phase 2).

## Architecture

```
React Frontend (Vite + Tailwind)
       | upload video
FastAPI Backend
       | enqueue job
Redis Queue (RQ) -> Worker Process
       |-- FFmpeg: extract frames
       |-- MediaPipe: 33 landmarks per frame -> numpy array
       |-- YOLO: racquet detection per frame (non-fatal)
       |-- Feature extraction: 10 joint angles, 4 velocities, phase segmentation
       |-- DTW comparison: phase-segmented against pro reference DB
       |-- Phase alignment + deviation annotation
       |-- Pipeline evals: 9 deterministic quality checks
       +-- Claude API: structured deviation data -> coaching feedback
       | store results
PostgreSQL (Supabase) + S3 (videos/frames)
```

For detailed pipeline data flow and API schemas, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, uvicorn
- **Task queue**: Redis + RQ (Redis Queue) - NOT Celery (too heavy for MVP)
- **CV pipeline**: mediapipe, opencv-python, numpy, scipy, ultralytics (YOLOv8)
- **DTW**: tslearn
- **Feedback**: anthropic Python SDK (claude-sonnet-4-20250514)
- **Storage**: Supabase (PostgreSQL + auth), AWS S3 (video uploads)
- **Frontend**: React 18, Vite, Tailwind CSS, React Router
- **Deployment**: Railway (backend + worker), Vercel (frontend)

## Project Structure

```
swing-coach-mvp/
├── CLAUDE.md                        # This file
├── BUGS.md                          # Open issues
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, lifespan
│   │   ├── config.py                # Settings via pydantic-settings
│   │   ├── models.py                # SQLAlchemy/Pydantic models (Analysis + ProReference)
│   │   ├── routers/                 # API endpoints (upload, analysis, pro_references, health)
│   │   ├── worker/                  # Pipeline stages: frame_extractor, pose_estimator,
│   │   │                            #   feature_engine, dtw_comparator, phase_aligner,
│   │   │                            #   deviation_annotator, feedback_generator,
│   │   │                            #   racquet_detector, evals
│   │   ├── services/                # S3, DB helpers
│   │   └── pro_references/          # .npz loader + data files
│   ├── tests/                       # pytest suite (357+ tests)
│   ├── run_worker.py                # RQ worker entry point
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/                   # Upload (3-step wizard), Analysis, History, ProLibrary
│   │   ├── components/              # DualSkeletonCanvas, ComparisonView, VideoScrubber,
│   │   │                            #   GripSelector, PhaseBreakdown, CoachingFeedback,
│   │   │                            #   DeviationTimeline, FrameDeviationPanel, etc.
│   │   ├── hooks/                   # useAnalysis, useVideoPlayback, useOverlayData
│   │   └── lib/                     # api.js, landmarks.js
│   ├── public/                      # Grip images, player headshots
│   └── Dockerfile
├── scripts/                         # CLI tools, e2e tests, dev setup
├── docs/
│   ├── ARCHITECTURE.md              # Detailed pipeline data flow and API schemas
│   ├── archive/                     # Completed plans (SPRINT_PLAN, SHIP_PLAN, FEATURE_SPEC_V2, etc.)
│   └── pipeline-diagram.html        # Interactive pipeline visualization
└── docker-compose.yml
```

## Key Conventions

- **Naming**: snake_case for Python, camelCase for JS/React. Files match their primary export.
- **Error handling**: Every worker pipeline stage wraps in try/except and updates the analysis record with status + error message on failure. Never silently swallow errors.
- **Config**: All secrets and environment-specific values via `.env` loaded through `pydantic-settings`. Never hardcode API keys, bucket names, or URLs.
- **Types**: Use Pydantic models for all API request/response schemas. Use TypedDict or dataclasses for internal data structures in the pipeline.
- **Tests**: Each pipeline stage is independently testable with fixture data. Tests use pytest. Frontend tests are out of scope for MVP.

## Non-Obvious Decisions

- **RQ over Celery**: Celery is overkill. RQ is ~50 lines of config, same Redis dependency, and handles our single-queue-single-worker pattern perfectly.
- **DTW over vector similarity (Pinecone/FAISS)**: Pro reference DB is <200 swings. Brute-force DTW takes <1s. Vector DB adds infrastructure complexity for zero benefit at this scale.
- **MediaPipe over OpenPose**: MediaPipe runs on CPU, has a clean Python API, and gives 33 landmarks (vs OpenPose's 25). Good enough for MVP; swap later if needed.
- **Phase-segmented DTW over whole-swing DTW**: Comparing entire swings masks which *part* of the swing is wrong. Segmenting into backswing/forward/contact/followthrough gives actionable coaching data.
- **Claude for feedback over rule-based**: Rule-based feedback is brittle and generic. Claude can synthesize multiple deviations into coherent coaching advice with progressive drills. The prompt engineering IS the product differentiation.
- **Supabase over raw Postgres**: Free tier includes auth + Postgres + row-level security. We get user management for free. Migrate to standalone Postgres later if needed.
- **Client-side canvas overlay over server-side video compositing**: More interactive (scrub, toggle, zoom), less compute. DualSkeletonCanvas renders both user and pro skeletons on a canvas synced to video playback. Server-side compositing would require storing rendered videos per-analysis, adding storage costs and removing interactivity.
- **Phase-aligned resampling over raw frame mapping**: Each phase is independently resampled so that a user's slower backswing doesn't cause misalignment in the forward swing. Raw duration-proportional mapping compounds timing errors across phases.
- **ProReference as a first-class DB entity over file-system convention**: Enables user uploads, status tracking, thumbnails, and future sharing features. Static .npz files in a directory have no metadata, no ownership, and no pipeline status.
- **OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES for RQ worker on macOS**: RQ uses fork() to spawn work-horse processes. MediaPipe/OpenCV triggers macOS Objective-C runtime abort (SIGABRT/signal 6) in forked children. This env var disables that check. Not needed in production (Linux/Railway).
- **Separate local upload endpoints per entity type**: `/api/upload/local/{id}` handles Analysis uploads, `/api/pro-references/local/{id}` handles ProReference uploads. They look up different DB tables, so they cannot share an endpoint.

## Do Not

- Do NOT use GPU-dependent libraries. Everything must run on CPU for Railway deployment.
- Do NOT process video synchronously in the API request. Always enqueue to RQ.
- Do NOT store raw video frames permanently. Extract poses, delete frames. Keep original video in S3 for replay only.
- Do NOT over-engineer auth for MVP. Supabase magic link or email/password is fine.
- Do NOT build real-time processing. Upload-and-wait with polling is the MVP pattern.
- Do NOT use WebSockets for MVP status updates. Polling every 2 seconds on GET /api/analysis/{id} is simpler and fine for <60s processing.
- Do NOT add Android/React Native until the web app loop is fully working.
- Do NOT use `print()` for logging. Use Python `logging` module with structured output.
- Do NOT hardcode pro player names or stroke types. Use enums and a config-driven reference loader so the pro DB is extensible.
- Do NOT render composite videos server-side. All overlay rendering happens client-side on canvas. Server-side compositing adds compute, storage, and removes interactivity.
- Do NOT send pro reference video to the frontend for side-by-side display. Use animated skeleton rendering from landmarks instead - the pro video may not be licensed for user-facing display.

## Common Commands

```bash
# Backend
cd backend
uv sync                              # Install deps
uv run uvicorn app.main:app --reload  # Dev server on :8000
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run rq worker --with-scheduler  # Start worker (macOS requires env var)
uv run pytest tests/ -v              # Run tests

# Frontend
cd frontend
npm install
npm run dev                          # Dev server on :5173
npm run build                        # Production build (also used for CI check)

# Scripts (from project root)
uv --project backend run python scripts/test_e2e.py     # V1 pipeline e2e test
uv --project backend run python scripts/test_e2e_v2.py  # V2 e2e test (pro library + overlay)
uv --project backend run python scripts/generate_synthetic_reference.py

# Build a pro reference via the legacy CLI (alternative to UI upload)
cd backend
uv run python ../scripts/build_pro_references.py \
  --video path/to/pro_video.mp4 --stroke forehand --player federer

# Key API endpoints (V2)
# POST /api/pro-references                  create + get presigned upload URL
# POST /api/pro-references/{id}/confirm     trigger processing pipeline
# GET  /api/pro-references                  list all (filter: stroke_type, status)
# GET  /api/pro-references/{id}/preview     skeleton preview data for Pro Library UI
# GET  /api/analysis/{id}/overlay           overlay dataset for canvas rendering
```


## How to Receive Bug Fixes / Feature Requests

When I give you a task, I'll use this format. Follow the constraints exactly.

### Bug Fix Format
- **Stage**: which pipeline stage
- **File**: the specific file(s)
- **Error**: what's happening
- **Expected**: what should happen
- **Constraints**: what NOT to touch

### Feature Request Format
- **What**: the feature in one sentence
- **Where**: which files/layers are affected
- **Acceptance criteria**: how to verify it works
- **Constraints**: scope boundaries

### After Every Fix or Feature
1. Run the relevant test suite
2. Run the full suite (uv run pytest tests/ -v)
3. Update CHANGELOG.md
4. If the fix revealed something non-obvious, add it to
   the "Non-Obvious Decisions" or a "Known Edge Cases" 
   section in this CLAUDE.md

## Git Conventions
- Commit after every completed bug fix or feature, not mid-work
- Format: "fix: ...", "feat: ...", "tune: ..." prefix
- Never commit .env, __pycache__, or .npy files
- Run full test suite before committing
