# Changelog

## [2026-03-26]

### Added (Task 1.5)
- Add MediaPipe pose estimation pipeline stage (`app/worker/pose_estimator.py`) using Tasks API (0.10+) with auto-download of heavy model, linear interpolation for missing frames, and `LANDMARK_NAMES` constant for all 33 BlazePose landmarks
- Add `blank_frame_paths` fixture to `tests/conftest.py`
- Add pose estimator tests (`tests/test_pose_estimator.py`): 14 tests covering output shape, detection rate, interpolation logic, and edge cases — fully mocked so CI requires no model download

---

### Added
- Add FFmpeg frame extraction pipeline stage (`app/worker/frame_extractor.py`) with ffprobe metadata, duration validation, and slow-mo auto-downsampling
- Add pytest fixtures for synthetic test videos (`tests/conftest.py`)
- Add frame extractor tests covering extraction, metadata, FPS downsampling, duration guard, and error handling (`tests/test_frame_extractor.py`)
