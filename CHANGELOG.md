# Changelog

## [2026-03-27]

### Added (Task 2.2 — Video upload page)
- Create `src/components/VideoUploader.jsx`: react-dropzone with MP4/MOV/QuickTime accept, 100 MB max, file name+size display, `<video>` preview via `URL.createObjectURL`, upload progress bar
- Build full `src/pages/Upload.jsx`: 7-option stroke type card selector, pro reference dropdown (Federer/Nadal/Djokovic/Synthetic), `createAnalysis` → S3 PUT → `confirmUpload` → navigate flow with `onUploadProgress` tracking, `file://` dev fallback to multipart POST, error banner, disabled-until-ready Analyze button

### Added (Task 2.1 — Frontend scaffolding)
- Create `frontend/` React app (Vite + React 19) with Tailwind CSS v4 CSS-based config and `@tailwindcss/vite` plugin
- Set up react-router-dom v7 with three routes: `/` (Upload), `/analysis/:id` (Analysis), `/history` (History)
- Add `src/lib/api.js`: Axios instance with `VITE_API_URL` base; exports `createAnalysis`, `confirmUpload`, `getAnalysis`, `getHistory`
- Create placeholder pages (Upload, Analysis, History) and `NavBar` layout wrapper with dark theme and `#2D8653` tennis green accent
- Add `.env` with `VITE_API_URL=http://localhost:8000`



### Added (Task 1.9 — Worker task orchestration and end-to-end pipeline)
- Implement `app/worker/tasks.py`: `process_analysis()` orchestrating all 5 pipeline stages (frames → pose → features → DTW → feedback) with per-stage timing logs, try/finally cleanup, and status transitions to `completed`/`failed`
- Add `app/services/s3.py` `download_video()`: downloads video from S3 to local path; falls back to local `uploads/` copy in dev
- Add `backend/run_worker.py`: RQ worker entry point (`uv run python run_worker.py`)
- Update `app/routers/upload.py` confirm endpoint to enqueue `process_analysis` (was `run_analysis` stub)
- Add `scripts/test_e2e.py`: manual end-to-end test that creates a synthetic video, runs the full pipeline with mocked pose estimation, and asserts all DB result fields are populated

### Added (Task 1.8 — Claude feedback generator)
- Implement `app/worker/feedback_generator.py`: async `generate_coaching_feedback()` calling `claude-sonnet-4-20250514` with structured deviation data; parses JSON response into `CoachingFeedback` dataclass (summary, overall_assessment, priority_fixes, positive_notes, drill_plan)
- Add `Fix` and `Drill` dataclasses with full field set (title, explanation, target_metric, current/target value; name, description, duration, frequency, focus_area)
- Add retry logic: on JSON parse failure, re-prompts Claude with explicit "respond only in valid JSON" nudge before raising `ValueError`
- Add 19 tests in `tests/test_feedback_generator.py`: prompt construction, JSON parsing, field validation, cap enforcement — 13 run without API key, 6 live tests skip unless `ANTHROPIC_API_KEY` is set

### Added (Task 1.7 — DTW comparator and pro reference loader)
- Implement `app/pro_references/loader.py`: `ProReferenceDB` class (load/query .npz files) and `save_reference()` helper; keys follow `{player}_{stroke_type}` convention
- Implement `app/worker/dtw_comparator.py`: `compare_swing()` with phase-segmented DTW, exponential score decay (scale=50), 5-phase weighted overall score, and `Deviation` dataclass with human-readable descriptions
- Add `scripts/generate_synthetic_reference.py`: generates a 60-frame synthetic forehand reference using parameterized sine curves; saves to `app/pro_references/data/synthetic_forehand.npz`
- Add `scripts/build_pro_references.py`: end-to-end pipeline script (video → frames → pose → features → .npz) for processing real pro videos
- Add 19 tests in `tests/test_dtw_comparator.py`: identical/different swing scores, deviation sorting, phase weighting, ProReferenceDB round-trip, synthetic reference integration — all passing

### Added (Task 1.6 — Feature extraction and phase segmentation)
- Implement `app/worker/feature_engine.py`: `extract_features()` producing joint angles (6 keys), smoothed velocities (3 keys), 5-phase segmentation, and contact frame index
- Add `compute_angle()` helper using arccos for stable [0,360) degree output
- Add `compute_velocity()` using Savitzky-Golay smoothing (window=7, polyorder=2) for noise reduction
- Add `detect_phases()` based on wrist x-velocity sign changes and peak wrist speed
- Support left-hand mirroring (swap hitting-arm landmark indices)
- Add 24 tests in `tests/test_feature_engine.py`: angle geometry, velocity smoothing, phase detection, integration, and handedness mirroring — all passing

## [2026-03-26]

### Added (Task 1.5 — MediaPipe pose estimation)
- Add MediaPipe pose estimation pipeline stage (`app/worker/pose_estimator.py`) using Tasks API (0.10+) with auto-download of heavy model, linear interpolation for missing frames, and `LANDMARK_NAMES` constant for all 33 BlazePose landmarks
- Add `blank_frame_paths` fixture to `tests/conftest.py`
- Add pose estimator tests (`tests/test_pose_estimator.py`): 14 tests covering output shape, detection rate, interpolation logic, and edge cases — fully mocked so CI requires no model download

### Added (Task 1.4 — FFmpeg frame extraction)
- Add frame extraction pipeline stage (`app/worker/frame_extractor.py`): ffprobe metadata probing, duration validation, slow-mo auto-downsampling (>60fps → 30fps), frame-as-PNG extraction via subprocess
- Add session-scoped synthetic video fixtures to `tests/conftest.py` (30fps, 120fps, 35s over-length)
- Add frame extractor tests (`tests/test_frame_extractor.py`): 11 tests covering extraction correctness, metadata, FPS downsampling, duration guard, and error handling

### Added (Task 1.3 — S3 service and upload endpoints)
- Add S3 service (`app/services/s3.py`): presigned PUT/GET URLs with local `file://` fallback when `S3_BUCKET` is unset
- Add upload router (`app/routers/upload.py`): `POST /api/upload` (create analysis + presigned URL), `POST /api/upload/{id}/confirm` (transition to processing, enqueue RQ job)
- Add analysis router (`app/routers/analysis.py`): `GET /api/analysis/{id}`, `GET /api/history`
- Add upload and analysis endpoint tests (`tests/test_upload_and_analysis.py`): 15 tests with in-memory SQLite and dependency overrides

### Added (Task 1.2 — Database models and Alembic migration)
- Add SQLAlchemy models and Pydantic schemas (`app/models.py`): `Analysis` table with UUID PK, status/stroke enums, JSON fields for pose data and feedback
- Add async database service (`app/services/db.py`): `get_engine()` and `get_session()` supporting both `postgresql+asyncpg://` and `sqlite+aiosqlite://`
- Add Alembic config and initial migration creating the `analyses` table
- Add model and DB tests (`tests/test_models_and_db.py`): 12 tests covering CRUD, enum validation, JSON roundtrip, and Alembic upgrade

### Added (Task 1.1 — Project scaffolding)
- Scaffold backend project structure matching CLAUDE.md layout
- Add `pyproject.toml` with all runtime and dev dependencies (FastAPI, MediaPipe, RQ, SQLAlchemy, Anthropic, etc.) managed via `uv`
- Add `app/config.py`: pydantic-settings `Settings` with all required env vars
- Add `app/main.py`: FastAPI app with CORS, lifespan logging, and router includes
- Add `app/routers/health.py`: `GET /api/health`
- Add `.env.example` with all config var stubs
