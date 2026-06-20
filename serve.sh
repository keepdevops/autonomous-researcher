#!/bin/bash
#
# serve.sh — run the FastAPI front end for the autonomous researcher.
#
# Assumes ./start-llm.sh and ./start-searxng.sh are already up.
#   ./serve.sh                 # http://127.0.0.1:8800
#   PORT=9000 ./serve.sh
# Override endpoints with LLM_BASE_URL / SEARXNG_URL.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$HERE/.venv}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8800}"

export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:8080/v1}"
export SEARXNG_URL="${SEARXNG_URL:-http://localhost:8888}"

if [ ! -x "$VENV/bin/python" ]; then
    echo "❌ Error: venv missing at $VENV. Run ./setup.sh first." >&2
    exit 1
fi

# Warn loudly if a backing service looks down, rather than failing per-request.
if ! curl -sf "${LLM_BASE_URL%/v1}/health" >/dev/null 2>&1 \
   && ! curl -sf "$LLM_BASE_URL/models" >/dev/null 2>&1; then
    echo "⚠️  LLM server not responding at $LLM_BASE_URL — start it with ./start-llm.sh" >&2
fi
if ! curl -sf "$SEARXNG_URL" >/dev/null 2>&1; then
    echo "⚠️  SearXNG not responding at $SEARXNG_URL — start it with ./start-searxng.sh" >&2
fi

echo "🌐 Researcher UI on http://$HOST:$PORT  (LLM=$LLM_BASE_URL  SearXNG=$SEARXNG_URL)"
exec "$VENV/bin/python" -m uvicorn app:app --host "$HOST" --port "$PORT" --app-dir "$HERE"
