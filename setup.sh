#!/bin/bash
#
# setup.sh — create the Python venv and install dependencies.
#
# Run once before the first launch:  ./setup.sh
# Override the interpreter with PYTHON=/path/to/python3 ./setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$HERE/.venv}"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "❌ Error: python interpreter '$PYTHON' not found." >&2
    echo "   Set PYTHON=/path/to/python3 to override." >&2
    exit 1
fi

echo "🐍 Creating venv at $VENV"
"$PYTHON" -m venv "$VENV"

echo "📦 Installing requirements"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$HERE/requirements.txt"

echo "✅ Setup complete. Next: ./start-llm.sh and ./start-searxng.sh, then ./run.sh \"your question\""
