# Swing Coach

Swing Coach is a tennis video-analysis application that compares a player's movement with a reference swing and turns the measured differences into coaching feedback.

This is an active prototype. The end-to-end workflow is implemented, but scoring still needs calibration against a larger set of real swings before it should be treated as coaching-grade analysis.

## What it does

- Accepts a tennis swing video through a guided upload flow.
- Extracts 2D image landmarks and MediaPipe world landmarks for each frame.
- Computes joint-angle, velocity, stance, and phase features.
- Aligns preparation, backswing, forward swing, contact, and follow-through independently with Dynamic Time Warping.
- Detects the racquet with YOLO when possible and falls back to a wrist-based estimate when detection fails.
- Displays an interactive user-versus-reference skeleton overlay with phase and deviation timelines.
- Runs deterministic pipeline checks before generating structured coaching feedback with Claude.
- Stores analysis state in Postgres and keeps uploaded videos in S3 or local development storage.

## Processing pipeline

```text
React upload flow
      |
      v
FastAPI API -> Postgres analysis record -> Redis queue
                                            |
                                            v
                                      Worker process
                                      - FFmpeg frames
                                      - MediaPipe pose
                                      - YOLO racquet detection
                                      - feature extraction
                                      - phase segmentation
                                      - DTW comparison
                                      - quality checks
                                      - coaching feedback
                                            |
                                            v
                               Postgres results + S3 video
                                            |
                                            v
                               Interactive browser overlay
```

The API enqueues analysis work instead of processing video inside the request. Each pipeline stage is independently testable, and failures update the analysis record rather than disappearing inside the worker.

For the detailed data flow and API contracts, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Important design choices

- **Phase-level comparison:** each phase is aligned independently so a slower backswing does not misalign the rest of the swing.
- **Angle-based scoring:** joint-angle features reduce sensitivity to camera position compared with raw image coordinates.
- **CPU-first models:** MediaPipe and YOLOv8 nano keep the worker deployable without a GPU.
- **Asynchronous processing:** Redis Queue keeps long-running video work outside the API lifecycle.
- **Client-side overlays:** the browser renders landmarks interactively instead of generating and storing composite videos.
- **Reference privacy:** reference video is not sent to the browser. The UI receives the derived landmark representation.

## Local development

Requirements:

- Python 3.11+
- Node.js 20+
- `uv`
- FFmpeg
- Redis

```bash
# Backend dependencies and configuration
cd backend
uv sync
cp .env.example .env

# Frontend dependencies
cd ../frontend
npm ci

# Synthetic reference data for local testing
cd ../backend
uv run python ../scripts/generate_synthetic_reference.py
```

Run the services in separate terminals:

```bash
redis-server
cd backend && uv run uvicorn app.main:app --reload
cd backend && uv run rq worker --with-scheduler
cd frontend && npm run dev
```

On macOS, the worker may require:

```bash
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run rq worker --with-scheduler
```

The frontend runs at [http://localhost:5173](http://localhost:5173), and the API health endpoint is [http://localhost:8000/api/health](http://localhost:8000/api/health).

Configuration is documented in [`backend/.env.example`](backend/.env.example). Local development can use SQLite and local file storage instead of Supabase and S3.

## Verification

```bash
cd backend && uv run pytest tests/ -v
cd frontend && npm run lint
cd frontend && npm run build
```

The repository also includes deterministic pipeline evaluations and end-to-end scripts under [`scripts/`](scripts/).

## Technology

- React, Vite, and Tailwind CSS
- FastAPI, Pydantic, and SQLAlchemy
- Redis Queue
- MediaPipe, OpenCV, YOLO, NumPy, SciPy, and tslearn
- PostgreSQL or SQLite
- AWS S3 or local storage
- Anthropic API

## Current limitations

- Angle-scoring scale factors are provisional and need validation against real swings.
- Several segment-angle features still use 2D projections even though 3D world landmarks are available.
- MediaPipe stability across camera angles has not been fully benchmarked.
- Racquet detection is non-fatal and may fall back to a wrist projection.
- The backend suite passes and the frontend builds, but ESLint currently reports 12 errors and 2 warnings in the interactive analysis UI.
- The application is not a substitute for instruction from a qualified coach.
- Production deployment is not complete.

Use synthetic or personally owned video for development. Professional reference footage is not included because redistribution rights vary.
