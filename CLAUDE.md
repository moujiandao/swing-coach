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
├── backend/
│   ├── pyproject.toml           # Dependencies (use uv)
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, lifespan
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── models.py            # SQLAlchemy/Pydantic models
│   │   ├── routers/
│   │   │   ├── upload.py        # POST /api/upload (presigned URL + job enqueue)
│   │   │   ├── analysis.py      # GET /api/analysis/{id}, GET /api/history
│   │   │   └── health.py        # GET /api/health
│   │   ├── worker/
│   │   │   ├── tasks.py         # RQ task: orchestrates the pipeline
│   │   │   ├── frame_extractor.py   # FFmpeg frame extraction
│   │   │   ├── pose_estimator.py    # MediaPipe pose extraction
│   │   │   ├── feature_engine.py    # Joint angles, velocities, phase segmentation
│   │   │   ├── dtw_comparator.py    # DTW comparison against pro DB
│   │   │   └── feedback_generator.py # Claude API coaching feedback
│   │   ├── services/
│   │   │   ├── s3.py            # S3 upload/download helpers
│   │   │   └── db.py            # Database session management
│   │   └── pro_references/
│   │       ├── loader.py        # Load pre-computed pro pose data
│   │       └── data/            # .npy files of pro swing landmarks
│   └── tests/
│       ├── test_pose_estimator.py
│       ├── test_feature_engine.py
│       ├── test_dtw_comparator.py
│       └── fixtures/            # Sample video clips for testing
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── pages/
│   │   │   ├── Upload.jsx       # Video upload with drag-and-drop
│   │   │   ├── Analysis.jsx     # Results display (skeleton + feedback)
│   │   │   └── History.jsx      # Past analyses list
│   │   ├── components/
│   │   │   ├── VideoUploader.jsx
│   │   │   ├── SkeletonOverlay.jsx  # Canvas overlay drawing pose
│   │   │   ├── PhaseBreakdown.jsx   # Per-phase deviation display
│   │   │   ├── CoachingFeedback.jsx # Claude-generated advice
│   │   │   └── ProComparison.jsx    # Side-by-side comparison view
│   │   ├── hooks/
│   │   │   ├── useUpload.js     # Upload + polling logic
│   │   │   └── useAnalysis.js   # Fetch analysis results
│   │   └── lib/
│   │       └── api.js           # Axios/fetch wrapper
│   └── public/
└── scripts/
    ├── build_pro_references.py  # Process pro video → .npy pose data
    └── seed_test_data.py        # Create test fixtures
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

## Pipeline Data Flow

```
Input: MP4/MOV video (max 30s, ideally 120fps slow-mo)
  ↓
FFmpeg → frames/ directory (PNG files at native FPS)
  ↓
MediaPipe → pose_landmarks: np.ndarray, shape (num_frames, 33, 3)
  ↓
Feature Engine →
  joint_angles: dict[str, np.ndarray]  # per-joint angle timeseries
    keys: elbow_angle, shoulder_rotation, hip_rotation, knee_bend, wrist_lag
  velocities: dict[str, np.ndarray]    # per-joint velocity timeseries
  phases: dict[str, tuple[int, int]]   # frame ranges per phase
    keys: backswing, forward_swing, contact, follow_through
  ↓
DTW Comparator →
  overall_score: float (0-100, higher = more similar to pro)
  phase_scores: dict[str, float]       # per-phase similarity
  deviations: list[Deviation]          # ranked list of biggest differences
    Deviation: {joint, phase, angle_diff, timing_diff, description}
  ↓
Claude Feedback →
  summary: str                         # 2-3 sentence overview
  priority_fixes: list[Fix]            # top 3 things to work on
    Fix: {title, explanation, drill, difficulty}
  positive_notes: list[str]            # what's going well
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

# Scripts
cd scripts
python build_pro_references.py --video path/to/pro_video.mp4 --stroke forehand --player federer
```
