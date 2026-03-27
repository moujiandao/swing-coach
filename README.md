# SwingCoach MVP

AI-powered tennis swing analysis. Upload a video of your swing, get coaching feedback comparing your technique against a professional reference using biomechanical pose analysis and DTW sequence matching.

---

## Architecture

```
Browser (React + Vite)
    │  drag-drop video upload
    ▼
FastAPI (Python)
    ├── POST /api/upload        → presigned S3 URL + analysis record
    ├── POST /api/upload/{id}/confirm → enqueue RQ job
    ├── GET  /api/analysis/{id} → poll for results
    └── GET  /api/history       → past analyses
    │
    ▼ (enqueue)
Redis Queue (RQ) Worker
    ├── FFmpeg          → extract frames (PNG) from video
    ├── MediaPipe       → 33 body landmarks per frame → numpy array (N, 33, 3)
    ├── Feature Engine  → joint angles, velocities, phase segmentation
    ├── DTW Comparator  → compare against pro reference (.npz)
    └── Claude API      → structured coaching feedback (JSON)
    │
    ▼ (store)
PostgreSQL (Supabase) ← analysis records + results
AWS S3               ← original video storage
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

# Terminal 3
cd backend && uv run python run_worker.py

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

## Building Pro References

Pro references are pre-computed swing feature data stored as `.npz` files in `backend/app/pro_references/data/`.

### Generate a synthetic reference (for dev/testing)

```bash
cd backend
uv run python ../scripts/generate_synthetic_reference.py
# Creates: app/pro_references/data/synthetic_forehand.npz
```

### Process a real pro video

```bash
cd backend
uv run python ../scripts/build_pro_references.py \
  --video /path/to/federer_forehand.mp4 \
  --stroke forehand \
  --player federer
# Creates: app/pro_references/data/federer_forehand.npz
```

Supported stroke values: `forehand`, `backhand_one`, `backhand_two`, `serve_flat`, `serve_kick`, `serve_slice`, `volley`

---

## Running Tests

```bash
cd backend
uv run pytest tests/ -v
```

Individual test files:
- `tests/test_frame_extractor.py` - FFmpeg frame extraction
- `tests/test_pose_estimator.py` - MediaPipe pose detection
- `tests/test_feature_engine.py` - Joint angles and phase detection
- `tests/test_dtw_comparator.py` - DTW comparison and scoring
- `tests/test_feedback_generator.py` - Claude API (skipped without API key)

---

## Deployment

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
| Sequence matching | DTW via tslearn |
| Coaching feedback | Anthropic Claude API |
| Database | PostgreSQL via Supabase (SQLite for local dev) |
| Video storage | AWS S3 |
| Deployment | Railway (backend), Vercel (frontend) |
