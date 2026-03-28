# SwingCoach MVP

## What This Is

AI-powered tennis swing analysis app. Users upload video of their swing → backend extracts body pose with MediaPipe → compares against pre-computed pro reference swings using Dynamic Time Warping → Claude API generates coaching feedback with specific drills. Web app (React) + iOS (React Native/Expo, phase 2).

## Architecture

```
React Frontend (Vite + Tailwind)
       ↓ upload video
FastAPI Backend
       ↓ enqueue job
Redis Queue (RQ) → Worker Process
       ├── FFmpeg: extract frames
       ├── MediaPipe: 33 landmarks per frame → numpy array
       ├── Feature extraction: joint angles, velocities, phase segmentation
       ├── DTW comparison: phase-segmented against pro reference DB
       └── Claude API: structured deviation data → coaching feedback
       ↓ store results
PostgreSQL (Supabase) + S3 (videos/frames)
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, uvicorn
- **Task queue**: Redis + RQ (Redis Queue) — NOT Celery (too heavy for MVP)
- **CV pipeline**: mediapipe, opencv-python, numpy, scipy
- **DTW**: tslearn (or fastdtw for simpler API)
- **Feedback**: anthropic Python SDK (Claude claude-sonnet-4-20250514)
- **Storage**: Supabase (PostgreSQL + auth), AWS S3 (video uploads)
- **Frontend**: React 18, Vite, Tailwind CSS, React Router
- **Deployment**: Railway (backend + worker), Vercel (frontend)

## Project Structure

```
swing-coach-mvp/
├── CLAUDE.md                    # This file
├── SPRINT_PLAN.md               # Task breakdown for execution
├── FEATURE_SPEC_V2.md           # V2 feature spec (Pro Library + Overlay)
├── backend/
│   ├── pyproject.toml           # Dependencies (use uv)
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, lifespan
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── models.py            # SQLAlchemy/Pydantic models (Analysis + ProReference)
│   │   ├── routers/
│   │   │   ├── upload.py        # POST /api/upload (presigned URL + job enqueue)
│   │   │   ├── analysis.py      # GET /api/analysis/{id}, /overlay, GET /api/history
│   │   │   ├── pro_references.py # CRUD + confirm + preview + reprocess for ProReference
│   │   │   └── health.py        # GET /api/health
│   │   ├── worker/
│   │   │   ├── tasks.py              # RQ task: full analysis pipeline
│   │   │   ├── pro_reference_tasks.py # RQ task: pro reference build pipeline
│   │   │   ├── frame_extractor.py    # FFmpeg frame extraction
│   │   │   ├── pose_estimator.py     # MediaPipe pose extraction
│   │   │   ├── feature_engine.py     # Joint angles, velocities, phase segmentation
│   │   │   ├── dtw_comparator.py     # DTW comparison against pro DB
│   │   │   ├── phase_aligner.py      # Phase-aligned frame mapping (user ↔ pro)
│   │   │   ├── deviation_annotator.py # Per-frame joint deviation annotation
│   │   │   └── feedback_generator.py # Claude API coaching feedback
│   │   ├── services/
│   │   │   ├── s3.py            # S3 upload/download helpers
│   │   │   └── db.py            # Database session management
│   │   └── pro_references/
│   │       ├── loader.py        # Load pre-computed pro pose data (.npz)
│   │       └── data/            # .npz files of pro swing landmarks
│   └── tests/
│       ├── test_pose_estimator.py
│       ├── test_feature_engine.py
│       ├── test_dtw_comparator.py
│       ├── test_phase_aligner.py
│       ├── test_deviation_annotator.py
│       ├── test_pro_references.py   # API endpoint tests
│       └── fixtures/            # Sample video clips for testing
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── pages/
│   │   │   ├── Upload.jsx       # Video upload with pro reference picker
│   │   │   ├── Analysis.jsx     # Results display (skeleton + overlay + feedback)
│   │   │   ├── History.jsx      # Past analyses list
│   │   │   └── ProLibrary.jsx   # Pro reference library (upload + manage)
│   │   ├── components/
│   │   │   ├── VideoUploader.jsx
│   │   │   ├── SkeletonOverlay.jsx      # Single-skeleton canvas (legacy)
│   │   │   ├── DualSkeletonCanvas.jsx   # Dual-skeleton canvas with deviation overlay
│   │   │   ├── SkeletonLegend.jsx       # Color legend for dual skeleton
│   │   │   ├── VideoScrubber.jsx        # Frame-accurate scrubber with phase regions
│   │   │   ├── PhaseTimeline.jsx        # Horizontal phase timeline bar
│   │   │   ├── ComparisonView.jsx       # Main comparison UI (canvas + scrubber + panels)
│   │   │   ├── DeviationTimeline.jsx    # Severity timeline across all frames
│   │   │   ├── FrameDeviationPanel.jsx  # Per-frame joint deviation detail
│   │   │   ├── KeyboardShortcutsHelp.jsx # ? key overlay
│   │   │   ├── PhaseBreakdown.jsx       # Per-phase score breakdown
│   │   │   ├── CoachingFeedback.jsx     # Claude-generated advice
│   │   │   ├── ProReferenceCard.jsx     # Card for pro library grid
│   │   │   ├── AddProReferenceModal.jsx # Upload form modal
│   │   │   └── ProReferencePicker.jsx   # Dropdown on Upload page
│   │   ├── hooks/
│   │   │   ├── useUpload.js         # Upload + polling logic
│   │   │   ├── useAnalysis.js       # Fetch analysis results
│   │   │   ├── useVideoPlayback.js  # Frame-stepping, play/pause, keyboard shortcuts
│   │   │   └── useOverlayData.js    # Fetch + parse /overlay endpoint
│   │   └── lib/
│   │       ├── api.js           # Axios/fetch wrapper
│   │       └── landmarks.js     # Landmark transform + deviation helpers
│   └── public/
└── scripts/
    ├── build_pro_references.py       # Process pro video → .npz pose data (legacy CLI)
    ├── generate_synthetic_reference.py
    ├── migrate_static_references.py  # Import existing .npz files into ProReference DB table
    ├── test_e2e.py                   # V1 pipeline e2e test
    ├── test_e2e_v2.py                # V2 e2e test (pro library + overlay)
    └── dev_setup.sh                  # Dev environment bootstrap
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
- **Client-side canvas overlay over server-side video compositing**: More interactive (scrub, toggle, zoom), less compute, and the existing SkeletonOverlay.jsx pattern made this the natural extension. Server-side compositing would require storing rendered videos per-analysis, adding storage costs and removing interactivity.
- **Phase-aligned resampling over raw frame mapping**: Each phase is independently resampled so that a user's slower backswing doesn't cause misalignment in the forward swing. Raw duration-proportional mapping compounds timing errors across phases.
- **ProReference as a first-class DB entity over file-system convention**: Enables user uploads, status tracking, thumbnails, and future sharing features. Static .npz files in a directory have no metadata, no ownership, and no pipeline status.

## Pipeline Data Flow

### Pro Reference Upload Pipeline (Tasks 3.x)

```
User uploads pro video via Pro Library UI
  ↓
POST /api/pro-references → create ProReference record (status=pending) + presigned S3 URL
  ↓
POST /api/pro-references/{id}/confirm → enqueue RQ job (status=processing)
  ↓
RQ Worker (pro_reference_tasks.py):
  FFmpeg → frames
  MediaPipe → landmarks (N, 33, 3)
  Feature Engine → joint_angles, velocities, phases
  cv2 → thumbnail JPEG → S3
  np.savez → .npz (landmarks + features + metadata) → local data/ dir
  DB update → status=ready, npz_path, frame_count, fps
```

### Analysis Pipeline (full flow with overlay)

```
Input: MP4/MOV video (max 30s, ideally 120fps slow-mo)
  ↓
FFmpeg → frames/ directory (PNG files at native FPS)
  ↓
MediaPipe → pose_landmarks: np.ndarray, shape (num_frames, 33, 3)
  ↓
Feature Engine →
  joint_angles: dict[str, np.ndarray]  # per-joint angle timeseries
    keys: elbow_angle, shoulder_rotation, hip_rotation, knee_bend, racket_arm_elevation, trunk_rotation
  velocities: dict[str, np.ndarray]    # per-joint velocity timeseries
  phases: dict[str, tuple[int, int]]   # frame ranges per phase
    keys: preparation, backswing, forward_swing, contact, follow_through
  ↓ (keyframe JPEGs extracted at phase boundaries → S3)
  ↓
Pro Reference Loader → load .npz (DB-backed path or filesystem fallback)
  ↓
DTW Comparator →
  overall_score: float (0-100, higher = more similar to pro)
  phase_scores: dict[str, float]       # per-phase similarity
  deviations: list[Deviation]          # ranked list of biggest differences
    Deviation: {joint, phase, angle_diff, timing_diff, description}
  ↓
Phase Aligner (phase_aligner.py) →
  frame_mapping: list[int]             # user_frame → pro_frame (per-phase linear interp)
  phase_boundaries: dict[str, PhaseBoundary]  # tempo_ratio per phase
  aligned_pro_landmarks: np.ndarray    # pro landmarks resampled to user frame count
  ↓
Deviation Annotator (deviation_annotator.py) →
  frame_deviations: list[FrameDeviation]  # per-frame joint annotations (severity, direction)
  ↓
Claude Feedback →
  summary: str                         # 2-3 sentence overview
  priority_fixes: list[Fix]            # top 3 things to work on
    Fix: {title, explanation, drill, difficulty}
  positive_notes: list[str]            # what's going well
  ↓
DB write: pose_data, aligned_pro_landmarks, frame_mapping, frame_deviations,
          phase_boundaries, fps, keyframe_s3_keys, coaching_feedback
```

### Overlay Endpoint (GET /api/analysis/{id}/overlay)

```
DB → Analysis record
  ↓
Return OverlayResponse:
  user_landmarks: list[frame][landmark][x,y,z]
  pro_landmarks: list[frame][landmark][x,y,z]   # phase-aligned, same frame count
  frame_mapping: list[int]
  frame_deviations: list[FrameDeviation]
  phase_boundaries: dict[str, PhaseBoundary]
  fps: float
  landmark_connections: list[list[int]]          # bone pairs for skeleton drawing
  video_url: str | None                          # presigned S3 URL
  keyframe_urls: dict[str, str] | None           # phase → presigned S3 URL
```

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
- Do NOT send pro reference video to the frontend for side-by-side display. Use animated skeleton rendering from landmarks instead — the pro video may not be licensed for user-facing display.

## Common Commands

```bash
# Backend
cd backend
uv sync                              # Install deps
uv run uvicorn app.main:app --reload  # Dev server on :8000
uv run rq worker --with-scheduler    # Start worker
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
