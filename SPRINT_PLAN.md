# Sprint Plan — SwingCoach MVP (2 Weeks)

## How to Use This Plan in Claude Code

Each task below is scoped to be completable in a single Claude Code session.
Execute them in order. Copy the task heading + description as your prompt.

**Pattern for each task:**
1. Copy the task section into Claude Code as your prompt
2. Let it execute
3. Verify the acceptance criteria manually
4. Move to the next task

**Do NOT try to combine multiple tasks into one prompt.** Each task is sized
for Sonnet's context window and attention budget. Combining them causes drift.

---

## Week 1: Backend Pipeline (Days 1-5)

### Task 1.1 — Project scaffolding and dependencies

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Set up the backend project structure:

1. Create backend/ directory with the structure from CLAUDE.md
2. Create pyproject.toml with these dependencies:
   - fastapi, uvicorn[standard], python-multipart
   - mediapipe, opencv-python-headless, numpy, scipy
   - tslearn (for DTW)
   - anthropic
   - pydantic-settings, python-dotenv
   - boto3 (S3)
   - rq, redis
   - sqlalchemy, asyncpg, alembic
   - httpx (for async HTTP)
   - pytest, pytest-asyncio (dev)

3. Create app/config.py using pydantic-settings:
   - SUPABASE_URL, SUPABASE_KEY
   - S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
   - REDIS_URL (default: redis://localhost:6379)
   - ANTHROPIC_API_KEY
   - ALLOWED_ORIGINS (comma-separated, default: http://localhost:5173)
   - MAX_VIDEO_DURATION_SECONDS (default: 30)
   - MAX_VIDEO_SIZE_MB (default: 100)

4. Create app/main.py with FastAPI app:
   - CORS middleware using ALLOWED_ORIGINS from config
   - Include routers for health, upload, analysis
   - Lifespan handler that logs startup/shutdown

5. Create app/routers/health.py:
   - GET /api/health → {"status": "ok", "version": "0.1.0"}

6. Create a .env.example with all required env vars (empty values)
7. Create a .gitignore (Python defaults + .env + __pycache__ + *.npy)

Use uv for package management. Make sure `uv run uvicorn app.main:app --reload`
starts successfully (it's fine if other routers are stubs).
```

**Acceptance criteria:**
- [ ] `uv run uvicorn app.main:app --reload` starts without errors
- [ ] `curl localhost:8000/api/health` returns 200 with JSON
- [ ] All directories from CLAUDE.md structure exist
- [ ] `.env.example` has all config vars listed

---

### Task 1.2 — Database models and Supabase connection

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Create the database layer:

1. Create app/models.py with SQLAlchemy models + Pydantic schemas:

   Analysis (SQLAlchemy model):
   - id: UUID, primary key, default=uuid4
   - user_id: String, nullable (no auth yet, will be added)
   - status: Enum("pending", "processing", "completed", "failed")
   - stroke_type: Enum("forehand", "backhand_one", "backhand_two", "serve_flat", "serve_kick", "serve_slice", "volley")
   - video_s3_key: String
   - pro_reference: String (which pro was compared against)
   - pose_data: JSON (nullable, stores extracted landmarks as serialized array)
   - phase_scores: JSON (nullable, dict of phase→score)
   - deviations: JSON (nullable, list of deviation dicts)
   - coaching_feedback: JSON (nullable, Claude's structured response)
   - overall_score: Float (nullable)
   - error_message: String (nullable)
   - created_at: DateTime, default=utcnow
   - completed_at: DateTime, nullable
   - processing_time_ms: Integer, nullable

   AnalysisCreate (Pydantic — request body):
   - stroke_type: StrokeType enum
   - pro_reference: str = "federer" (default)

   AnalysisResponse (Pydantic — API response):
   - All Analysis fields, serialized properly
   - Config: from_attributes = True

2. Create app/services/db.py:
   - get_engine() → create_async_engine from DATABASE_URL
   - get_session() → async context manager yielding AsyncSession
   - For MVP: support both Supabase Postgres URL and local sqlite for dev
     (detect from DATABASE_URL scheme)

3. Create an alembic.ini and initial migration that creates the analyses table.

Use async SQLAlchemy throughout. The DATABASE_URL env var should work with both
postgresql+asyncpg:// (production) and sqlite+aiosqlite:// (local dev).
Add aiosqlite to dev dependencies for local testing.
```

**Acceptance criteria:**
- [ ] Migration runs successfully against local SQLite
- [ ] Can create and query an Analysis record programmatically
- [ ] Pydantic schemas serialize/deserialize correctly
- [ ] Enum values are validated on input

---

### Task 1.3 — S3 service and video upload endpoint

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the video upload flow:

1. Create app/services/s3.py:
   - generate_presigned_upload_url(key: str, content_type: str) → str
     Generates a presigned PUT URL for direct browser→S3 upload. Expires in 10 min.
   - generate_presigned_download_url(key: str) → str
     For video playback later. Expires in 1 hour.
   - For local dev without S3: add a fallback that saves to a local
     uploads/ directory and returns a file:// URL. Switch based on whether
     S3_BUCKET is set.

2. Create app/routers/upload.py:
   - POST /api/upload
     Request body: { stroke_type: str, pro_reference: str }
     Response: { analysis_id: uuid, upload_url: str, s3_key: str }
     Steps:
       a. Validate stroke_type against the enum
       b. Generate S3 key: "uploads/{analysis_id}/{timestamp}.mp4"
       c. Generate presigned upload URL
       d. Create Analysis record with status="pending"
       e. Return the presigned URL and analysis ID
       (The frontend uploads directly to S3, then calls a confirm endpoint)

   - POST /api/upload/{analysis_id}/confirm
     Called after frontend finishes S3 upload.
     Steps:
       a. Verify the analysis exists and is "pending"
       b. Update status to "processing"
       c. Enqueue the RQ job (import but stub the task for now)
       d. Return { analysis_id, status: "processing" }

3. Create app/routers/analysis.py:
   - GET /api/analysis/{analysis_id}
     Returns the full AnalysisResponse. Frontend polls this.
   - GET /api/history
     Returns list of AnalysisResponse, ordered by created_at desc.
     Query param: limit (default 20)

All endpoints should use proper HTTP status codes (201 for creation,
404 for not found, 422 for validation errors).
```

**Acceptance criteria:**
- [ ] POST /api/upload returns presigned URL + analysis ID (or local path in dev)
- [ ] POST /api/upload/{id}/confirm updates status and returns 200
- [ ] GET /api/analysis/{id} returns the analysis record
- [ ] GET /api/history returns a list
- [ ] Invalid stroke_type returns 422
- [ ] Non-existent analysis ID returns 404

---

### Task 1.4 — Frame extraction with FFmpeg

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the frame extraction stage of the pipeline:

1. Create app/worker/frame_extractor.py:

   def extract_frames(video_path: str, output_dir: str, target_fps: int | None = None) -> FrameExtractionResult:
       """
       Extract frames from a video file using FFmpeg.

       Args:
           video_path: Path to the input video file
           output_dir: Directory to write frame PNGs
           target_fps: If set, downsample to this FPS. If None, use native FPS.
                       For 120fps input, we might downsample to 30fps for faster processing.

       Returns:
           FrameExtractionResult:
               frame_paths: list[str]  — sorted paths to extracted PNGs
               fps: float              — actual FPS of extracted frames
               duration_seconds: float — video duration
               total_frames: int      — number of frames extracted
               resolution: tuple[int, int] — (width, height)

       Raises:
           ValueError: if video is longer than MAX_VIDEO_DURATION_SECONDS
           RuntimeError: if FFmpeg fails
       """

   Implementation details:
   - Use subprocess.run to call ffmpeg (not a Python wrapper library)
   - First, probe the video with ffprobe to get duration, fps, resolution
   - Validate duration <= config.MAX_VIDEO_DURATION_SECONDS
   - Extract frames as frame_%05d.png
   - If target_fps is set, use ffmpeg's -vf fps={target_fps} filter
   - If input is >60fps (slow-mo), default target_fps to 30 to keep processing fast
   - Log frame count and extraction time

2. Create tests/test_frame_extractor.py:
   - Test with a fixture: generate a 3-second synthetic test video using ffmpeg
     (solid color frames with a counter, created in conftest.py)
   - Test that frame count matches expected FPS × duration
   - Test that ValueError is raised for >30s video
   - Test that output PNGs exist and are valid images

Make sure ffmpeg is available in the environment (add a check at module level
that raises a clear error if ffmpeg is not installed).
```

**Acceptance criteria:**
- [ ] Extracts frames from a test video correctly
- [ ] Frame count matches FPS × duration (±1)
- [ ] Rejects videos longer than MAX_VIDEO_DURATION_SECONDS
- [ ] Returns correct metadata (fps, duration, resolution)
- [ ] All tests pass

---

### Task 1.5 — MediaPipe pose estimation

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the pose estimation stage:

1. Create app/worker/pose_estimator.py:

   def extract_poses(frame_paths: list[str]) -> PoseEstimationResult:
       """
       Run MediaPipe BlazePose on each frame to extract body landmarks.

       Args:
           frame_paths: Sorted list of paths to frame PNG files

       Returns:
           PoseEstimationResult:
               landmarks: np.ndarray, shape (num_frames, 33, 3)
                   — x, y, z coordinates per landmark per frame
                   — x, y are normalized [0, 1] relative to image dimensions
                   — z is depth relative to hip midpoint
               visibility: np.ndarray, shape (num_frames, 33)
                   — per-landmark confidence scores
               frames_processed: int
               frames_with_pose: int  — frames where a person was detected
               detection_rate: float  — frames_with_pose / frames_processed

       Raises:
           ValueError: if detection_rate < 0.5 (too few frames with a visible person)
       """

   Implementation:
   - Use mediapipe.solutions.pose with:
       static_image_mode=True (processing individual frames, not video stream)
       model_complexity=2 (highest accuracy — we're not doing real-time)
       min_detection_confidence=0.5
   - For frames where no pose is detected, interpolate from neighboring frames
     (simple linear interpolation). If >50% of frames have no pose, raise ValueError.
   - Return numpy arrays, NOT mediapipe objects (they're not serializable)

2. Define the landmark index mapping as a module-level constant:
   LANDMARK_NAMES = {
       0: "nose", 11: "left_shoulder", 12: "right_shoulder",
       13: "left_elbow", 14: "right_elbow",
       15: "left_wrist", 16: "right_wrist",
       23: "left_hip", 24: "right_hip",
       25: "left_knee", 26: "right_knee",
       27: "left_ankle", 28: "right_ankle",
       # include all 33 but these are the ones we'll use most
   }

3. Create tests/test_pose_estimator.py:
   - Test with a fixture: use a real image of a person (download a public domain
     stock photo in conftest.py, or generate a simple stick figure with OpenCV)
   - Test that output shape is correct
   - Test that detection_rate > 0 for valid input
   - Test that ValueError is raised when passing blank frames

Note: MediaPipe's model files download automatically on first use (~30MB).
Add mediapipe model cache to .gitignore.
```

**Acceptance criteria:**
- [ ] Returns numpy array of shape (N, 33, 3) for N frames
- [ ] Visibility scores are populated
- [ ] Detection rate calculation is correct
- [ ] Interpolation fills gaps for missing frames
- [ ] Raises ValueError when person not visible in majority of frames
- [ ] Tests pass

---

### Task 1.6 — Feature extraction and phase segmentation

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the feature extraction and phase segmentation engine. This is the
core biomechanics logic — it turns raw landmarks into coaching-relevant metrics.

1. Create app/worker/feature_engine.py:

   def extract_features(
       landmarks: np.ndarray,  # (num_frames, 33, 3)
       fps: float,
       stroke_type: str,       # from StrokeType enum
       handedness: str = "right"  # "right" or "left"
   ) -> FeatureExtractionResult:

   FeatureExtractionResult:
       joint_angles: dict[str, np.ndarray]
           Keys and how to compute:
           - "elbow_angle": angle at elbow (shoulder→elbow→wrist), hitting arm
           - "shoulder_rotation": angle of shoulder line relative to baseline/net
           - "hip_rotation": angle of hip line relative to baseline
           - "trunk_rotation": angle between hip line and shoulder line
           - "knee_bend": angle at front knee (hip→knee→ankle)
           - "racket_arm_elevation": angle of upper arm relative to torso
       velocities: dict[str, np.ndarray]
           - "wrist_speed": magnitude of wrist velocity (pixels/frame → m/s estimate)
           - "elbow_speed": same for elbow
           - "hip_speed": same for hip midpoint
       phases: dict[str, tuple[int, int]]
           Frame ranges for each phase:
           - "preparation": from start until backswing begins
           - "backswing": racket moving backward (wrist moving away from net)
           - "forward_swing": racket moving forward toward contact
           - "contact": the ~3-frame window around peak wrist speed
           - "follow_through": from contact to end
       contact_frame: int  — the single frame of peak racket speed

   Helper functions to implement:
   - compute_angle(a, b, c) → float
     Angle at point b formed by vectors b→a and b→c using np.arctan2
   - compute_velocity(positions, fps) → np.ndarray
     First derivative of position timeseries, smoothed with Savitzky-Golay filter
   - detect_phases(wrist_positions, wrist_velocities, stroke_type) → dict
     Phase detection logic:
       1. Find contact_frame = argmax(wrist_speed)
       2. Find backswing_start: before contact, find where wrist velocity
          changes sign (from forward to backward)
       3. Find forward_swing_start: after backswing peak, wrist velocity
          changes sign again (backward to forward)
       4. follow_through_start = contact_frame + 1
       5. preparation = (0, backswing_start)

   For handedness="left", mirror the landmark indices (swap left↔right).
   Use scipy.signal.savgol_filter for smoothing velocities (window=7, polyorder=2).

2. Create tests/test_feature_engine.py:
   - Test compute_angle with known geometries (90°, 180°, 45°)
   - Test compute_velocity with a linear position series
   - Test phase detection with a synthetic sinusoidal wrist trajectory
   - Test that left-hand mirroring swaps the correct landmarks
```

**Acceptance criteria:**
- [ ] Joint angles are in degrees, range 0-360
- [ ] Velocities are smoothed (no noise spikes)
- [ ] Phase detection finds all 5 phases with non-overlapping frame ranges
- [ ] Contact frame is at peak wrist speed
- [ ] Left-hand mirroring produces correct landmark swaps
- [ ] All tests pass

---

### Task 1.7 — DTW comparator and pro reference loader

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the DTW comparison engine and pro reference data management:

1. Create app/pro_references/loader.py:

   class ProReferenceDB:
       """Loads and manages pre-computed professional swing data."""

       def __init__(self, data_dir: str = "app/pro_references/data"):
           self.references: dict[str, dict] = {}
           # Key: "{player}_{stroke_type}" e.g. "federer_forehand"
           # Value: {
           #   "player": str,
           #   "stroke_type": str,
           #   "joint_angles": dict[str, np.ndarray],
           #   "phases": dict[str, tuple[int, int]],
           #   "metadata": dict  # any extra info
           # }

       def load_all(self):
           """Load all .npz files from data_dir"""

       def get_reference(self, player: str, stroke_type: str) -> dict | None:
           """Get a specific reference swing"""

       def list_available(self) -> list[dict]:
           """Return list of {player, stroke_type} dicts"""

   Also create a save_reference() function for the build script to use.

2. Create scripts/build_pro_references.py:
   """
   Process a pro player video into a reference .npz file.
   Usage: python build_pro_references.py --video path.mp4 --stroke forehand --player federer
   """
   Pipeline:
   a. Extract frames (reuse frame_extractor)
   b. Run pose estimation (reuse pose_estimator)
   c. Extract features (reuse feature_engine)
   d. Save as .npz to app/pro_references/data/{player}_{stroke}.npz

3. Create scripts/generate_synthetic_reference.py:
   """
   Generate a SYNTHETIC pro reference for testing when no real video is available.
   Creates a plausible forehand swing trajectory using parameterized sine curves.
   """
   This is crucial for development — we need a reference to test against
   before Brian records real pro swings.
   Generate smooth, realistic-ish joint angle curves for:
   - A forehand with proper kinetic chain timing
   - ~60 frames at 30fps (2 seconds)
   Save as app/pro_references/data/synthetic_forehand.npz

4. Create app/worker/dtw_comparator.py:

   def compare_swing(
       user_features: FeatureExtractionResult,
       pro_reference: dict,  # from ProReferenceDB
   ) -> ComparisonResult:

   ComparisonResult:
       overall_score: float           # 0-100 (100 = identical to pro)
       phase_scores: dict[str, float] # per-phase 0-100
       deviations: list[Deviation]    # sorted by severity (worst first)

   Deviation:
       joint: str          # e.g. "elbow_angle"
       phase: str          # e.g. "forward_swing"
       mean_diff_degrees: float  # average angle difference in this phase
       max_diff_degrees: float   # peak difference
       timing_offset_ms: float   # how much earlier/later the user's motion is
       severity: str       # "critical" | "moderate" | "minor"
       description: str    # human-readable: "Elbow angle 18° wider than reference during forward swing"

   Implementation:
   - For each joint angle timeseries and each phase:
     a. Extract the user's segment for that phase
     b. Extract the pro's segment for the same phase
     c. Normalize both to the same length (resample with np.interp)
     d. Compute DTW distance using tslearn.metrics.dtw
     e. Also compute the DTW alignment path to find timing offsets
   - Convert DTW distances to 0-100 scores using an exponential decay:
     score = 100 * exp(-dtw_distance / scale_factor)
     Use scale_factor=50 (tunable later)
   - Overall score = weighted average of phase scores
     Weights: preparation=0.05, backswing=0.15, forward_swing=0.35,
              contact=0.30, follow_through=0.15
   - Build deviations list by finding joints × phases with score < 70
   - Severity: <40 = critical, 40-60 = moderate, 60-70 = minor

5. Create tests/test_dtw_comparator.py:
   - Test with identical inputs → score should be 100
   - Test with completely different inputs → score should be <30
   - Test that deviations are sorted by severity
   - Test that timing offsets are computed correctly
```

**Acceptance criteria:**
- [ ] Synthetic reference generates and saves as .npz
- [ ] ProReferenceDB loads .npz files correctly
- [ ] DTW comparison of identical swings returns score ~100
- [ ] DTW comparison of different swings returns low score with deviations
- [ ] Deviations include human-readable descriptions
- [ ] Phase weighting works correctly
- [ ] All tests pass

---

### Task 1.8 — Claude feedback generator

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the coaching feedback generator using Claude API:

1. Create app/worker/feedback_generator.py:

   async def generate_coaching_feedback(
       comparison: ComparisonResult,
       stroke_type: str,
       pro_reference_name: str,
   ) -> CoachingFeedback:

   CoachingFeedback:
       summary: str              # 2-3 sentence overview of the swing
       overall_assessment: str   # "beginner" | "intermediate" | "advanced" | "pro-level"
       priority_fixes: list[Fix] # top 3 things to work on, ordered by impact
       positive_notes: list[str] # 2-3 things the player is doing well
       drill_plan: list[Drill]   # specific drills to address priority fixes

   Fix:
       title: str           # e.g. "Late hip rotation"
       explanation: str     # what's happening and why it matters (2-3 sentences)
       target_metric: str   # which joint/angle to improve
       current_value: str   # "Your hip rotation starts 80ms after your shoulder"
       target_value: str    # "Pro reference shows hip leading shoulder by 20ms"

   Drill:
       name: str            # e.g. "Shadow swing with pause at trophy position"
       description: str     # step-by-step instructions (3-5 sentences)
       duration: str        # e.g. "10 minutes"
       frequency: str       # e.g. "Before each practice session"
       focus_area: str      # which Fix this addresses

   Implementation:
   - Use the anthropic Python SDK
   - Model: claude-sonnet-4-20250514
   - System prompt should establish:
     a. You are an expert tennis coach analyzing a student's swing
     b. You have data comparing the student's {stroke_type} to {pro_reference_name}
     c. Provide actionable, specific feedback — not generic advice
     d. Drills should be progressive (easy → harder) and specific to the deviations
     e. Be encouraging but honest
     f. RESPOND ONLY IN JSON matching the CoachingFeedback schema (provide the schema)
   - User message: serialize the ComparisonResult (overall_score, phase_scores,
     deviations list with all fields)
   - Parse the JSON response into CoachingFeedback
   - If JSON parsing fails, retry once with a "please respond only in valid JSON" nudge
   - Max tokens: 2000
   - Temperature: 0.3 (we want consistent, structured output)

2. Create tests/test_feedback_generator.py:
   - Create a mock ComparisonResult with known deviations
   - Test that the response parses into CoachingFeedback correctly
   - Test that priority_fixes has <= 3 items
   - Test that drill_plan items reference actual fixes
   - Mark this test with @pytest.mark.skipif for CI (requires API key)

Add ANTHROPIC_API_KEY to .env.example.
```

**Acceptance criteria:**
- [ ] Claude returns structured JSON matching CoachingFeedback schema
- [ ] Feedback references specific deviations from the comparison data
- [ ] Drills are specific and actionable (not generic "practice more")
- [ ] Graceful handling of JSON parse failures (retry logic)
- [ ] Test passes when API key is available

---

### Task 1.9 — Worker task orchestration and end-to-end pipeline

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Wire all pipeline stages into the RQ worker task:

1. Create app/worker/tasks.py:

   def process_analysis(analysis_id: str):
       """
       Main RQ task. Orchestrates the full pipeline for one analysis.

       Steps:
       1. Fetch Analysis record from DB, update status → "processing"
       2. Download video from S3 to a temp directory
       3. Extract frames (frame_extractor)
       4. Run pose estimation (pose_estimator)
       5. Extract features (feature_engine)
       6. Load pro reference (pro_references.loader)
       7. Run DTW comparison (dtw_comparator)
       8. Generate coaching feedback (feedback_generator) — run async in sync context
       9. Update Analysis record with:
          - status → "completed"
          - pose_data (serialized landmarks — store as list, not numpy)
          - phase_scores
          - deviations
          - coaching_feedback
          - overall_score
          - completed_at
          - processing_time_ms
       10. Clean up temp directory (delete frames)

       On ANY exception:
       - Update Analysis: status → "failed", error_message = str(exception)
       - Log the full traceback
       - Clean up temp directory
       - Do NOT re-raise (RQ will handle retries if configured)
       """

   Implementation notes:
   - Use tempfile.mkdtemp() for the working directory
   - Use a try/finally to always clean up
   - Time the entire pipeline with time.perf_counter()
   - For the async feedback_generator call in sync RQ context:
     use asyncio.run(generate_coaching_feedback(...))
   - Serialize numpy arrays to lists before storing in JSON columns
   - Log each stage start/completion with timing

2. Create a run_worker.py at backend/ root:
   """Start the RQ worker."""
   from redis import Redis
   from rq import Worker, Queue
   redis = Redis.from_url(settings.REDIS_URL)
   queue = Queue(connection=redis)
   worker = Worker([queue], connection=redis)
   worker.work()

3. Update app/routers/upload.py confirm endpoint:
   - Import and enqueue process_analysis task properly
   - from rq import Queue; queue.enqueue(process_analysis, analysis_id)

4. Create an end-to-end test script (scripts/test_e2e.py):
   """
   End-to-end test: processes a test video through the full pipeline.
   NOT a pytest test — run manually: python scripts/test_e2e.py
   Requires: Redis running, .env configured, synthetic reference built.
   """
   Steps:
   a. Create a synthetic test video (3 seconds of a moving stick figure)
   b. Create an Analysis DB record manually
   c. Call process_analysis(analysis_id) directly (not via queue)
   d. Print the resulting analysis record (score, deviations, feedback)
   e. Assert status == "completed"

This is the integration point. If this works, the backend pipeline is done.
```

**Acceptance criteria:**
- [ ] Worker processes a test video end-to-end without errors
- [ ] Analysis record is updated with all result fields
- [ ] Processing time is logged and stored
- [ ] Failures update status to "failed" with error message
- [ ] Temp files are cleaned up even on failure
- [ ] e2e test script runs successfully with synthetic data

---

## Week 2: Frontend + Integration (Days 6-10)

### Task 2.1 — Frontend scaffolding

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Set up the React frontend:

1. Create frontend/ using Vite + React:
   npx create-vite frontend --template react
   cd frontend && npm install

2. Install dependencies:
   - tailwindcss @tailwindcss/vite (v4 — use the new CSS-based config)
   - react-router-dom
   - axios
   - react-dropzone (for drag-and-drop uploads)
   - lucide-react (icons)

3. Set up Tailwind CSS v4 (CSS-based, NOT tailwind.config.js):
   - Add @import "tailwindcss" to the main CSS file
   - Add the Tailwind Vite plugin to vite.config.js

4. Set up routing in App.jsx:
   - / → Upload page
   - /analysis/:id → Analysis results page
   - /history → Past analyses

5. Create src/lib/api.js:
   - Axios instance with baseURL from VITE_API_URL env var
   - Functions:
     createAnalysis(strokeType, proReference) → { analysis_id, upload_url }
     confirmUpload(analysisId) → { status }
     getAnalysis(analysisId) → AnalysisResponse
     getHistory(limit) → AnalysisResponse[]

6. Create placeholder pages (just a heading + basic layout):
   - Upload.jsx: "Upload Your Swing"
   - Analysis.jsx: "Analysis Results"
   - History.jsx: "Your Analyses"

7. Add a simple layout wrapper with:
   - App name "SwingCoach" in a top bar
   - Navigation links
   - Clean, minimal styling — dark theme, tennis green accent (#2D8653)

8. Create a .env with VITE_API_URL=http://localhost:8000

Verify: npm run dev starts and all 3 routes render.
```

**Acceptance criteria:**
- [ ] `npm run dev` starts successfully
- [ ] All 3 routes render with placeholder content
- [ ] Tailwind classes work (test with a colored div)
- [ ] API helper functions are importable
- [ ] Navigation between pages works

---

### Task 2.2 — Video upload page

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the Upload page (frontend/src/pages/Upload.jsx):

This is the main entry point. The user selects a stroke type, chooses a
pro to compare against, uploads a video, and gets redirected to the
analysis page while processing happens.

Components needed:

1. src/components/VideoUploader.jsx:
   - Drag-and-drop zone using react-dropzone
   - Accept only video/mp4, video/quicktime, video/mov
   - Max file size: 100MB
   - Show file name + size after selection
   - Video preview: render a <video> element so user can verify the clip
   - Show upload progress percentage

2. src/pages/Upload.jsx:
   - Stroke type selector: radio buttons or nice card selector
     Options: Forehand, One-handed Backhand, Two-handed Backhand,
     Flat Serve, Kick Serve, Slice Serve, Volley
   - Pro reference selector: dropdown or card selector
     Options: "Federer", "Nadal", "Djokovic", "Synthetic (test)"
     (We only have synthetic for now, but build the UI for real names)
   - The VideoUploader component
   - "Analyze" button (disabled until video selected + stroke type chosen)
   - Upload flow on submit:
     a. Call createAnalysis(strokeType, proReference)
     b. Upload the file directly to the presigned S3 URL via PUT
        (use axios with onUploadProgress for progress tracking)
     c. Call confirmUpload(analysisId)
     d. Navigate to /analysis/{analysisId}
   - Handle errors: show toast/alert if upload fails
   - Loading state on the button during upload

3. Styling:
   - Center the form, max-width 640px
   - The drop zone should be prominent — large dashed border area
   - Stroke type cards should feel tappable and give visual feedback on selection
   - Use the tennis green accent (#2D8653) for primary actions
   - Responsive: works on mobile screens

For local dev without S3: detect if upload_url starts with "file://" and
fall back to a POST multipart upload to the backend instead.
```

**Acceptance criteria:**
- [ ] Can drag-and-drop a video file
- [ ] Video preview plays the selected file
- [ ] Stroke type selection works with visual feedback
- [ ] Upload progress bar shows percentage
- [ ] After upload, navigates to /analysis/:id
- [ ] Disabled state when form is incomplete
- [ ] Error handling for oversized files

---

### Task 2.3 — Analysis results page

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the Analysis results page (frontend/src/pages/Analysis.jsx):

This page polls for results while processing, then displays the full
analysis when complete.

1. src/hooks/useAnalysis.js:
   - Custom hook: useAnalysis(analysisId)
   - Polls GET /api/analysis/{id} every 2 seconds while status is "pending" or "processing"
   - Stops polling when status is "completed" or "failed"
   - Returns: { analysis, isLoading, error, isProcessing }

2. src/pages/Analysis.jsx:
   States:
   a. PROCESSING: Show an animated loading state
      - "Analyzing your swing..." with a progress indicator
      - Show which stage is happening (if we add stage tracking later, just
        show a generic animation for now)
      - Estimated time remaining: "Usually takes 30-60 seconds"

   b. COMPLETED: Show full results
      Layout (scrollable single page):
      - Overall score: big number (0-100) with a circular gauge/ring
        Color: green (80+), yellow (60-79), orange (40-59), red (<40)
      - Phase breakdown: horizontal bar chart showing per-phase scores
        Phases: Preparation, Backswing, Forward Swing, Contact, Follow-through
      - Deviations list: cards for each deviation
        Each card shows: joint name, phase, severity badge (color-coded),
        angle difference, human-readable description
      - Coaching feedback section:
        - Summary paragraph
        - Priority fixes as expandable accordion items
          Each shows: title, explanation, current vs target values
        - Drills section: cards with name, description, duration, frequency
        - Positive notes: green-highlighted callouts
      - Pro reference comparison: "Compared against: {pro_name}'s {stroke_type}"

   c. FAILED: Show error message with a "Try Again" button (links back to /)

3. Components to create:
   - src/components/ScoreGauge.jsx — circular progress ring showing overall score
   - src/components/PhaseBreakdown.jsx — horizontal bars per phase
   - src/components/DeviationCard.jsx — individual deviation display
   - src/components/CoachingFeedback.jsx — the feedback section with accordions
   - src/components/ProcessingState.jsx — the loading animation

4. Styling:
   - Dark background, cards with subtle borders
   - Severity colors: critical=#EF4444, moderate=#F59E0B, minor=#3B82F6
   - Score gauge should be the visual centerpiece
   - Smooth transitions when data loads
   - Mobile-responsive: stack vertically on small screens
```

**Acceptance criteria:**
- [ ] Polls correctly and shows processing state
- [ ] Transitions to results display when analysis completes
- [ ] Overall score gauge renders with correct color
- [ ] Phase breakdown chart shows 5 phases with scores
- [ ] Deviation cards show all fields with severity badges
- [ ] Coaching feedback renders summary, fixes, drills, positives
- [ ] Failed state shows error and retry link
- [ ] Responsive on mobile viewports

---

### Task 2.4 — History page and navigation polish

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Build the History page and polish the app navigation:

1. src/pages/History.jsx:
   - Fetch analyses from GET /api/history
   - Display as a list of cards, each showing:
     - Date/time
     - Stroke type (with an icon or label)
     - Pro reference compared against
     - Overall score (color-coded number)
     - Status badge (completed/failed/processing)
   - Click a card → navigate to /analysis/{id}
   - Empty state: "No analyses yet. Upload your first swing!"
     with a link to /
   - Loading skeleton while fetching

2. Polish the app layout (App.jsx):
   - Top navigation bar:
     - "SwingCoach" logo/text on the left (link to /)
     - "Upload" and "History" nav links on the right
   - Footer: "Built by Brian • Powered by MediaPipe + Claude"
   - Active nav link styling

3. Add a 404 page for unknown routes

4. Add a loading spinner component (reusable)

5. Add error boundary that catches rendering errors gracefully

6. Make sure the entire app looks cohesive:
   - Consistent spacing (use Tailwind's space scale)
   - Consistent card styling across pages
   - Consistent typography hierarchy
   - Dark theme throughout
   - The tennis green (#2D8653) as accent, not overwhelming
```

**Acceptance criteria:**
- [ ] History page loads and displays past analyses
- [ ] Clicking a history card navigates to the analysis
- [ ] Empty state renders when no analyses exist
- [ ] Navigation highlights the active page
- [ ] 404 page renders for unknown routes
- [ ] App feels visually cohesive across all pages

---

### Task 2.5 — Full integration test and deployment prep

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context.

Final integration and deployment preparation:

1. CORS and proxy setup:
   - Make sure FastAPI CORS allows the frontend origin
   - Add a vite.config.js proxy: /api → http://localhost:8000
     so the frontend can use relative URLs in dev

2. Create a docker-compose.yml at project root for local dev:
   services:
     redis:
       image: redis:7-alpine
       ports: ["6379:6379"]
     backend:
       build: ./backend
       ports: ["8000:8000"]
       env_file: ./backend/.env
       depends_on: [redis]
       command: uvicorn app.main:app --host 0.0.0.0 --port 8000
     worker:
       build: ./backend
       env_file: ./backend/.env
       depends_on: [redis]
       command: python run_worker.py
     frontend:
       build: ./frontend
       ports: ["5173:5173"]

3. Create backend/Dockerfile:
   - Python 3.11 slim base
   - Install ffmpeg via apt-get
   - Install uv, copy pyproject.toml, uv sync
   - Copy app code
   - Expose 8000

4. Create frontend/Dockerfile:
   - Node 20 alpine
   - npm install, npm run build
   - Serve with a simple static server (or just use for dev)

5. Create a Railway-compatible setup:
   - backend/Procfile: web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
   - backend/railway.toml or nixpacks config if needed
   - Ensure ffmpeg is available in the Railway build

6. Create a comprehensive README.md at project root:
   - Project description
   - Architecture diagram (ASCII)
   - Local development setup (step by step)
   - Environment variables reference
   - How to build pro references
   - How to deploy
   - Tech stack summary

7. Run through a full manual test:
   a. docker-compose up
   b. Open http://localhost:5173
   c. Upload a test video
   d. Verify processing completes
   e. Verify results display correctly
   f. Check history page shows the analysis

   Document any issues found and fix them.

8. Add a scripts/dev_setup.sh that:
   - Checks for required tools (python, node, ffmpeg, redis)
   - Runs uv sync in backend/
   - Runs npm install in frontend/
   - Generates the synthetic pro reference
   - Creates .env from .env.example if it doesn't exist
   - Prints "Ready! Run docker-compose up to start."
```

**Acceptance criteria:**
- [ ] docker-compose up starts all services
- [ ] Frontend can reach backend through the proxy
- [ ] Full upload → process → display flow works end-to-end
- [ ] Dockerfiles build without errors
- [ ] README is comprehensive and accurate
- [ ] dev_setup.sh runs successfully on a clean machine
- [ ] No hardcoded secrets anywhere in the codebase

---

## Post-Sprint Checklist

After completing all tasks, verify:

- [ ] The synthetic reference is generated and committed
- [ ] A test video can be processed end-to-end
- [ ] Results display correctly in the frontend
- [ ] Error states are handled (bad video, no person detected, API failure)
- [ ] All Python tests pass: `cd backend && uv run pytest tests/ -v`
- [ ] Frontend builds without warnings: `cd frontend && npm run build`
- [ ] .env.example is complete and accurate
- [ ] README covers local dev setup completely
- [ ] No console.log() spam in frontend
- [ ] No print() statements in backend (only logging)
- [ ] Git history is clean with meaningful commit messages

## What's Next (Post-MVP Backlog)

- [ ] Supabase auth integration (magic link)
- [ ] Record real pro reference swings (Brian films them)
- [ ] Skeleton overlay on video playback (Canvas + pose data)
- [ ] Side-by-side video comparison (user vs pro)
- [ ] Progress tracking over time (same stroke, multiple analyses)
- [ ] React Native iOS wrapper with Expo
- [ ] Camera recording guide overlay (shows ideal filming position)
- [ ] Stripe integration for subscription billing
