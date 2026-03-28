# Feature Spec V2 — SwingCoach MVP

## Pro Reference Library + Visual Deviation Overlay + Comparison UI

**Date:** 2026-03-27
**Depends on:** Sprint 1 (Tasks 1.1–2.5) — all complete, 102 tests passing

---

## How to Use This Spec in Claude Code

Same pattern as SPRINT_PLAN.md. Each task is scoped for a single Claude Code session.

**Execution rules:**
1. Copy the task heading + prompt into Claude Code
2. Let it execute
3. Verify the acceptance criteria
4. Move to the next task

**Do NOT combine tasks.** Dependencies are explicit. Execute in order.

**Key context for every task:** Read CLAUDE.md first. The existing codebase has:
- Backend: FastAPI + RQ worker with full pipeline (frames → pose → features → DTW → Claude feedback)
- Frontend: React 18 + Vite + Tailwind v4, pages for Upload/Analysis/History
- Database: SQLAlchemy async (Supabase Postgres / local SQLite)
- Pro references: static `.npz` files in `backend/app/pro_references/data/`
- Tests: 102 passing via `uv run pytest tests/ -v`

---

## Architecture Decisions (Pre-Made)

These decisions are FINAL. Do not re-evaluate during implementation.

1. **Deviation visualization: client-side canvas overlay.** The frontend already has `SkeletonOverlay.jsx`. Ship aligned landmark arrays for both swings to the browser. The frontend draws dual skeletons on a canvas synced to video playback. No server-side video compositing.

2. **Pro Library: database-backed, user-uploadable.** Pro references move from static `.npz` files to a `ProReference` DB table. Users upload pro videos through the UI, which triggers the same FFmpeg → MediaPipe → Feature Engine pipeline (no DTW, no Claude). The existing `build_pro_references.py` logic becomes an RQ background job.

3. **Phase alignment: frame-index mapping.** Both user and pro swings are segmented into 5 phases. For the overlay, resample each phase of both swings to the same frame count using `np.interp`. This produces a 1:1 frame mapping so skeletons can be drawn on top of each other.

4. **Priority order:** Pro Library (Tasks 3.1–3.4) → Deviation Overlay backend (Tasks 4.1–4.3) → Frontend Comparison UI (Tasks 5.1–5.4) → Integration (Task 6.1).

---

## Phase 3: Pro Reference Library (Backend + Frontend)

### Task 3.1 — ProReference database model and migration

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.

Add a ProReference model to the database to support user-uploadable
pro swing references. Currently pro references are static .npz files
in backend/app/pro_references/data/. We're moving to a DB-backed model
so users can upload and manage their own library of pro swings.

1. Add to app/models.py — new SQLAlchemy model:

   ProReference:
   - id: UUID, primary key, default=uuid4
   - player_name: String, required (e.g. "Roger Federer")
   - player_slug: String, unique index (e.g. "roger-federer", auto-generated)
   - stroke_type: Enum (reuse existing StrokeType)
   - video_s3_key: String, nullable (original uploaded video)
   - thumbnail_s3_key: String, nullable (auto-generated thumbnail from video)
   - npz_path: String, nullable (path to computed .npz feature file)
   - status: Enum("pending", "processing", "ready", "failed")
   - error_message: String, nullable
   - frame_count: Integer, nullable (number of frames extracted)
   - fps: Float, nullable
   - duration_seconds: Float, nullable
   - is_builtin: Boolean, default=False (True for pre-shipped references)
   - metadata_json: JSON, nullable (extra info: source URL, notes, etc.)
   - created_at: DateTime, default=utcnow
   - processed_at: DateTime, nullable

   Pydantic schemas:
   - ProReferenceCreate: player_name, stroke_type, metadata_json (optional)
   - ProReferenceResponse: all fields, from_attributes=True
   - ProReferenceListItem: id, player_name, player_slug, stroke_type,
     status, thumbnail_s3_key, is_builtin, created_at (lightweight for list views)

2. Create Alembic migration for the new table.

3. Add a slug generation utility:
   - slugify(name: str) -> str
   - "Roger Federer" -> "roger-federer"
   - "Carlos Alcaraz" -> "carlos-alcaraz"
   - Handle duplicates by appending -2, -3, etc.

4. Create a data migration script (scripts/migrate_static_references.py):
   - Scan backend/app/pro_references/data/*.npz
   - For each .npz file, create a ProReference record with:
     - player_name derived from filename (e.g. "synthetic_forehand.npz" -> "Synthetic")
     - stroke_type from filename
     - npz_path pointing to existing file
     - status = "ready"
     - is_builtin = True
   - This preserves backward compatibility with existing references.

5. Update app/pro_references/loader.py:
   - ProReferenceDB should now query the database for references with status="ready"
   - Keep the .npz file loading logic (load from npz_path)
   - Add method: get_by_id(ref_id: UUID) -> dict | None
   - Add method: list_available() -> list[ProReferenceListItem]
   - Deprecate but don't remove the old file-scan logic (fallback)

6. Add tests in tests/test_pro_reference_model.py:
   - CRUD operations on ProReference
   - Slug generation and uniqueness
   - ProReferenceDB loading from DB records
   - Migration script creates correct records from existing .npz files

Run: uv run pytest tests/ -v (all tests including new ones must pass)
Update CHANGELOG.md with what was added.
```

**Acceptance criteria:**
- [ ] Alembic migration creates `pro_references` table
- [ ] ProReference CRUD works with async SQLAlchemy
- [ ] Slug generation handles duplicates
- [ ] Migration script imports existing .npz files as DB records
- [ ] ProReferenceDB loads references from DB
- [ ] Existing analysis pipeline still works (backward compatible)
- [ ] All tests pass

---

### Task 3.2 — Pro reference upload API and processing pipeline

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Task 3.1 must be completed first (ProReference DB model exists).

Build the API endpoints and background processing pipeline for uploading
pro reference videos. The pipeline reuses existing stages (FFmpeg, MediaPipe,
Feature Engine) but does NOT run DTW or Claude feedback — it just builds
the .npz reference file.

1. Create app/routers/pro_references.py — new router:

   POST /api/pro-references
     Request body: { player_name: str, stroke_type: str, metadata: dict (optional) }
     Response: { reference_id: uuid, upload_url: str, s3_key: str }
     Steps:
       a. Generate slug from player_name, check uniqueness for this stroke_type
       b. Generate S3 key: "pro-references/{reference_id}/{timestamp}.mp4"
       c. Generate presigned upload URL (reuse s3.py)
       d. Create ProReference record with status="pending"
       e. Return presigned URL and reference_id

   POST /api/pro-references/{reference_id}/confirm
     Called after frontend finishes uploading to S3.
     Steps:
       a. Verify reference exists and is "pending"
       b. Update status to "processing"
       c. Enqueue process_pro_reference RQ job
       d. Return { reference_id, status: "processing" }

   GET /api/pro-references
     List all pro references. Returns list of ProReferenceListItem.
     Query params:
       - stroke_type: filter by stroke (optional)
       - status: filter by status (optional, default shows all)
       - include_builtin: bool (default True)
     Sort by: player_name ASC

   GET /api/pro-references/{reference_id}
     Full detail for one reference. Returns ProReferenceResponse.

   DELETE /api/pro-references/{reference_id}
     Delete a pro reference.
     - Cannot delete is_builtin references (return 403)
     - Delete .npz file from disk
     - Delete video from S3
     - Delete DB record
     - Return 204

   POST /api/pro-references/{reference_id}/reprocess
     Re-run the processing pipeline on an existing reference.
     Useful if the pipeline code improves.
     - Set status back to "processing"
     - Delete old .npz
     - Enqueue process_pro_reference job
     - Return { reference_id, status: "processing" }

2. Create app/worker/pro_reference_tasks.py:

   def process_pro_reference(reference_id: str):
       """
       RQ task. Processes a pro reference video into a .npz feature file.

       Steps:
       1. Fetch ProReference from DB, verify status is "processing"
       2. Download video from S3 to temp dir
       3. Extract frames (frame_extractor) — same as analysis pipeline
       4. Run pose estimation (pose_estimator)
       5. Extract features (feature_engine)
       6. Generate thumbnail: extract middle frame, resize to 320x180, save as JPEG
       7. Upload thumbnail to S3
       8. Save features as .npz to app/pro_references/data/{slug}_{stroke}.npz
          Store in the .npz:
            - joint_angles (dict of arrays)
            - velocities (dict of arrays)
            - phases (dict of tuples)
            - landmarks (full numpy array for overlay rendering)
            - metadata (player name, stroke, fps, frame_count)
       9. Update ProReference record:
          - status = "ready"
          - npz_path = path to .npz file
          - thumbnail_s3_key = S3 key
          - frame_count, fps, duration_seconds
          - processed_at = utcnow
       10. Clean up temp dir

       On failure:
       - status = "failed", error_message = str(exception)
       - Clean up temp dir
       """

3. Register the new router in app/main.py:
   app.include_router(pro_references_router, prefix="/api")

4. Add tests in tests/test_pro_reference_api.py:
   - POST create returns presigned URL
   - POST confirm transitions status and enqueues job
   - GET list returns references with correct filtering
   - GET detail returns full reference
   - DELETE removes non-builtin reference
   - DELETE returns 403 for builtin reference
   - Test process_pro_reference task with synthetic video (mock pose estimator)

Run: uv run pytest tests/ -v
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] POST /api/pro-references creates a reference and returns upload URL
- [ ] POST /api/pro-references/{id}/confirm enqueues processing
- [ ] process_pro_reference generates .npz and thumbnail
- [ ] GET /api/pro-references returns filterable list
- [ ] DELETE works for user-uploaded, blocked for builtins
- [ ] Reprocess endpoint re-runs pipeline
- [ ] All tests pass

---

### Task 3.3 — Pro Library frontend page

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Tasks 3.1 and 3.2 must be completed first.

Build the Pro Library management page in the frontend. Users can view
all available pro references, upload new ones, and manage their library.

1. Add API functions to src/lib/api.js:
   - getProReferences(filters?) -> ProReferenceListItem[]
   - getProReference(id) -> ProReferenceResponse
   - createProReference(playerName, strokeType, metadata?) -> { reference_id, upload_url }
   - confirmProReference(referenceId) -> { status }
   - deleteProReference(referenceId) -> void
   - reprocessProReference(referenceId) -> { status }

2. Create src/pages/ProLibrary.jsx:

   Layout: full-width page with two sections:

   A. HEADER SECTION:
      - Title: "Pro Reference Library"
      - Subtitle: "Upload pro player swings to compare against"
      - "Add Pro Reference" button (opens upload modal)
      - Filter bar:
        - Stroke type dropdown (All, Forehand, Backhand, Serve, etc.)
        - Status filter (All, Ready, Processing, Failed)

   B. REFERENCE GRID:
      - Responsive grid: 3 columns desktop, 2 tablet, 1 mobile
      - Each card (ProReferenceCard component):
        - Thumbnail image (or placeholder silhouette if no thumbnail)
        - Player name (large text)
        - Stroke type badge
        - Status indicator:
          - Ready: green dot
          - Processing: spinning indicator + "Processing..."
          - Failed: red dot + "Failed" (click to see error)
        - "Built-in" badge for is_builtin=true references
        - Footer: created date + action menu (reprocess, delete)
        - Click card -> detail view or just select for comparison
      - Empty state: "No pro references yet. Upload your first!"
      - Loading: skeleton card grid (6 cards)

3. Create src/components/AddProReferenceModal.jsx:

   A modal dialog for uploading a new pro reference:
   - Player name text input (required)
   - Stroke type selector (same card selector from Upload page)
   - Video upload zone (reuse VideoUploader component from Upload page)
   - "Upload & Process" button
   - Upload flow:
     a. createProReference(name, stroke)
     b. Upload video to presigned URL with progress bar
     c. confirmProReference(id)
     d. Close modal, show toast "Processing started"
     e. The card appears in the grid with "Processing..." status
   - Cancel button

4. Create src/components/ProReferenceCard.jsx:
   - Thumbnail with aspect ratio 16:9, rounded corners
   - Status overlay in top-right corner
   - Hover effect: slight scale + shadow
   - Context menu (three dots):
     - "Reprocess" (calls reprocessProReference)
     - "Delete" (confirmation dialog first, then deleteProReference)
     - Disabled for builtin references

5. Add route to App.jsx:
   - /library -> ProLibrary page
   - Add "Library" to the navigation bar (between "Upload" and "History")

6. Auto-refresh: poll GET /api/pro-references every 5 seconds while any
   reference has status="processing" to update the grid as processing completes.

Styling: match existing dark theme with tennis green (#2D8653) accent.
Cards should feel premium — clean borders, consistent spacing, subtle
shadows. Use lucide-react icons for status indicators and action menus.

Run: npm run dev and verify all interactions work.
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] /library route renders with grid of references
- [ ] "Add Pro Reference" opens modal, upload flow works end to end
- [ ] Cards show correct status (ready/processing/failed)
- [ ] Filters work (stroke type, status)
- [ ] Delete works with confirmation for non-builtin
- [ ] Reprocess triggers re-processing
- [ ] Auto-refresh updates cards as processing completes
- [ ] Responsive grid layout on mobile/tablet/desktop
- [ ] Empty state and loading skeletons render correctly

---

### Task 3.4 — Update Upload page to use Pro Library picker

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Tasks 3.1-3.3 must be completed first.

Update the Upload page to let users pick which pro reference(s) to
compare against from their library instead of a hardcoded dropdown.

1. Update src/pages/Upload.jsx:

   Replace the current pro reference dropdown with a ProReferencePicker
   component. The picker shows all references with status="ready" for
   the selected stroke type.

   Flow change:
   - User selects stroke type first (existing behavior)
   - Pro reference picker auto-filters to show only references matching
     that stroke type
   - User selects one (for now — multi-select in a future iteration)
   - If no references match the stroke type, show a message:
     "No pro references for this stroke. Add one in the Library."
     with a link to /library
   - Rest of the upload flow stays the same

2. Create src/components/ProReferencePicker.jsx:

   A compact, inline selector (not a modal):
   - Horizontal scrollable row of mini-cards (thumbnail + name)
   - Selected card has a green border + checkmark overlay
   - Each card: 120x80 thumbnail, player name below
   - If more than 5 references, scrollable with arrows or native scroll
   - Filter is automatic: only show references matching the current stroke_type
   - Shows "Processing..." cards grayed out (not selectable)
   - "Add New" card at the end: clicking it opens AddProReferenceModal
     (reuse from Task 3.3), and when processing completes the card
     appears in the row

3. Update the API call in Upload page:
   - createAnalysis now sends reference_id (UUID) instead of a string name
   - Backend: update POST /api/upload to accept pro_reference_id (UUID)
     instead of pro_reference (string)
   - Backend: update the process_analysis worker task to load the reference
     by ID from the database instead of by name from the filesystem

4. Update backend/app/routers/upload.py:
   - AnalysisCreate schema: change pro_reference (str) to pro_reference_id (UUID)
   - Validate that the referenced ProReference exists and has status="ready"
   - Store the reference_id on the Analysis record

5. Update backend/app/models.py:
   - Add pro_reference_id: UUID ForeignKey to ProReference (nullable for
     backward compatibility with old analyses that used string names)
   - Keep the old pro_reference string field (don't break existing data)
   - Add Alembic migration for the new column

6. Update backend/app/worker/tasks.py:
   - process_analysis: load pro reference by ID from DB if pro_reference_id
     is set, fall back to old string-based loading if not
   - Pass the loaded reference's landmarks array into the result for
     the frontend overlay (store in a new field on Analysis: pro_landmarks JSON)

7. Update backend/app/models.py Analysis model:
   - Add pro_landmarks: JSON, nullable (stores the pro's landmark array
     for client-side overlay rendering)
   - Add Alembic migration

Run backend tests: uv run pytest tests/ -v
Run frontend: npm run dev, verify upload flow works with the new picker.
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] ProReferencePicker renders matching references for selected stroke
- [ ] Selecting a reference highlights it with green border
- [ ] Upload sends reference_id UUID to backend
- [ ] Backend validates reference exists and is ready
- [ ] process_analysis loads reference by ID from DB
- [ ] pro_landmarks stored on Analysis for overlay rendering
- [ ] Old analyses with string-based references still load
- [ ] "Add New" card opens modal and refreshes picker on completion
- [ ] All tests pass

---

## Phase 4: Visual Deviation Overlay (Backend)

### Task 4.1 — Phase alignment and frame mapping engine

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Phase 3 (Tasks 3.1-3.4) must be completed first.

Build the phase alignment engine that maps user swing frames to pro
reference frames so both skeletons can be drawn on the same timeline.

The problem: user's swing might be 90 frames (3s at 30fps) while the
pro reference is 60 frames (2s). The phases have different durations.
We need a frame-by-frame mapping so that "frame 45 of the user's swing"
knows which pro reference frame to overlay.

1. Create backend/app/worker/phase_aligner.py:

   def align_phases(
       user_phases: dict[str, tuple[int, int]],   # from feature_engine
       pro_phases: dict[str, tuple[int, int]],     # from pro reference
       user_frame_count: int,
       pro_frame_count: int,
   ) -> PhaseAlignmentResult:

   PhaseAlignmentResult:
       frame_mapping: list[int]
           # Length = user_frame_count
           # frame_mapping[user_frame] = corresponding pro_frame index
           # This maps every user frame to its aligned pro frame

       phase_boundaries: dict[str, PhaseBoundary]
           # Per-phase alignment info

       total_user_frames: int
       total_pro_frames: int

   PhaseBoundary:
       phase_name: str
       user_start: int
       user_end: int
       pro_start: int
       pro_end: int
       user_duration_frames: int
       pro_duration_frames: int
       tempo_ratio: float  # user_duration / pro_duration (>1 = user is slower)

   Algorithm:
   a. For each phase (preparation, backswing, forward_swing, contact, follow_through):
      - Get user frame range: (user_start, user_end)
      - Get pro frame range: (pro_start, pro_end)
      - User phase has N frames, pro phase has M frames
      - Create a linear mapping: for user frame i in [user_start, user_end],
        the corresponding pro frame = pro_start + (i - user_start) / (N-1) * (M-1)
        Use np.interp for this
   b. Concatenate all phase mappings into one frame_mapping array
   c. Handle edge case: if a phase is missing from either swing, skip it
      in the mapping (map those frames to the nearest available phase)
   d. Compute tempo_ratio per phase for the timing feedback

   Also create:

   def resample_landmarks(
       landmarks: np.ndarray,   # (N, 33, 3)
       target_length: int,
   ) -> np.ndarray:
       """Resample a landmark sequence to a target number of frames.
       Uses linear interpolation per landmark per coordinate."""
       # shape: (target_length, 33, 3)

   This is needed to create pro landmark arrays that are the same length
   as the user's swing for frame-by-frame overlay.

2. Create backend/app/worker/deviation_annotator.py:

   def compute_frame_deviations(
       user_landmarks: np.ndarray,       # (N, 33, 3)
       pro_landmarks_aligned: np.ndarray, # (N, 33, 3) — already resampled
       phases: dict[str, tuple[int, int]],
       deviations: list[Deviation],       # from DTW comparator
   ) -> list[FrameDeviation]:

   FrameDeviation:
       frame_index: int
       deviating_joints: list[JointDeviation]
       phase: str
       severity: str  # worst severity among deviating joints this frame

   JointDeviation:
       joint_name: str
       landmark_indices: list[int]  # which MediaPipe landmark IDs to highlight
       user_angle: float
       pro_angle: float
       diff_degrees: float
       direction: str  # "too_wide", "too_narrow", "too_early", "too_late"

   Algorithm:
   a. For each frame, check which joints from the deviations list are
      actively deviating (angle diff > threshold, default 10 degrees)
   b. Map joint names to MediaPipe landmark indices:
      - "elbow_angle" -> [13, 14] (left/right elbow)
      - "shoulder_rotation" -> [11, 12]
      - "hip_rotation" -> [23, 24]
      - "knee_bend" -> [25, 26]
      - "racket_arm_elevation" -> [11 or 12, 13 or 14] (hitting side)
      - "trunk_rotation" -> [11, 12, 23, 24]
   c. Only flag joints in frames that fall within the deviation's phase
   d. Compute per-frame angle differences between user and aligned pro

3. Update backend/app/worker/tasks.py (process_analysis):
   After DTW comparison, add new steps:
   - Run phase_aligner to create frame mapping
   - Resample pro landmarks to match user frame count
   - Run deviation_annotator to compute per-frame deviations
   - Store on Analysis record (new JSON fields):
     - aligned_pro_landmarks: the resampled pro landmarks (as nested list)
     - frame_mapping: the frame index mapping array
     - frame_deviations: the per-frame deviation data
     - phase_boundaries: the alignment boundaries with tempo ratios

4. Update backend/app/models.py Analysis model:
   - Add aligned_pro_landmarks: JSON, nullable
   - Add frame_mapping: JSON, nullable
   - Add frame_deviations: JSON, nullable
   - Add phase_boundaries: JSON, nullable
   - Create Alembic migration

5. Update GET /api/analysis/{id} response to include the new fields.

6. Add tests in tests/test_phase_aligner.py:
   - Identical phase lengths: mapping should be 1:1
   - Different phase lengths: verify interpolation
   - Missing phase handling
   - Tempo ratio calculation
   - resample_landmarks shape validation

7. Add tests in tests/test_deviation_annotator.py:
   - Frame with big joint diff -> deviation flagged
   - Frame with small joint diff -> no deviation
   - Phase boundaries respected (no false flags outside phase)
   - Joint name to landmark index mapping

Run: uv run pytest tests/ -v
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] Phase alignment produces correct 1:1 frame mapping
- [ ] Resampled pro landmarks match user frame count
- [ ] Frame deviations identify correct joints in correct phases
- [ ] Tempo ratios computed per phase
- [ ] Analysis record stores all overlay data
- [ ] API returns overlay data in response
- [ ] All tests pass

---

### Task 4.2 — Overlay data API endpoint and optimization

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Task 4.1 must be completed first.

The overlay data (aligned_pro_landmarks, frame_deviations) can be large.
A 90-frame swing with 33 landmarks × 3 coords = ~8000 floats per swing.
Plus frame deviations. We need an optimized endpoint for the frontend.

1. Create GET /api/analysis/{analysis_id}/overlay endpoint in
   app/routers/analysis.py:

   Returns only the data the frontend needs for canvas rendering:
   {
     user_landmarks: number[][][],        // [frame][landmark][xyz]
     pro_landmarks: number[][][],         // [frame][landmark][xyz] — aligned
     frame_mapping: number[],             // user_frame -> pro_frame
     frame_deviations: FrameDeviation[],  // per-frame joint flags
     phase_boundaries: PhaseBoundary[],   // with tempo ratios
     fps: number,                         // for playback speed
     landmark_connections: number[][],     // pairs of landmark indices to draw bones
   }

   LANDMARK_CONNECTIONS constant (defines which landmarks to connect
   with lines to draw a skeleton):
   [
     [11, 12],  // shoulders
     [11, 13],  // left shoulder -> left elbow
     [13, 15],  // left elbow -> left wrist
     [12, 14],  // right shoulder -> right elbow
     [14, 16],  // right elbow -> right wrist
     [11, 23],  // left shoulder -> left hip
     [12, 24],  // right shoulder -> right hip
     [23, 24],  // hips
     [23, 25],  // left hip -> left knee
     [25, 27],  // left knee -> left ankle
     [24, 26],  // right hip -> right knee
     [26, 28],  // right knee -> right ankle
   ]

2. Optimization: compress the landmark data before sending.
   - Round all coordinates to 4 decimal places (float32 precision is enough)
   - For the pro landmarks, only send frames that are DIFFERENT from a
     linear interpolation of keyframes (delta encoding). Actually, for MVP
     just round and send the full arrays — premature optimization not needed.
   - Set appropriate Cache-Control headers (this data won't change after
     analysis is complete)

3. Also store the user's original landmarks on the Analysis record.
   Currently pose_data is set but may be incomplete. Ensure it stores
   the full (N, 33, 3) array as a nested list in the JSON field.
   Update process_analysis in tasks.py if needed.

4. Add a GET /api/pro-references/{reference_id}/preview endpoint:
   Returns a subset of the pro reference data for preview purposes:
   {
     landmarks: number[][][],       // full landmark array
     phases: dict,                  // phase boundaries
     fps: number,
     frame_count: number,
     landmark_connections: number[][],
   }
   This lets the frontend show an animated skeleton preview of a pro
   reference in the library (stretch goal, but the endpoint should exist).

5. Add tests:
   - Overlay endpoint returns correct shape
   - Pro preview endpoint returns correct shape
   - 404 when analysis not complete
   - Landmark connections are valid indices (all < 33)

Run: uv run pytest tests/ -v
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] /api/analysis/{id}/overlay returns complete overlay dataset
- [ ] Coordinates rounded to 4 decimal places
- [ ] Landmark connections define valid skeleton bones
- [ ] /api/pro-references/{id}/preview returns previewable data
- [ ] Endpoints return 404 for incomplete/missing records
- [ ] All tests pass

---

### Task 4.3 — Annotated frame extraction for video overlay

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Tasks 4.1 and 4.2 must be completed first.

Currently the pipeline deletes extracted frames after pose estimation
to save disk space. For the video overlay feature, we need to keep
the user's original frames (or the original video) accessible so the
frontend can show the video with skeleton overlays.

Update the pipeline to preserve video access:

1. Update backend/app/worker/tasks.py (process_analysis):

   After processing, instead of deleting the temp directory entirely:
   - Keep the original video file accessible (it's already in S3)
   - Extract and save a set of "keyframes" for thumbnail/preview:
     One frame per phase transition (5 frames total), saved as JPEGs
     to S3 at "analyses/{analysis_id}/keyframes/phase_{name}.jpg"
   - Store keyframe S3 keys on the Analysis record

2. Add to Analysis model:
   - keyframe_urls: JSON, nullable (dict of phase_name -> S3 key)
   - video_url: String, nullable (presigned download URL, generated on read)
   - Add Alembic migration

3. Update GET /api/analysis/{id} to include:
   - video_url: a fresh presigned S3 download URL for the original video
     (generate at request time, expires in 1 hour)
   - keyframe_urls: dict of phase_name -> presigned download URL

4. Update GET /api/analysis/{id}/overlay to include:
   - video_url: same presigned URL
   - keyframe_urls: same
   (The frontend needs the video URL to render the canvas overlay on top)

5. Add a utility in app/services/s3.py:
   - generate_presigned_urls(keys: list[str]) -> list[str]
     Batch presigned URL generation for multiple keys

6. For local dev (no S3): serve frames from a local directory.
   Update the local fallback in s3.py to handle the keyframe paths.
   Add a static file mount in main.py for /uploads/ directory in dev mode.

7. Tests:
   - Keyframes are extracted at correct phase boundaries
   - Presigned URLs are generated correctly
   - Overlay endpoint includes video_url and keyframe_urls

Run: uv run pytest tests/ -v
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] Keyframes extracted at phase transition points
- [ ] Keyframes uploaded to S3
- [ ] Analysis response includes video_url and keyframe_urls
- [ ] Overlay endpoint includes video and keyframe URLs
- [ ] Local dev fallback works without S3
- [ ] All tests pass

---

## Phase 5: Frontend Comparison UI

### Task 5.1 — Dual skeleton canvas renderer

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Phase 4 (Tasks 4.1-4.3) must be completed first.

Build the core canvas rendering component that draws two skeletons
(user + pro) on top of video frames, with deviation highlighting.
This is the most visually complex component in the app.

1. Create src/components/DualSkeletonCanvas.jsx:

   Props:
   - videoSrc: string (URL to user's video)
   - userLandmarks: number[][][] (per-frame landmarks)
   - proLandmarks: number[][][] (aligned pro landmarks, same frame count)
   - frameDeviations: FrameDeviation[] (per-frame deviation data)
   - landmarkConnections: number[][] (bone pairs)
   - phaseBoundaries: PhaseBoundary[] (phase start/end frames)
   - fps: number
   - currentFrame: number (controlled externally)
   - showUserSkeleton: boolean (default true)
   - showProSkeleton: boolean (default true)
   - showDeviations: boolean (default true)
   - width: number
   - height: number

   Rendering logic:
   a. Draw the video frame on a <canvas> element
   b. On top, draw the USER skeleton:
      - Iterate landmarkConnections, draw lines between each pair
      - Color: cyan (#00D4FF) with 70% opacity
      - Line width: 2px
      - Draw circles at each landmark point: 4px radius
   c. On top, draw the PRO skeleton:
      - Same bone connections
      - Color: gold (#FFD700) with 70% opacity
      - Line width: 2px, dashed pattern [6, 3]
      - Draw circles at each landmark point: 4px radius
   d. Deviation highlighting:
      - For the current frame, check frameDeviations
      - For each deviating joint:
        - Draw a red glow/circle around the landmark (larger, pulsing)
        - Draw a red arc showing the angle difference
        - Draw a small label: "{diff}°" near the joint
      - Severity coloring:
        - critical: #EF4444 (red), thick lines
        - moderate: #F59E0B (amber), medium lines
        - minor: #3B82F6 (blue), thin lines
   e. Phase indicator: draw a small label in the top-left showing
      current phase name (e.g., "Backswing")

   Performance:
   - Use requestAnimationFrame for smooth rendering
   - Only redraw when currentFrame changes
   - Pre-compute transformed coordinates (landmarks are normalized 0-1,
     need to scale to canvas dimensions)

2. Create src/components/SkeletonLegend.jsx:
   A small legend bar showing:
   - Cyan line = "Your swing"
   - Gold dashed line = "Pro reference"
   - Red highlight = "Deviation area"

3. Coordinate transformation utility (src/lib/landmarks.js):

   function transformLandmarks(landmarks, canvasWidth, canvasHeight):
     """Convert normalized [0,1] landmark coordinates to canvas pixels."""
     - x_pixel = landmark[0] * canvasWidth
     - y_pixel = landmark[1] * canvasHeight
     - Return transformed array

   function getDeviationsForFrame(frameDeviations, frameIndex):
     """Get deviation data for a specific frame."""

4. Test the component manually:
   - Create a test page at /dev/overlay-test (only in dev mode)
   - Generate synthetic landmark data (two slightly different sine waves)
   - Render DualSkeletonCanvas with the synthetic data
   - Verify both skeletons render, deviations highlight correctly

Styling: canvas should have a dark background. Skeletons should be
clearly visible. The glow effect on deviations should be eye-catching
but not overwhelming. Use canvas shadow blur for the glow.

Run: npm run dev and test at /dev/overlay-test
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] Canvas renders video frame as background
- [ ] User skeleton drawn in cyan with correct bone connections
- [ ] Pro skeleton drawn in gold dashed lines
- [ ] Deviation joints highlighted with colored glow
- [ ] Angle difference labels shown near deviating joints
- [ ] Phase name shown in top-left
- [ ] Legend component renders correctly
- [ ] Coordinate transformation scales landmarks to canvas
- [ ] Smooth rendering with requestAnimationFrame
- [ ] Dev test page works with synthetic data

---

### Task 5.2 — Video scrubber and phase timeline

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Task 5.1 must be completed first.

Build the video playback controls and phase timeline that drive the
DualSkeletonCanvas. The user needs to play, pause, scrub frame-by-frame,
and jump to specific phases.

1. Create src/components/VideoScrubber.jsx:

   Props:
   - totalFrames: number
   - currentFrame: number
   - onFrameChange: (frame: number) => void
   - fps: number
   - isPlaying: boolean
   - onPlayPause: () => void
   - phaseBoundaries: PhaseBoundary[]

   UI elements:
   a. Play/Pause button (large, centered)
   b. Frame-by-frame step buttons: << (back 1 frame) and >> (forward 1 frame)
   c. Speed control: 0.25x, 0.5x, 1x buttons (tennis swings need slow-mo)
   d. Scrubber bar:
      - Full-width horizontal slider
      - Shows current position as a draggable handle
      - Background colored by phase:
        preparation = gray
        backswing = blue
        forward_swing = green
        contact = yellow
        follow_through = purple
      - Phase labels above the bar at their boundaries
      - Current time display: "Frame 45/90 (1.5s)"
   e. Phase quick-jump buttons:
      - Row of buttons for each phase name
      - Clicking jumps to the start frame of that phase
      - Active phase button is highlighted

2. Create src/hooks/useVideoPlayback.js:

   Custom hook managing playback state:
   - currentFrame: number (0-indexed)
   - isPlaying: boolean
   - playbackSpeed: number (0.25, 0.5, 1.0)
   - play(): start advancing frames at fps * playbackSpeed
   - pause(): stop advancing
   - seekToFrame(frame: number): jump to frame
   - seekToPhase(phaseName: string): jump to phase start
   - stepForward(): advance 1 frame
   - stepBackward(): go back 1 frame
   - Use requestAnimationFrame for smooth playback
   - Loop back to frame 0 when reaching the end

   The hook also manages a hidden <video> element:
   - Load the video src
   - When currentFrame changes, seek the video to the correct time:
     video.currentTime = currentFrame / fps
   - Draw the video frame to the canvas via a callback

3. Create src/components/PhaseTimeline.jsx:

   A visual timeline showing all 5 phases with:
   - Colored segments proportional to phase duration
   - Phase names inside or above each segment
   - Tempo comparison: show if user is faster/slower than pro per phase
     e.g., "Backswing: 1.2x slower than Federer"
   - Current position indicator (vertical line that moves with playback)
   - Clickable: clicking a phase segment jumps to that phase

4. Wire everything together in a test page:
   - Update the /dev/overlay-test page from Task 5.1
   - Add VideoScrubber and PhaseTimeline below the canvas
   - Verify: play/pause works, scrubbing updates canvas, phase jumps work,
     speed control works

Styling:
- Scrubber bar should be a custom-styled range input (not default browser)
- Phase colors should match the PhaseBreakdown component from Task 2.3
- Controls should feel responsive and immediate
- Dark theme, minimal chrome

Run: npm run dev and test at /dev/overlay-test
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] Play/pause advances frames at correct speed
- [ ] Frame step buttons advance/retreat by 1
- [ ] Speed control switches between 0.25x, 0.5x, 1x
- [ ] Scrubber bar is draggable and updates canvas
- [ ] Phase colors render on scrubber background
- [ ] Phase quick-jump buttons work
- [ ] PhaseTimeline shows phase durations and tempo comparison
- [ ] Video frame syncs to currentFrame
- [ ] Smooth playback with requestAnimationFrame

---

### Task 5.3 — Comparison view (side-by-side + overlay modes)

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Tasks 5.1 and 5.2 must be completed first.

Build the full comparison view that brings together the video overlay
and all controls. This replaces the current Analysis page with a
richer experience.

1. Create src/components/ComparisonView.jsx:

   This is the main comparison container. It has two display modes:

   A. OVERLAY MODE (default):
      - Single canvas showing user's video with both skeletons overlaid
      - DualSkeletonCanvas takes full width
      - Toggle buttons above: "Show My Skeleton" / "Show Pro Skeleton" /
        "Show Deviations" (all on by default)
      - VideoScrubber below the canvas
      - PhaseTimeline below the scrubber

   B. SIDE-BY-SIDE MODE:
      - Two canvases next to each other (50/50 width)
      - Left: user's video with user skeleton only
      - Right: pro reference video (if available) or blank canvas with
        pro skeleton animated (using pro landmarks and phase timing)
      - Both canvases synced: same current phase progress
        (not same frame number — same phase progress percentage)
      - Shared scrubber and timeline below both canvases

   Mode toggle: tabs or segmented control at the top
   "Overlay" | "Side by Side"

2. Create src/components/DeviationTimeline.jsx:

   A horizontal timeline below the phase timeline showing WHERE
   deviations occur across the swing:
   - Full width, thin bar
   - Colored markers at frame positions where deviations exist:
     - Red dots for critical
     - Amber dots for moderate
     - Blue dots for minor
   - Hovering a dot shows a tooltip: "Elbow angle off by 18° (forward swing)"
   - Clicking a dot jumps to that frame
   - This gives users a quick visual of "where are my problems?"

3. Create src/components/FrameDeviationPanel.jsx:

   A collapsible side panel (right side) showing real-time deviation
   data for the current frame:
   - If current frame has deviations:
     - List each deviating joint with:
       - Joint name + icon
       - Your angle vs pro angle (with small gauge visualization)
       - Direction hint: "Your elbow is 18° too wide"
       - Severity badge
   - If current frame has no deviations:
     - "Looking good! No deviations on this frame."
     - Green checkmark
   - Panel updates live as user scrubs through frames

4. Update src/pages/Analysis.jsx:

   Restructure the completed analysis view:

   TOP SECTION (keep existing):
   - Overall score gauge
   - Phase breakdown bars
   - "Compared against: {pro_name}"

   NEW MIDDLE SECTION:
   - ComparisonView (the full canvas + controls)
   - Takes ~60% of the viewport height
   - FrameDeviationPanel as a toggleable right sidebar

   BOTTOM SECTION (keep existing):
   - Coaching feedback (summary, priority fixes, drills, positives)
   - Deviation cards

   Add a new hook: src/hooks/useOverlayData.js
   - Fetches GET /api/analysis/{id}/overlay
   - Returns: { overlayData, isLoading, error }
   - Only fetches after analysis status is "completed"

5. Handle loading states:
   - While overlay data loads: show existing analysis results (score,
     feedback) with a "Loading comparison view..." skeleton where the
     canvas will be
   - If overlay data fails to load: show analysis without comparison
     view (graceful degradation)

Styling:
- Canvas area should be prominent — this IS the main feature now
- Side panel should slide in/out smoothly
- Overlay/side-by-side toggle should be a clean segmented control
- Deviation timeline should be compact but informative
- Mobile: side-by-side falls back to overlay mode only
  (two canvases don't fit on mobile)

Run: npm run dev
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] Overlay mode shows dual skeletons on user's video
- [ ] Side-by-side mode shows two synced canvases
- [ ] Mode toggle switches between overlay and side-by-side
- [ ] DeviationTimeline shows colored markers across the swing
- [ ] Clicking a deviation marker jumps to that frame
- [ ] FrameDeviationPanel shows real-time data for current frame
- [ ] Analysis page integrates comparison view with existing results
- [ ] useOverlayData hook fetches and caches overlay data
- [ ] Graceful degradation if overlay data unavailable
- [ ] Mobile falls back to overlay mode only

---

### Task 5.4 — Polish, responsive design, and keyboard shortcuts

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is part of Feature Spec V2.
Tasks 5.1-5.3 must be completed first.

Polish the comparison UI for a professional feel and add keyboard shortcuts
for power users (Brian will use this while reviewing his own swings).

1. Keyboard shortcuts (add to ComparisonView):
   - Space: play/pause
   - Left arrow: step back 1 frame
   - Right arrow: step forward 1 frame
   - 1-5: jump to phase 1-5 (preparation through follow_through)
   - S: toggle user skeleton
   - P: toggle pro skeleton
   - D: toggle deviations
   - M: switch between overlay and side-by-side mode
   - [: decrease speed (1x -> 0.5x -> 0.25x)
   - ]: increase speed (0.25x -> 0.5x -> 1x)
   - Show keyboard shortcuts in a small help overlay (press ? to toggle)

2. Create src/components/KeyboardShortcutsHelp.jsx:
   - A small overlay showing all shortcuts
   - Triggered by pressing ? or clicking a "?" icon in the toolbar
   - Semi-transparent dark background, centered card with shortcuts grid

3. Responsive design audit — verify and fix:
   - Desktop (>1024px): full layout with side panel
   - Tablet (768-1024px): collapse side panel to bottom, keep dual canvas
   - Mobile (<768px): overlay mode only, no side panel,
     scrubber simplified, phase buttons scroll horizontally
   - Canvas should resize dynamically (use ResizeObserver)
   - Video aspect ratio preserved (no stretching)

4. Loading and empty states:
   - Skeleton loading for the canvas area while overlay data fetches
   - Error state: "Couldn't load comparison data. Try refreshing."
     with a retry button
   - If analysis has no overlay data (old analysis before V2):
     Show the existing analysis page without comparison view,
     with a note: "Comparison overlay not available for this analysis.
     Re-analyze to see frame-by-frame comparison."

5. Visual polish:
   - Add smooth transitions when toggling skeletons on/off (fade in/out)
   - Add a subtle animation when deviations pulse at high severity
   - Phase boundary lines on the canvas (thin vertical lines at phase
     transitions)
   - Current phase highlight: slight background color change on the
     canvas border matching the current phase color
   - Frame counter in the top-right of the canvas: "F 45/90"

6. Performance check:
   - Profile the canvas rendering in Chrome DevTools
   - Ensure 60fps rendering for overlay mode
   - If performance issues: reduce skeleton line quality,
     skip deviation labels, simplify glow effects
   - Lazy-load the overlay data (don't fetch until user scrolls to
     the comparison section)

7. Update the navigation:
   - Add breadcrumbs on the Analysis page: "Home > History > Analysis #abc123"
   - Update page title: "SwingCoach — Analysis Results"

Run: npm run dev, test on Chrome and Safari at multiple viewport sizes.
Run: npm run build (verify no build errors or warnings).
Update CHANGELOG.md.
```

**Acceptance criteria:**
- [ ] All keyboard shortcuts work correctly
- [ ] Keyboard shortcuts help overlay shows on ? press
- [ ] Responsive layout works on desktop/tablet/mobile
- [ ] Canvas resizes without stretching
- [ ] Loading and error states render correctly
- [ ] Old analyses without overlay data degrade gracefully
- [ ] Skeleton toggle has smooth fade animation
- [ ] Deviation pulse animation on severe deviations
- [ ] 60fps canvas rendering confirmed in Chrome DevTools
- [ ] npm run build succeeds without errors/warnings

---

## Phase 6: Integration and Testing

### Task 6.1 — End-to-end integration test and CLAUDE.md update

**Prompt for Claude Code:**
```
Read CLAUDE.md for project context. This is the FINAL task of Feature Spec V2.
ALL previous tasks (3.1-5.4) must be completed first.

Full integration test and documentation update.

1. End-to-end test (scripts/test_e2e_v2.py):

   NOT a pytest test. Run manually: python scripts/test_e2e_v2.py

   Steps:
   a. Create a ProReference record via API
   b. Process a synthetic video through the pro reference pipeline
   c. Wait for ProReference status = "ready"
   d. Create an Analysis via API with the new pro_reference_id
   e. Process a slightly different synthetic video through the analysis pipeline
   f. Wait for Analysis status = "completed"
   g. Fetch the overlay endpoint, verify:
      - user_landmarks and pro_landmarks have same frame count
      - frame_mapping length matches user frame count
      - frame_deviations has entries
      - phase_boundaries has 5 phases
   h. Print summary:
      - Overall score
      - Number of deviations
      - Per-phase tempo ratios
      - Overlay data sizes
   i. Assert everything is populated correctly

2. Update CLAUDE.md:

   Add to the Project Structure section:
   - New files: phase_aligner.py, deviation_annotator.py, pro_reference_tasks.py
   - New router: pro_references.py
   - New frontend pages: ProLibrary.jsx
   - New frontend components: DualSkeletonCanvas, VideoScrubber,
     PhaseTimeline, ComparisonView, etc.

   Add to Non-Obvious Decisions:
   - "Client-side canvas overlay over server-side video compositing:
     More interactive (scrub, toggle, zoom), less compute, and
     the existing SkeletonOverlay.jsx pattern made this natural."
   - "Phase-aligned resampling over raw frame mapping:
     Each phase is independently resampled so that a user's slower
     backswing doesn't cause misalignment in the forward swing."
   - "ProReference as a first-class DB entity over file-system convention:
     Enables user uploads, status tracking, thumbnails, and future
     sharing features."

   Add to Pipeline Data Flow:
   - Update the diagram to show the new phase alignment and deviation
     annotation stages
   - Show the ProReference upload pipeline (video → frames → pose → features → .npz)

   Add to Do Not:
   - "Do NOT render composite videos server-side. All overlay rendering
     happens client-side on canvas."
   - "Do NOT send pro reference video to the frontend for side-by-side.
     Use animated skeleton rendering from landmarks instead."

   Update Common Commands with new endpoints and test scripts.

3. Update README.md:
   - Add Pro Library section (how to upload pro references)
   - Add Comparison View section (how the overlay works)
   - Update architecture diagram to show the new data flow
   - Update environment variables if any new ones were added

4. Run ALL tests:
   cd backend && uv run pytest tests/ -v
   cd frontend && npm run build
   python scripts/test_e2e_v2.py

5. Update CHANGELOG.md with a summary of all V2 features.

6. Git: commit with message "feat: V2 — Pro Library, Visual Deviation Overlay, Comparison UI"
```

**Acceptance criteria:**
- [ ] E2E V2 test passes end-to-end
- [ ] CLAUDE.md accurately reflects the new architecture
- [ ] README.md updated with new features
- [ ] All backend tests pass
- [ ] Frontend builds without errors
- [ ] CHANGELOG.md documents all V2 changes
- [ ] Clean git commit with all V2 code

---

## Summary: Task Dependency Graph

```
Phase 3: Pro Library
  3.1 DB model ─────► 3.2 API + pipeline ─────► 3.3 Frontend page
                                                       │
                                                       ▼
                                                 3.4 Upload page picker

Phase 4: Deviation Overlay (Backend)
  3.4 ─────► 4.1 Phase alignment engine ─────► 4.2 Overlay API
                                                       │
                                                       ▼
                                                 4.3 Keyframe extraction

Phase 5: Frontend Comparison UI
  4.3 ─────► 5.1 Dual skeleton canvas ─────► 5.2 Video scrubber
                                                       │
                                                       ▼
                                              5.3 Comparison view
                                                       │
                                                       ▼
                                              5.4 Polish + shortcuts

Phase 6: Integration
  5.4 ─────► 6.1 E2E test + docs update
```

Total: 12 tasks, each scoped for a single Claude Code session.
Estimated: 3-4 days of focused execution.

---

## Post-V2 Backlog

After V2 ships, the next priorities are:

- [ ] Multi-pro comparison: compare against 2+ pros simultaneously (overlay up to 3 skeletons)
- [ ] Progress tracking: same stroke analyzed over time, chart improvement
- [ ] Video recording in-app: use device camera with a guide overlay
- [ ] Shareable comparison clips: export a 5-second annotated GIF/MP4
- [ ] Pro reference marketplace: share references between users
- [ ] AI-powered drill demonstrations: generate stick-figure animation showing correct form
- [ ] React Native iOS wrapper with Expo
- [ ] Supabase auth integration
