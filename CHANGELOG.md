# Changelog

## [2026-03-26]

### Added
- Add FFmpeg frame extraction pipeline stage (`app/worker/frame_extractor.py`) with ffprobe metadata, duration validation, and slow-mo auto-downsampling
- Add pytest fixtures for synthetic test videos (`tests/conftest.py`)
- Add frame extractor tests covering extraction, metadata, FPS downsampling, duration guard, and error handling (`tests/test_frame_extractor.py`)
