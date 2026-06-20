#!/bin/bash
#
# start-searxng.sh — run a local SearXNG (the search_web backend) via Docker.
#
# Listens on :8888 to avoid colliding with the llama.cpp server on :8080.
# Point the agent at it with:  SEARXNG_URL=http://localhost:8888
#   PORT=9001 ./start-searxng.sh        # use a different port
#   DETACH=1 ./start-searxng.sh         # run in the background
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8888}"
NAME="${NAME:-searxng-researcher}"
SETTINGS_DIR="${SETTINGS_DIR:-$HERE/searxng}"
DETACH="${DETACH:-0}"

if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Error: docker not found on PATH." >&2
    echo "   Install Docker Desktop, or set SEARXNG_URL to an existing instance." >&2
    exit 1
fi
if [ ! -f "$SETTINGS_DIR/settings.yml" ]; then
    echo "❌ Error: $SETTINGS_DIR/settings.yml missing (needed to enable JSON output)." >&2
    exit 1
fi

# Replace any prior container with the same name so reruns are idempotent.
docker rm -f "$NAME" >/dev/null 2>&1 || true

RUN_FLAGS=(--rm --name "$NAME" -p "127.0.0.1:$PORT:8080" \
    -v "$SETTINGS_DIR:/etc/searxng:rw" \
    -e "BASE_URL=http://localhost:$PORT/")

echo "🔎 SearXNG on http://localhost:$PORT  (JSON enabled)"
echo "   Point the agent at it with: SEARXNG_URL=http://localhost:$PORT"

if [ "$DETACH" = "1" ]; then
    docker run -d "${RUN_FLAGS[@]}" searxng/searxng:latest >/dev/null
    echo "   Running detached as container '$NAME'. Stop with: docker rm -f $NAME"
else
    echo "Press Ctrl+C to stop."
    exec docker run "${RUN_FLAGS[@]}" searxng/searxng:latest
fi
