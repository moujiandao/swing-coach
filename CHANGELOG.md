# Changelog

## [2026-03-26]

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
