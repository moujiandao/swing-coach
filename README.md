# SwingCoach MVP

AI-powered tennis swing analysis. Upload a video of your swing, get coaching feedback comparing your technique against a professional reference using biomechanical pose analysis and DTW sequence matching.

---

## Features

- **3-step upload wizard**: Choose stroke type and grip, select a pro reference, upload video
- **Grip-based pro matching**: Semi-Western, Modified Eastern, Eastern, Western grip selection filters available pro references with player headshots
- **Full-body pose analysis**: 10 joint angles + 4 velocity metrics extracted via MediaPipe BlazePose (33 landmarks)
- **Phase-segmented DTW comparison**: Preparation, backswing, forward swing, contact, follow-through scored independently against pro reference
- **Base score**: Dedicated lower body scoring (stance width, knee bend, hip rotation)
- **YOLO racquet detection**: Per-frame racquet position tracking with fallback to wrist-projection heuristic
- **Skeleton overlay**: Dual-skeleton canvas (user in cyan, pro in gold) with deviation glow highlights synced to video playback
- **Frame-accurate scrubber**: Step through frames, jump between phases, adjustable playback speed (0.25x/0.5x/1x)
- **AI coaching feedback**: Claude-generated coaching advice with 4 golden rules of tennis, priority fixes, and drill plans
- **Pipeline quality checks**: 9 deterministic eval checks + optional LLM-as-judge feedback quality scoring
- **Pro reference library**: Upload and manage pro swing references with status tracking and skeleton preview
- **Analysis history**: View past analyses with delete/bulk-delete support

---

## Architecture

```
Browser (React + Vite)
    │  drag-drop video upload          │  pro reference upload (Pro Library)
    ▼                                  ▼
FastAPI (Python)
    ├── POST /api/upload               → presigned S3 URL + analysis record
    ├── POST /api/upload/{id}/confirm  → enqueue analysis RQ job
    ├── GET  /api/analysis/{id}        → poll for results
    ├── GET  /api/analysis/{id}/overlay → overlay dataset for canvas rendering
    ├── GET  /api/history              → past analyses
    ├── DELETE /api/analysis/{id}      → delete single analysis
    ├── POST /api/analysis/bulk-delete → delete multiple analyses
    ├── POST /api/pro-references       → presigned S3 URL + ProReference record
    ├── POST /api/pro-references/{id}/confirm → enqueue pro reference RQ job
    ├── GET  /api/pro-references       → list available pro references
    └── GET  /api/pro-references/{id}/preview → skeleton preview data
    │
    ▼ (enqueue)
Redis Queue (RQ) Worker
    ├── Analysis pipeline (tasks.py):
    │   ├── FFmpeg          → extract frames (PNG) from video
    │   ├── MediaPipe       → 33 body landmarks per frame → numpy array (N, 33, 3)
    │   ├── YOLO            → racquet detection per frame (non-fatal)
    │   ├── Feature Engine  → 10 joint angles, 4 velocities, phase segmentation
    │   ├── DTW Comparator  → compare against pro reference (.npz)
    │   ├── Phase Aligner   → per-phase frame mapping + aligned pro landmarks
    │   ├── Deviation Annotator → per-frame joint deviation severity
    │   ├── Pipeline Evals  → 9 deterministic quality checks
    │   └── Claude API      → structured coaching feedback (JSON)
    │
    └── Pro Reference pipeline (pro_reference_tasks.py):
        ├── FFmpeg          → extract frames
        ├── MediaPipe       → landmarks
        ├── YOLO            → racquet detection (non-fatal)
        ├── Feature Engine  → angles, velocities, phases
        └── np.savez        → .npz file (landmarks + features + racquet)
    │
    ▼ (store)
PostgreSQL (Supabase) ← analysis records + overlay data + pro reference metadata
AWS S3               ← original videos, keyframe JPEGs, pro reference thumbnails
```

---

## Local Development Setup

### Prerequisites

- Python 3.11+
- Node 20+
- ffmpeg (`brew install ffmpeg` on Mac, `apt-get install ffmpeg` on Linux)
- Redis (`brew install redis` on Mac)
- Docker + Docker Compose (optional, for containerized dev)

### Quick start (automated)

```bash
# From project root:
bash scripts/dev_setup.sh
```

This script checks all prerequisites, installs dependencies, creates `backend/.env` from the example, and generates the synthetic pro reference for testing.

### Manual setup

```bash
# 1. Backend
cd backend
uv sync
cp .env.example .env    # then fill in your secrets

# 2. Frontend
cd frontend
npm install

# 3. Synthetic pro reference (for testing without real pro video)
cd backend
uv run python ../scripts/generate_synthetic_reference.py
```

### Running locally

Option A - Docker Compose (recommended):
```bash
docker-compose up
```

Option B - Manual (4 terminals):
```bash
# Terminal 1
redis-server

# Terminal 2
cd backend && uv run uvicorn app.main:app --reload

# Terminal 3 (macOS requires the env var to prevent SIGABRT in forked MediaPipe processes)
cd backend && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run rq worker --with-scheduler

# Terminal 4
cd frontend && npm run dev
```

- Frontend: http://localhost:5173
- API: http://localhost:8000/api/health

---

## Environment Variables

All secrets live in `backend/.env`. Copy from `.env.example`:

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL or SQLite URL | `sqlite+aiosqlite:///./dev.db` |
| `SUPABASE_URL` | Supabase project URL | |
| `SUPABASE_KEY` | Supabase anon key | |
| `S3_BUCKET` | AWS S3 bucket name | |
| `AWS_ACCESS_KEY_ID` | AWS credentials | |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials | |
| `AWS_REGION` | AWS region | `us-east-1` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `ANTHROPIC_API_KEY` | Claude API key | |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | `http://localhost:5173` |
| `MAX_VIDEO_DURATION_SECONDS` | Reject videos longer than this | `30` |
| `MAX_VIDEO_SIZE_MB` | Reject files larger than this | `100` |

For local dev without S3: leave `S3_BUCKET` empty and the backend will save uploads to a local `uploads/` directory.

---

## Pro Reference Library

Pro references are pre-computed swing feature data stored as `.npz` files, now backed by a `ProReference` database table with upload status tracking.

### Upload a pro reference via the UI

1. Navigate to the **Pro Library** page in the app
2. Click **Add Pro Reference**, fill in player name and stroke type
3. Upload the video file — the backend processes it automatically (frames → pose → features → .npz)
4. Once status shows **Ready**, the reference is available to select when uploading a new analysis

### Generate a synthetic reference (for dev/testing)

```bash
cd backend
uv run python ../scripts/generate_synthetic_reference.py
# Creates: app/pro_references/data/synthetic_forehand.npz
```

### Process a real pro video via CLI (legacy)

```bash
cd backend
uv run python ../scripts/build_pro_references.py \
  --video /path/to/federer_forehand.mp4 \
  --stroke forehand \
  --player federer
# Creates: app/pro_references/data/federer_forehand.npz
```

Supported stroke values: `forehand`, `backhand_one`, `backhand_two`, `serve_flat`, `serve_kick`, `serve_slice`, `volley`, `buggy_whip_forehand`, `slice`

---

## Comparison View and Deviation Overlay

After an analysis completes, the **Comparison View** shows your swing overlaid on the selected pro reference using an animated skeleton canvas.

### How it works

- The backend phase-aligns both swings frame-by-frame (each of 5 phases is independently resampled)
- The frontend fetches `GET /api/analysis/{id}/overlay` which returns landmark arrays, frame mapping, and per-frame deviation annotations
- `DualSkeletonCanvas` renders both skeletons simultaneously — user in cyan, pro in gold
- Deviating joints pulse in red/amber based on severity (critical/moderate/minor)
- `VideoScrubber` lets you step through frames; `PhaseTimeline` shows which swing phase you're in
- `DeviationTimeline` shows a severity heatmap across the full swing

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| Space | Play / pause |
| ← / → | Step one frame |
| [ / ] | Jump to previous / next phase |
| S | Toggle skeleton overlay |
| ? | Show keyboard shortcuts |

---

## Running Tests

```bash
cd backend
uv run pytest tests/ -v    # 357+ tests
```

Test coverage spans all pipeline stages: frame extraction, pose estimation, feature engine, DTW comparison, phase alignment, deviation annotation, racquet detection, pipeline evals, feedback generation, overlay API, pro reference API, upload/analysis endpoints, keyframe extraction, and model/DB operations.

---

## Deployment (planned, not yet live)

### Railway (backend + worker)

The `backend/Procfile` defines two process types:
- `web`: FastAPI API server
- `worker`: RQ background worker

Railway auto-detects the Procfile. Set all environment variables in the Railway dashboard. ffmpeg is installed via the Dockerfile.

```bash
# Railway CLI deploy
railway up
```

Set `ALLOWED_ORIGINS` to your Vercel frontend URL in Railway env vars.

### Vercel (frontend)

```bash
cd frontend
npm run build
vercel --prod
```

Set `VITE_API_URL` to your Railway backend URL in Vercel env vars, or use the Vercel dashboard.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS v4, React Router |
| Backend API | FastAPI, uvicorn, Python 3.11 |
| Task queue | Redis + RQ |
| Pose estimation | MediaPipe BlazePose (CPU) |
| Racquet detection | YOLOv8 nano via ultralytics (CPU) |
| Sequence matching | DTW via tslearn |
| Coaching feedback | Anthropic Claude API |
| Database | PostgreSQL via Supabase (SQLite for local dev) |
| Video storage | AWS S3 |
| Deployment | Railway (backend), Vercel (frontend) |
