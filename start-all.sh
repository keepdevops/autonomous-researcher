#!/bin/bash
#
# start-all.sh — bring up both backing services in the background, then run the
# agent. One-command entry point after ./setup.sh has been run once.
#   ./start-all.sh "Summarize the latest on <topic>"
# Logs land in ./logs/. Stop everything with ./stop.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HERE/logs"
mkdir -p "$LOG_DIR"

LLM_PORT="${LLM_PORT:-8080}"
SEARX_PORT="${SEARX_PORT:-8888}"
export LLM_BASE_URL="http://127.0.0.1:$LLM_PORT/v1"
export SEARXNG_URL="http://localhost:$SEARX_PORT"

# Start SearXNG detached (Docker manages the process).
echo "▶ Starting SearXNG…"
PORT="$SEARX_PORT" DETACH=1 "$HERE/start-searxng.sh"

# Start the LLM server in the background, tracked by PID file.
if curl -sf "http://127.0.0.1:$LLM_PORT/health" >/dev/null 2>&1; then
    echo "▶ LLM already running on :$LLM_PORT"
else
    echo "▶ Starting llama.cpp server… (log: $LOG_DIR/llm.log)"
    PORT="$LLM_PORT" nohup "$HERE/start-llm.sh" >"$LOG_DIR/llm.log" 2>&1 &
    echo $! > "$LOG_DIR/llm.pid"
fi

# Wait for the LLM to become healthy before driving the agent.
echo -n "⏳ Waiting for LLM"
for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$LLM_PORT/health" >/dev/null 2>&1; then
        echo " — ready."
        break
    fi
    echo -n "."
    sleep 2
done

exec "$HERE/run.sh" "$@"
