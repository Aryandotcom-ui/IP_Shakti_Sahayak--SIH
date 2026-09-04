#!/usr/bin/env bash
#
# Start IP-SAKTI Sahayak locally: build the search index if it is missing,
# then serve the API and the web UI.
#
#   ./scripts/run.sh              backend + frontend, open the printed URL
#   ./scripts/run.sh --backend    API only, no web UI
#   ./scripts/run.sh --rebuild    discard and rebuild the index first
#
# You must open the printed http://localhost:5173 URL. Opening
# frontend/index.html from the file manager cannot work: the page is built
# by Vite at request time, and a file:// page has no origin to reach the
# API on, so it falls back to sample data.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

BACKEND_ONLY=0
REBUILD=0
for arg in "$@"; do
  case "$arg" in
    --backend) BACKEND_ONLY=1 ;;
    --rebuild) REBUILD=1 ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

PY=${PYTHON:-python3}
say() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$1" >&2; exit 1; }

command -v "$PY" >/dev/null || die "python3 not found. Install Python 3.11 or newer."

# Refuse to start on an occupied port. Without this the health check below
# is answered by whatever is already listening, so a failed start reports
# success and you spend the next hour debugging a server that never ran.
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3<&-; return 0; }; return 1; }
check_port() {
  port_busy "$1" || return 0
  die "port $1 is already in use, and that would silently shadow the server
  this script is trying to start. Stop the other process first:

    lsof -ti :$1 | xargs kill      # macOS / Linux with lsof
    fuser -k $1/tcp                # Linux with psmisc

  Most often it is an earlier run of this script that was not shut down."
}

# --- dependencies ---------------------------------------------------------
if ! "$PY" -c "import fastapi, chromadb, sklearn, fitz" 2>/dev/null; then
  say "Installing Python dependencies (a few minutes the first time)"
  "$PY" -m pip install --quiet -r backend/requirements.txt \
    || die "pip install failed. If your Python is externally managed, make a venv first:
    python3 -m venv .venv && source .venv/bin/activate
  then re-run this script."
fi

# --- search index ---------------------------------------------------------
# Not in git: it is ~1800 chunks derived from data/pdfs and rebuilds in
# about a minute, so it is generated rather than versioned.
if [ "$REBUILD" = 1 ]; then
  say "Rebuilding the index from scratch"
  rm -rf data/chroma data/registry.sqlite3
fi

if [ ! -f data/chroma/tfidf-vectorizer.joblib ]; then
  say "Building the search index from data/pdfs (about a minute)"
  "$PY" -m ai.cli data/pdfs --manifest ai/corpus.yaml --model tfidf \
    || die "index build failed — see the log above"
else
  say "Search index already built (delete data/chroma or pass --rebuild to redo it)"
fi

# --- API ------------------------------------------------------------------
cleanup() { [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
            [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

check_port 8000
say "Starting the API on http://localhost:8000"
( cd backend && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 ) &
API_PID=$!

for _ in $(seq 1 45); do
  curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  kill -0 "$API_PID" 2>/dev/null || die "the API exited on startup — see the log above"
  "$PY" -c 'import time; time.sleep(1)'
done
curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null \
  || die "the API did not come up within 45s"

CHUNKS=$(curl -sf http://127.0.0.1:8000/api/v1/corpus \
         | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["chunks"])' 2>/dev/null || echo 0)
say "API is up — $CHUNKS chunks indexed"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  cat <<'NOTE'

  Note: ANTHROPIC_API_KEY is not set, so the answer wording comes from a
  deterministic stand-in and the UI labels it "Canned prose - no API key".
  Retrieval, citations, deadlines and compliance screening are real either
  way. Export the key and restart to generate the wording for real.

NOTE
fi

if [ "$BACKEND_ONLY" = 1 ]; then
  say "Backend only. API docs: http://localhost:8000/docs — Ctrl-C to stop."
  wait "$API_PID"; exit 0
fi

# --- web UI ---------------------------------------------------------------
FRONTEND="$ROOT/frontend"
if [ ! -f "$FRONTEND/package.json" ]; then
  cat <<NOTE

  frontend/ is missing or incomplete, so only the API is running:
  http://localhost:8000/docs

  If this is a partial checkout, restore it with:  git checkout -- frontend
NOTE
  wait "$API_PID"; exit 0
fi

command -v npm >/dev/null || die "npm not found. Install Node.js 18+ from https://nodejs.org"

if [ ! -d "$FRONTEND/node_modules" ]; then
  say "Installing web UI dependencies (first run only)"
  ( cd "$FRONTEND" && npm install --no-fund --no-audit ) || die "npm install failed"
fi

check_port 5173
say "Starting the web UI"
( cd "$FRONTEND" && VITE_API_TARGET=http://127.0.0.1:8000 \
    exec npm run dev -- --host 127.0.0.1 --port 5173 --strictPort ) &
WEB_PID=$!

for _ in $(seq 1 45); do
  curl -sf --max-time 2 http://127.0.0.1:5173/ >/dev/null 2>&1 && break
  kill -0 "$WEB_PID" 2>/dev/null || die "the web UI exited on startup — see the log above"
  "$PY" -c 'import time; time.sleep(1)'
done

cat <<'BANNER'

  ------------------------------------------------------------
    Open  http://localhost:5173  in your browser.

    Open that URL, not the index.html file. A file:// page has no
    API to talk to and will show the sample-data banner.
  ------------------------------------------------------------

  Ctrl-C to stop both.

BANNER

wait
