# Changelog

## Session status — 2026-03-28 end of session

**Branch:** `feature/pro-reference-v2` — 250 tests passing, working tree clean

**Completed this session:**
- Task 3.4: ProReferencePicker component + wire Upload page to DB-backed references + `pro_reference_id` FK on Analysis
- Task 4.1: Phase alignment engine (`phase_aligner.py`) + deviation annotator (`deviation_annotator.py`) + 4 new overlay JSON columns on Analysis
- Task 4.2: `GET /api/analysis/{id}/overlay` + `GET /api/pro-references/{id}/preview` endpoints + `LANDMARK_CONNECTIONS` constant + `fps` column on Analysis
- Task 4.3: Keyframe extraction per phase + S3 upload + `keyframe_s3_keys` on Analysis + presigned `video_url`/`keyframe_urls` in analysis and overlay endpoints + local dev static file serving via `/uploads/`
- Task 5.1: `DualSkeletonCanvas` component (video + dual skeleton + deviation glow + phase label) + `SkeletonLegend` + `src/lib/landmarks.js` utilities + `/dev/overlay-test` page with synthetic data
- Task 5.2: `useVideoPlayback` hook (rAF-based, configurable speed) + `VideoScrubber` (phase-gradient track, transport controls, phase jump buttons) + `PhaseTimeline` (proportional segments, tempo badges, cursor line)

**Next tasks (FEATURE_SPEC_V2.md):**
- Task 5.3: Comparison view (side-by-side + overlay modes)
- Task 5.4: Polish
- Task 6.1: Integration

---

## [2026-03-28]

### Added
- `keyframe_s3_keys` JSON column on `analyses` table (Alembic migration `f1c2d3e4b567`)
- `_save_keyframes()` helper in `tasks.py` - extracts first frame of each phase as JPEG
- Step 6.5 in `process_analysis` - extracts and uploads 5 keyframes to S3 after feature extraction; non-fatal on failure
- `generate_presigned_urls(keys)` batch utility in `app/services/s3.py`
- `video_url` and `keyframe_urls` fields on `AnalysisResponse` and `OverlayResponse` (computed at request time)
- `_build_keyframe_urls()` helper in analysis router
- `StaticFiles` mount at `/uploads` in `main.py` for local dev (no S3) so the frontend can load videos and keyframes via HTTP
- `aiofiles` dependency (required by FastAPI StaticFiles)
- 18 new tests in `test_keyframe_extraction.py`

### Changed
- `GET /api/analysis/{id}` now includes `video_url` (presigned) and `keyframe_urls` (dict of phase_name → presigned URL)
- `GET /api/analysis/{id}/overlay` now includes `video_url` and `keyframe_urls`; Cache-Control changed from `immutable` to `private, max-age=3600` since presigned URLs expire in 1 hour
- `generate_presigned_download_url` local dev fallback now returns `/uploads/{key}` HTTP path instead of `file://` URI (browser-usable)

## [2026-03-28] Task 5.2

### Added
- `frontend/src/hooks/useVideoPlayback.js`: rAF-based playback hook with `play/pause/seek/step/seekToPhase`, configurable speed (0.25x/0.5x/1x), frame looping
- `frontend/src/components/VideoScrubber.jsx`: transport controls (play/pause, step, speed), phase-gradient scrubber track, phase quick-jump buttons, frame/time readout; exports `PHASE_COLORS` and `PHASE_ORDER` constants
- `frontend/src/components/PhaseTimeline.jsx`: proportional phase segments with tempo badges (slower/faster/on-pace), current-frame cursor, clickable phase segments

### Changed
- `frontend/src/pages/DevOverlayTest.jsx`: replaced manual range input with `VideoScrubber` + `PhaseTimeline`, wired `useVideoPlayback` hook; synthetic phase boundaries now include `tempo_ratio` for timeline badges

---

## [2026-03-28] Task 5.1

### Added
- `frontend/src/lib/landmarks.js`: `transformLandmarks()`, `getDeviationsForFrame()`, `getCurrentPhase()` utilities
- `frontend/src/components/DualSkeletonCanvas.jsx`: canvas component rendering user skeleton (cyan solid), pro skeleton (gold dashed), deviation glow highlights with pulsing animation, angle-diff labels, phase name label — requestAnimationFrame loop, video-frame background via hidden `<video>` element
- `frontend/src/components/SkeletonLegend.jsx`: compact SVG legend bar (cyan = your swing, gold dashed = pro, red circle = deviation)
- `frontend/src/pages/DevOverlayTest.jsx`: dev-only test page at `/dev/overlay-test` with synthetic landmark data, frame scrubber, and skeleton toggle controls
- `getOverlay(analysisId)` function in `frontend/src/lib/api.js`

### Changed
- `frontend/vite.config.js`: added `/uploads` proxy so local videos/keyframes load in dev without CORS issues
- `frontend/src/App.jsx`: added `/dev/overlay-test` route (dev mode only, lazy-loaded)

---

## Session status — 2026-03-27 end of session

**Branch:** `feature/pro-reference-v2` — 154 tests passing, working tree clean

**Completed this session:**
- Task 3.1: ProReference DB model + Alembic migration + slug utility + migrate script
- Task 3.2: Pro reference API (6 endpoints) + `process_pro_reference` RQ worker task

**Next tasks (FEATURE_SPEC_V2.md):**
- Task 3.3: Frontend pro reference library UI (upload form, library page, status polling)
- Task 3.4: Wire existing analysis to use DB-backed pro references
- Task 4.x: Deviation overlay backend
- Task 5.x: Frontend comparison UI
- Task 6.1: Integration

---

## [2026-03-28] Overlay data API and pro reference preview (Task 4.2)

### Added
- `GET /api/analysis/{id}/overlay` — returns user+pro landmarks, frame mapping, per-frame deviations, phase boundaries, fps, and skeleton bone connections; coordinates rounded to 4dp; `Cache-Control: immutable` on completed analyses
- `GET /api/pro-references/{id}/preview` — returns pro reference landmark array + phases + fps for animated skeleton preview in the library; loads directly from .npz; `Cache-Control: immutable`
- `LANDMARK_CONNECTIONS` constant in `models.py` — 12 BlazePose bone pairs, all indices validated < 33
- `OverlayResponse` and `ProPreviewResponse` Pydantic schemas
- `fps` column on `Analysis` model; stored by `process_analysis`; Alembic migration `e9a2c3d5f617`
- `tests/test_overlay_api.py` — 28 tests covering shape, 404s, rounding, Cache-Control, landmark connection validity

### Changed
- `analysis.py` — `_round_landmarks()` helper rounds nested lists via numpy
- `tasks.py` — stores `fps` in `_write_results`

---

## [2026-03-28] Phase alignment and deviation annotation engine (Task 4.1)

### Added
- `phase_aligner.py` — `align_phases()` builds a per-frame mapping from user swing to pro reference via linear interpolation within each phase; `resample_landmarks()` resamples (N,33,3) arrays to any target length; `PhaseAlignmentResult` and `PhaseBoundary` dataclasses with tempo ratios
- `deviation_annotator.py` — `compute_frame_deviations()` annotates each frame with which joints are deviating (angle diff > 10°) and maps joints to MediaPipe landmark indices for skeleton highlighting; `FrameDeviation` and `JointDeviation` dataclasses
- Alembic migration `d4f8b2e1a736` — adds `aligned_pro_landmarks`, `frame_mapping`, `frame_deviations`, `phase_boundaries` JSON columns to `analyses`
- `tests/test_phase_aligner.py` — 25 tests covering identical lengths, interpolation, missing phases, tempo ratios, resample shape/values
- `tests/test_deviation_annotator.py` — 25 tests covering landmark map, angle computation, phase boundaries, direction ("too_wide"/"too_narrow"), severity propagation

### Changed
- `Analysis` model and `AnalysisResponse` schema — expose all four new overlay fields
- `process_analysis` worker task — after DTW comparison, runs phase alignment, resamples pro landmarks, runs deviation annotation, stores all overlay data on the Analysis record

---

## [2026-03-27] Wire Upload page to pro reference library (Task 3.4)

### Added
- `ProReferencePicker` component — scrollable card row filtered by stroke type; selected card shows green border + checkmark; "Add New" card opens modal
- `pro_reference_id` UUID FK column on `analyses` table (nullable, backward compat)
- `pro_landmarks` JSON column on `analyses` table — stores pro landmark array for frontend overlay
- Alembic migration `c7e3a1b2d849` — adds both new columns; FK constraint skipped on SQLite

### Changed
- `AnalysisCreate` schema — adds `pro_reference_id: UUID | None`; keeps `pro_reference` string for backward compat
- `AnalysisResponse` schema — exposes `pro_reference_id` and `pro_landmarks`
- Upload router — validates `pro_reference_id` exists and has `status=ready` before creating the Analysis record
- Worker `process_analysis` — loads pro reference directly from the DB record's `.npz` when `pro_reference_id` is set; falls back to file-based loader for old analyses
- `createAnalysis` in `api.js` — now sends `pro_reference_id` UUID instead of `pro_reference` string name
- `Upload.jsx` — replaced hardcoded dropdown with `ProReferencePicker`; stroke type selection clears reference selection

---

## [2026-03-27] Pro reference library UI (Task 3.3)

### Added
- Add `getProReferences`, `getProReference`, `createProReference`, `confirmProReference`, `deleteProReference`, `reprocessProReference` to `frontend/src/lib/api.js`
- Create `frontend/src/pages/ProLibrary.jsx`: full-width page with filter bar (stroke type, status), responsive 3/2/1 grid, skeleton loading, empty state, auto-poll every 5s while any card is processing/pending, toast on upload success
- Create `frontend/src/components/ProReferenceCard.jsx`: thumbnail (or SVG silhouette), stroke badge, status indicator (dot + label), built-in badge, hover scale effect, context menu (reprocess/delete) with delete confirmation overlay
- Create `frontend/src/components/AddProReferenceModal.jsx`: player name input, stroke selector, VideoUploader reuse, presigned URL upload with progress bar, confirm call, success toast on close
- Add `/library` route and "Library" nav link (between Upload and History) to `frontend/src/App.jsx`

## [2026-03-27] Pro reference upload pipeline

### Added
- Create `backend/app/routers/pro_references.py`: 6 endpoints - POST create (presigned upload URL), POST confirm (enqueue processing), GET list (filterable by stroke_type/status/include_builtin, sorted by player_name), GET detail, DELETE (403 for builtins, cleans up .npz + S3), POST reprocess
- Create `backend/app/worker/pro_reference_tasks.py`: `process_pro_reference` RQ task - download video, extract frames, pose estimation, feature extraction, thumbnail generation (320x180 JPEG), .npz save (extends loader format with velocity and landmark arrays), DB record update
- Add `upload_file(local_path, key, content_type)` and `delete_object(key)` to `backend/app/services/s3.py`
- Register pro_references router in `backend/app/main.py`
- Add `backend/tests/test_pro_reference_api.py`: 27 tests covering all endpoints and worker task orchestration (npz written to disk, failure marks status=failed)

## [2026-03-27] ProReference DB model

### Added
- Add `ProReference` SQLAlchemy model to `backend/app/models.py`: UUID primary key, player_name/slug, stroke_type, video/thumbnail/npz S3 keys, status enum (pending/processing/ready/failed), frame metadata, is_builtin flag, metadata_json
- Add `ProReferenceStatus` enum to `app/models.py`
- Add `slugify(name)` utility to `app/models.py`: lowercase, hyphen-separated, handles special chars
- Add Pydantic schemas: `ProReferenceCreate`, `ProReferenceResponse`, `ProReferenceListItem`
- Add Alembic migration `a3c1e7d2f905_create_pro_references_table.py`: creates `pro_references` table with unique index on `player_slug`
- Add `ProReferenceDB.get_by_id(session, ref_id)`: async DB-backed lookup by UUID, loads .npz from npz_path
- Add `ProReferenceDB.list_available_from_db(session)`: async DB-backed list of ready references as `ProReferenceListItem` list
- Deprecate `ProReferenceDB.list_available()` (file-scan path) with `DeprecationWarning`; kept as fallback
- Add `scripts/migrate_static_references.py`: scans `backend/app/pro_references/data/*.npz`, creates ProReference DB records with status=ready/is_builtin=True; idempotent
- Add `backend/tests/test_pro_reference_model.py`: 20 tests covering CRUD, slug uniqueness, DB-backed loader methods, migration script correctness and idempotency

## [2026-03-27]

### Fixed (Analyze Swing button — "Not Found" error on upload)
- Fix `frontend/src/lib/api.js`: correct `createAnalysis` endpoint from `/api/upload/create` to `/api/upload`
- Fix `frontend/src/lib/api.js`: correct `confirmUpload` endpoint from `/api/upload/confirm/{id}` to `/api/upload/{id}/confirm`
- Add `POST /api/upload/local/{analysis_id}` endpoint to `backend/app/routers/upload.py`: receives multipart video and writes it to the local `uploads/` directory for dev environments without S3 configured
- Fix: run `alembic upgrade head` to create missing `analyses` table in local SQLite (table existed only as alembic metadata, causing 500 on all upload requests)

### Added
- Add interactive HTML pipeline diagram (`docs/pipeline-diagram.html`): expandable stage cards showing function signatures, internal logic, and output dataclasses with exact field types and shapes; typed arrow connectors between stages; color-coded by concern (extraction, analysis, intelligence, storage)

### Fixed (verify.py and dependency setup — post-sprint audit)
- Fix `backend/pyproject.toml`: move pytest/pytest-asyncio/aiosqlite from `[project.optional-dependencies]` to `[dependency-groups]` so `uv sync` installs them by default
- Create `backend/.gitignore`: Python, venv, .env, test cache, *.npy, local uploads dir
- Fix `scripts/verify.py`: replace `uv run pytest` with `uv run python -m pytest` (script wasn't in PATH)
- Fix `scripts/verify.py`: replace shell `timeout` + `&` background job with Python `subprocess.Popen` + `urllib` polling (GNU `timeout` not available on macOS)
- Fix `scripts/verify.py`: correct script paths (`backend/scripts/` → `scripts/`) for `generate_synthetic_reference.py` and `test_e2e.py`
- Fix `scripts/verify.py`: narrow secrets grep from `aws_secret` (matched field names) to actual key format patterns (`sk-ant-api`, `AKIA[A-Z0-9]`)
- Result: `python3 scripts/verify.py all` → 102 passed, 0 failed

### Added (Task 2.5 — Full integration and deployment prep)
- Create `docker-compose.yml`: redis, backend, worker, frontend services with health checks and shared REDIS_URL override
- Create `backend/Dockerfile`: Python 3.11-slim + ffmpeg via apt, uv, layer-cached dependency install
- Create `frontend/Dockerfile`: Node 20-alpine multi-stage (dev/build/prod targets)
- Create `backend/Procfile`: Railway-compatible `web` and `worker` process types
- Create `README.md`: project description, architecture diagram, local dev setup, env vars table, pro reference build guide, deploy instructions, tech stack
- Create `scripts/dev_setup.sh`: checks python/uv/node/npm/ffmpeg/redis, installs deps, creates .env from example, generates synthetic reference
- Update `frontend/vite.config.js`: add `/api` proxy to `http://localhost:8000` for local dev without CORS friction

### Added (Task 2.4 — History page and navigation polish)
- Create `src/pages/History.jsx`: fetches `GET /api/history`, skeleton loading (3 pulse cards), color-coded score + status badge cards, empty state with CTA, click navigates to `/analysis/:id`
- Create `src/pages/NotFound.jsx`: 404 page for unknown routes via `<Route path="*">`
- Create `src/components/Spinner.jsx`: reusable animated ring, size via `className` prop
- Create `src/components/ErrorBoundary.jsx`: class component catching render errors, shows message + Go Home link
- Update `src/App.jsx`: logo as `<Link>`, footer ("Built by Brian - Powered by MediaPipe + Claude"), 404 route, `ErrorBoundary` wrapping all routes, `flex flex-col` layout so footer stays at bottom

### Added (Task 2.3 — Analysis results page)
- Create `src/hooks/useAnalysis.js`: polls `GET /api/analysis/{id}` every 2s, stops on `completed`/`failed`, returns `{ analysis, isLoading, error, isProcessing }`
- Create `src/components/ProcessingState.jsx`: spinner with staggered stage-hint dots
- Create `src/components/ScoreGauge.jsx`: SVG circular ring, 4-tier color thresholds (green/yellow/orange/red)
- Create `src/components/PhaseBreakdown.jsx`: 5-phase horizontal bar chart with color-coded scores
- Create `src/components/DeviationCard.jsx`: joint/phase/severity-badge/angle-diff cards; severity derived from angle_diff magnitude
- Create `src/components/CoachingFeedback.jsx`: accordion priority fixes, drill plan grid, green positive-notes callouts
- Build `src/pages/Analysis.jsx`: three states (processing/failed/completed), responsive 2-col score+phases layout

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
