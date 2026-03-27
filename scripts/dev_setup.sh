#!/usr/bin/env bash
# dev_setup.sh — Bootstrap SwingCoach for local development
# Run from the project root: bash scripts/dev_setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo "SwingCoach dev setup"
echo "===================="

# ── 1. Check required tools ──────────────────────────────────────────────────
echo ""
echo "Checking required tools..."

command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install Python 3.11+."
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "python3 $PY_VERSION"

command -v uv >/dev/null 2>&1 || fail "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
ok "uv $(uv --version 2>&1 | head -1)"

command -v node >/dev/null 2>&1 || fail "node not found. Install Node 20+: https://nodejs.org"
ok "node $(node --version)"

command -v npm >/dev/null 2>&1 || fail "npm not found (comes with Node)."
ok "npm $(npm --version)"

command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg not found. Install: brew install ffmpeg (Mac) or apt-get install ffmpeg (Linux)"
ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"

if command -v redis-cli >/dev/null 2>&1; then
    ok "redis-cli found"
    if redis-cli ping >/dev/null 2>&1; then
        ok "Redis is running"
    else
        warn "Redis is installed but not running. Start it with: redis-server"
    fi
else
    warn "redis-cli not found. For local dev without Docker, install: brew install redis"
fi

# ── 2. Backend deps ─────────────────────────────────────────────────────────
echo ""
echo "Installing backend dependencies..."
cd "$ROOT/backend"
uv sync
ok "Backend dependencies installed"
cd "$ROOT"

# ── 3. Frontend deps ─────────────────────────────────────────────────────────
echo ""
echo "Installing frontend dependencies..."
cd "$ROOT/frontend"
npm install
ok "Frontend dependencies installed"
cd "$ROOT"

# ── 4. Create .env from .env.example ─────────────────────────────────────────
echo ""
if [ ! -f "$ROOT/backend/.env" ]; then
    if [ -f "$ROOT/backend/.env.example" ]; then
        cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
        ok "Created backend/.env from .env.example — fill in your secrets"
    else
        warn "backend/.env.example not found, skipping .env creation"
    fi
else
    ok "backend/.env already exists"
fi

# ── 5. Generate synthetic pro reference ────────────────────────────────────
echo ""
echo "Generating synthetic pro reference..."
cd "$ROOT/backend"
if uv run python ../scripts/generate_synthetic_reference.py 2>&1; then
    ok "Synthetic pro reference generated"
else
    warn "Could not generate synthetic reference (this may be OK if mediapipe isn't installed yet)"
fi
cd "$ROOT"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=================================="
echo -e "${GREEN}Ready!${NC}"
echo ""
echo "Start all services with Docker:"
echo "  docker-compose up"
echo ""
echo "Or start manually (3 terminals):"
echo "  Terminal 1: redis-server"
echo "  Terminal 2: cd backend && uv run uvicorn app.main:app --reload"
echo "  Terminal 3: cd backend && uv run python run_worker.py"
echo "  Terminal 4: cd frontend && npm run dev"
echo ""
echo "Frontend: http://localhost:5173"
echo "API:      http://localhost:8000/api/health"
