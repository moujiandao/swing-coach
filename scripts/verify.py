#!/usr/bin/env python3
"""
Automated acceptance criteria checker for SwingCoach MVP.

Usage:
    python scripts/verify.py 1.1    # Check Task 1.1
    python scripts/verify.py 1.4    # Check Task 1.4
    python scripts/verify.py all    # Check all completed tasks

Add this to every Claude Code task prompt:
    "After implementation, run: python scripts/verify.py {task_number}
     Fix any FAIL results before finishing."
"""

import subprocess
import sys
import os
import json
from pathlib import Path

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"
CHECK = f"{GREEN}✓ PASS{RESET}"
CROSS = f"{RED}✗ FAIL{RESET}"
SKIP = f"{YELLOW}○ SKIP{RESET}"


def run(cmd, cwd=None, timeout=30):
    """Run a shell command, return (success, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=cwd, timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)


def check(description, passed, detail=""):
    """Print a check result and return pass/fail."""
    status = CHECK if passed else CROSS
    print(f"  {status}  {description}")
    if not passed and detail:
        print(f"         {RED}{detail}{RESET}")
    return passed


def file_exists(path):
    return Path(path).exists()


def file_contains(path, text):
    if not Path(path).exists():
        return False
    return text in Path(path).read_text()


# ──────────────────────────────────────────────────────────
# Task verification functions
# ──────────────────────────────────────────────────────────

def verify_1_1():
    """Task 1.1 — Project scaffolding and dependencies"""
    print("\n📋 Task 1.1 — Project scaffolding and dependencies\n")
    results = []

    # Structure checks
    for path in [
        "backend/pyproject.toml",
        "backend/app/main.py",
        "backend/app/config.py",
        "backend/app/routers/health.py",
        "backend/app/routers/upload.py",
        "backend/app/routers/analysis.py",
        "backend/app/worker/tasks.py",
        "backend/app/worker/frame_extractor.py",
        "backend/app/worker/pose_estimator.py",
        "backend/app/worker/feature_engine.py",
        "backend/app/worker/dtw_comparator.py",
        "backend/app/worker/feedback_generator.py",
        "backend/.env.example",
        "backend/.gitignore",
    ]:
        results.append(check(f"File exists: {path}", file_exists(path)))

    # Server starts — launch uvicorn as a managed subprocess, poll health, then terminate
    import urllib.request
    import time as _time
    _server_ok = False
    _server_detail = ""
    try:
        _proc = subprocess.Popen(
            ["uv", "run", "uvicorn", "app.main:app", "--port", "18112"],
            cwd="backend",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(12):  # up to 6 seconds
            _time.sleep(0.5)
            try:
                with urllib.request.urlopen(
                    "http://localhost:18112/api/health", timeout=1
                ) as _r:
                    _body = _r.read().decode()
                    if "ok" in _body.lower():
                        _server_ok = True
                        break
            except Exception:
                pass
        if not _server_ok:
            _server_detail = "health endpoint did not respond within 6s"
    except Exception as _e:
        _server_detail = str(_e)
    finally:
        try:
            _proc.terminate()
            _proc.wait(timeout=3)
        except Exception:
            pass
    results.append(check(
        "uvicorn starts and /api/health returns 200",
        _server_ok,
        detail=_server_detail
    ))

    # Dependencies installable
    ok, out, err = run("cd backend && uv sync --quiet", timeout=120)
    results.append(check("uv sync succeeds", ok, detail=err))

    # Config has all required vars
    if file_exists("backend/.env.example"):
        env_text = Path("backend/.env.example").read_text()
        for var in ["SUPABASE_URL", "S3_BUCKET", "REDIS_URL",
                     "ANTHROPIC_API_KEY", "ALLOWED_ORIGINS"]:
            results.append(check(
                f".env.example contains {var}",
                var in env_text
            ))

    return results


def verify_1_2():
    """Task 1.2 — Database models and Supabase connection"""
    print("\n📋 Task 1.2 — Database models and Supabase connection\n")
    results = []

    results.append(check(
        "models.py exists",
        file_exists("backend/app/models.py")
    ))
    results.append(check(
        "db.py exists",
        file_exists("backend/app/services/db.py")
    ))

    if file_exists("backend/app/models.py"):
        text = Path("backend/app/models.py").read_text()
        for field in ["status", "stroke_type", "video_s3_key",
                       "pose_data", "phase_scores", "coaching_feedback",
                       "overall_score", "error_message"]:
            results.append(check(
                f"Analysis model has '{field}' field",
                field in text
            ))

        results.append(check(
            "StrokeType enum defined",
            "forehand" in text.lower() and "serve" in text.lower()
        ))

    return results


def verify_1_3():
    """Task 1.3 — S3 service and video upload endpoint"""
    print("\n📋 Task 1.3 — S3 service and video upload endpoint\n")
    results = []

    results.append(check(
        "s3.py exists",
        file_exists("backend/app/services/s3.py")
    ))
    results.append(check(
        "upload.py router exists",
        file_exists("backend/app/routers/upload.py")
    ))
    results.append(check(
        "analysis.py router exists",
        file_exists("backend/app/routers/analysis.py")
    ))

    if file_exists("backend/app/routers/upload.py"):
        text = Path("backend/app/routers/upload.py").read_text()
        results.append(check(
            "POST /api/upload endpoint defined",
            "/upload" in text and ("post" in text.lower() or "POST" in text)
        ))
        results.append(check(
            "Confirm endpoint defined",
            "confirm" in text
        ))

    return results


def verify_1_4():
    """Task 1.4 — Frame extraction with FFmpeg"""
    print("\n📋 Task 1.4 — Frame extraction with FFmpeg\n")
    results = []

    results.append(check(
        "frame_extractor.py exists",
        file_exists("backend/app/worker/frame_extractor.py")
    ))
    results.append(check(
        "test_frame_extractor.py exists",
        file_exists("backend/tests/test_frame_extractor.py")
    ))

    # Check ffmpeg is available
    ok, out, err = run("ffmpeg -version")
    results.append(check("ffmpeg is installed", ok, detail=err))

    # Run the specific test
    ok, out, err = run(
        "cd backend && uv run python -m pytest tests/test_frame_extractor.py -v --tb=short",
        timeout=60
    )
    results.append(check("Frame extractor tests pass", ok, detail=out or err))

    return results


def verify_1_5():
    """Task 1.5 — MediaPipe pose estimation"""
    print("\n📋 Task 1.5 — MediaPipe pose estimation\n")
    results = []

    results.append(check(
        "pose_estimator.py exists",
        file_exists("backend/app/worker/pose_estimator.py")
    ))
    results.append(check(
        "test_pose_estimator.py exists",
        file_exists("backend/tests/test_pose_estimator.py")
    ))

    if file_exists("backend/app/worker/pose_estimator.py"):
        text = Path("backend/app/worker/pose_estimator.py").read_text()
        results.append(check(
            "LANDMARK_NAMES mapping defined",
            "LANDMARK_NAMES" in text or "landmark_names" in text
        ))
        results.append(check(
            "Uses mediapipe",
            "mediapipe" in text
        ))

    ok, out, err = run(
        "cd backend && uv run python -m pytest tests/test_pose_estimator.py -v --tb=short",
        timeout=120
    )
    results.append(check("Pose estimator tests pass", ok, detail=out or err))

    return results


def verify_1_6():
    """Task 1.6 — Feature extraction and phase segmentation"""
    print("\n📋 Task 1.6 — Feature extraction and phase segmentation\n")
    results = []

    results.append(check(
        "feature_engine.py exists",
        file_exists("backend/app/worker/feature_engine.py")
    ))
    results.append(check(
        "test_feature_engine.py exists",
        file_exists("backend/tests/test_feature_engine.py")
    ))

    if file_exists("backend/app/worker/feature_engine.py"):
        text = Path("backend/app/worker/feature_engine.py").read_text()
        for fn in ["compute_angle", "compute_velocity", "detect_phases"]:
            results.append(check(f"Function {fn}() defined", fn in text))
        results.append(check(
            "Uses savgol_filter for smoothing",
            "savgol_filter" in text
        ))

    ok, out, err = run(
        "cd backend && uv run python -m pytest tests/test_feature_engine.py -v --tb=short",
        timeout=60
    )
    results.append(check("Feature engine tests pass", ok, detail=out or err))

    return results


def verify_1_7():
    """Task 1.7 — DTW comparator and pro reference loader"""
    print("\n📋 Task 1.7 — DTW comparator and pro reference loader\n")
    results = []

    results.append(check(
        "dtw_comparator.py exists",
        file_exists("backend/app/worker/dtw_comparator.py")
    ))
    results.append(check(
        "loader.py exists",
        file_exists("backend/app/pro_references/loader.py")
    ))
    results.append(check(
        "generate_synthetic_reference.py exists",
        file_exists("scripts/generate_synthetic_reference.py")
    ))
    results.append(check(
        "test_dtw_comparator.py exists",
        file_exists("backend/tests/test_dtw_comparator.py")
    ))

    # Check if synthetic reference was generated
    data_dir = Path("backend/app/pro_references/data")
    has_npz = any(data_dir.glob("*.npz")) if data_dir.exists() else False
    results.append(check(
        "At least one .npz reference file exists",
        has_npz,
        detail="Run: python scripts/generate_synthetic_reference.py"
    ))

    ok, out, err = run(
        "cd backend && uv run python -m pytest tests/test_dtw_comparator.py -v --tb=short",
        timeout=60
    )
    results.append(check("DTW comparator tests pass", ok, detail=out or err))

    return results


def verify_1_8():
    """Task 1.8 — Claude feedback generator"""
    print("\n📋 Task 1.8 — Claude feedback generator\n")
    results = []

    results.append(check(
        "feedback_generator.py exists",
        file_exists("backend/app/worker/feedback_generator.py")
    ))

    if file_exists("backend/app/worker/feedback_generator.py"):
        text = Path("backend/app/worker/feedback_generator.py").read_text()
        results.append(check("Uses anthropic SDK", "anthropic" in text))
        results.append(check(
            "Uses claude-sonnet-4-20250514 model",
            "sonnet" in text.lower()
        ))
        results.append(check(
            "Has retry logic for JSON parsing",
            "retry" in text.lower() or "attempt" in text.lower()
        ))

    # Test only if API key is set
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        ok, out, err = run(
            "cd backend && uv run python -m pytest tests/test_feedback_generator.py -v --tb=short",
            timeout=60
        )
        results.append(check("Feedback generator tests pass", ok, detail=out or err))
    else:
        print(f"  {SKIP}  Feedback generator tests (no ANTHROPIC_API_KEY set)")

    return results


def verify_1_9():
    """Task 1.9 — Worker task orchestration"""
    print("\n📋 Task 1.9 — Worker task orchestration\n")
    results = []

    results.append(check(
        "tasks.py has process_analysis function",
        file_exists("backend/app/worker/tasks.py") and
        "process_analysis" in Path("backend/app/worker/tasks.py").read_text()
    ))
    results.append(check(
        "run_worker.py exists",
        file_exists("backend/run_worker.py")
    ))
    results.append(check(
        "e2e test script exists",
        file_exists("scripts/test_e2e.py")
    ))

    if file_exists("backend/app/worker/tasks.py"):
        text = Path("backend/app/worker/tasks.py").read_text()
        results.append(check(
            "Uses tempfile for working directory",
            "tempfile" in text or "mkdtemp" in text
        ))
        results.append(check(
            "Has try/finally cleanup",
            "finally" in text
        ))
        results.append(check(
            "Updates status on failure",
            "failed" in text.lower()
        ))
        results.append(check(
            "Tracks processing_time_ms",
            "processing_time" in text or "perf_counter" in text
        ))

    return results


def verify_2_1():
    """Task 2.1 — Frontend scaffolding"""
    print("\n📋 Task 2.1 — Frontend scaffolding\n")
    results = []

    for path in [
        "frontend/package.json",
        "frontend/vite.config.js",
        "frontend/src/App.jsx",
        "frontend/src/lib/api.js",
        "frontend/src/pages/Upload.jsx",
        "frontend/src/pages/Analysis.jsx",
        "frontend/src/pages/History.jsx",
    ]:
        # Also check .ts/.tsx variants
        tsx = path.replace(".jsx", ".tsx").replace(".js", ".ts")
        results.append(check(
            f"File exists: {path}",
            file_exists(path) or file_exists(tsx)
        ))

    # npm install works
    ok, out, err = run("cd frontend && npm install --silent", timeout=120)
    results.append(check("npm install succeeds", ok, detail=err))

    # Build works
    ok, out, err = run("cd frontend && npm run build", timeout=60)
    results.append(check("npm run build succeeds", ok, detail=err))

    return results


def verify_2_2():
    """Task 2.2 — Video upload page"""
    print("\n📋 Task 2.2 — Video upload page\n")
    results = []

    upload_path = "frontend/src/pages/Upload.jsx"
    upload_tsx = "frontend/src/pages/Upload.tsx"
    uploader_path = "frontend/src/components/VideoUploader.jsx"
    uploader_tsx = "frontend/src/components/VideoUploader.tsx"

    results.append(check(
        "Upload page exists",
        file_exists(upload_path) or file_exists(upload_tsx)
    ))
    results.append(check(
        "VideoUploader component exists",
        file_exists(uploader_path) or file_exists(uploader_tsx)
    ))

    # Check the upload page for key features
    for p in [upload_path, upload_tsx]:
        if file_exists(p):
            text = Path(p).read_text()
            results.append(check(
                "References stroke type selection",
                "stroke" in text.lower() or "forehand" in text.lower()
            ))
            results.append(check(
                "Has upload/submit handler",
                "upload" in text.lower() or "submit" in text.lower() or "handleSubmit" in text
            ))

    ok, out, err = run("cd frontend && npm run build", timeout=60)
    results.append(check("Frontend builds without errors", ok, detail=err))

    return results


def verify_2_3():
    """Task 2.3 — Analysis results page"""
    print("\n📋 Task 2.3 — Analysis results page\n")
    results = []

    for component in [
        "ScoreGauge", "PhaseBreakdown", "DeviationCard",
        "CoachingFeedback", "ProcessingState"
    ]:
        jsx = f"frontend/src/components/{component}.jsx"
        tsx = f"frontend/src/components/{component}.tsx"
        results.append(check(
            f"{component} component exists",
            file_exists(jsx) or file_exists(tsx)
        ))

    hook_js = "frontend/src/hooks/useAnalysis.js"
    hook_ts = "frontend/src/hooks/useAnalysis.ts"
    results.append(check(
        "useAnalysis hook exists",
        file_exists(hook_js) or file_exists(hook_ts)
    ))

    ok, out, err = run("cd frontend && npm run build", timeout=60)
    results.append(check("Frontend builds without errors", ok, detail=err))

    return results


def verify_2_4():
    """Task 2.4 — History page and navigation polish"""
    print("\n📋 Task 2.4 — History page and navigation polish\n")
    results = []

    ok, out, err = run("cd frontend && npm run build", timeout=60)
    results.append(check("Frontend builds without errors", ok, detail=err))

    # Check for no console.log spam
    ok, out, err = run(
        "cd frontend/src && grep -rn 'console.log' --include='*.jsx' --include='*.tsx' --include='*.js' --include='*.ts' | grep -v node_modules | grep -v '// debug' || true"
    )
    log_count = len(out.strip().split('\n')) if out.strip() else 0
    results.append(check(
        f"No excessive console.log ({log_count} found)",
        log_count <= 3,
        detail=out if log_count > 3 else ""
    ))

    return results


def verify_2_5():
    """Task 2.5 — Full integration test and deployment prep"""
    print("\n📋 Task 2.5 — Full integration and deployment prep\n")
    results = []

    for path in [
        "docker-compose.yml",
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "README.md",
        "scripts/dev_setup.sh",
    ]:
        results.append(check(f"File exists: {path}", file_exists(path)))

    # All backend tests pass
    ok, out, err = run(
        "cd backend && uv run python -m pytest tests/ -v --tb=short -x",
        timeout=120
    )
    results.append(check("All backend tests pass", ok, detail=out or err))

    # Frontend builds
    ok, out, err = run("cd frontend && npm run build", timeout=60)
    results.append(check("Frontend production build succeeds", ok, detail=err))

    # No hardcoded secrets
    ok, out, err = run(
        "grep -rn 'sk-ant-api[0-9]\\|AKIA[A-Z0-9]' backend/ frontend/ "
        "--include='*.py' --include='*.js' --include='*.jsx' --include='*.ts' --include='*.tsx' "
        "| grep -v node_modules | grep -v '.env' || true"
    )
    results.append(check(
        "No hardcoded secrets in source",
        not out.strip(),
        detail=out if out.strip() else ""
    ))

    # No print() in backend (should use logging)
    ok, out, err = run(
        "grep -rn '^[^#]*print(' backend/app/ --include='*.py' | grep -v '__pycache__' || true"
    )
    print_count = len(out.strip().split('\n')) if out.strip() else 0
    results.append(check(
        f"No print() in backend app code ({print_count} found)",
        print_count == 0,
        detail=out if print_count > 0 else ""
    ))

    return results


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

TASKS = {
    "1.1": verify_1_1,
    "1.2": verify_1_2,
    "1.3": verify_1_3,
    "1.4": verify_1_4,
    "1.5": verify_1_5,
    "1.6": verify_1_6,
    "1.7": verify_1_7,
    "1.8": verify_1_8,
    "1.9": verify_1_9,
    "2.1": verify_2_1,
    "2.2": verify_2_2,
    "2.3": verify_2_3,
    "2.4": verify_2_4,
    "2.5": verify_2_5,
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify.py <task_number|all>")
        print(f"Available tasks: {', '.join(TASKS.keys())}")
        sys.exit(1)

    target = sys.argv[1]

    if target == "all":
        tasks_to_run = list(TASKS.items())
    elif target in TASKS:
        tasks_to_run = [(target, TASKS[target])]
    else:
        print(f"Unknown task: {target}")
        print(f"Available: {', '.join(TASKS.keys())}")
        sys.exit(1)

    total_pass = 0
    total_fail = 0

    for task_id, verify_fn in tasks_to_run:
        results = verify_fn()
        passed = sum(1 for r in results if r)
        failed = sum(1 for r in results if not r)
        total_pass += passed
        total_fail += failed
        print(f"\n  Results: {GREEN}{passed} passed{RESET}, {RED}{failed} failed{RESET}")

    print(f"\n{'='*50}")
    print(f"  TOTAL: {GREEN}{total_pass} passed{RESET}, {RED}{total_fail} failed{RESET}")

    if total_fail > 0:
        print(f"\n  {RED}Some checks failed. Fix before moving to the next task.{RESET}")
        sys.exit(1)
    else:
        print(f"\n  {GREEN}All checks passed! Ready for the next task.{RESET}")


if __name__ == "__main__":
    main()
