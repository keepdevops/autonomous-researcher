#!/bin/bash
#
# stop.sh — tear down services started by start-all.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HERE/logs"
NAME="${NAME:-searxng-researcher}"

if [ -f "$LOG_DIR/llm.pid" ]; then
    PID="$(cat "$LOG_DIR/llm.pid")"
    if kill "$PID" 2>/dev/null; then
        echo "🛑 Stopped llama.cpp server (pid $PID)"
    else
        echo "ℹ️  llama.cpp server (pid $PID) not running"
    fi
    rm -f "$LOG_DIR/llm.pid"
else
    echo "ℹ️  No LLM pid file; nothing to stop."
fi

if docker rm -f "$NAME" >/dev/null 2>&1; then
    echo "🛑 Stopped SearXNG container '$NAME'"
else
    echo "ℹ️  SearXNG container '$NAME' not running"
fi
