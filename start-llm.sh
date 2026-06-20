#!/bin/bash
#
# start-llm.sh — launch the llama.cpp OpenAI-compatible server for the agent.
#
# The agent relies on tool-calling, so the default is the 8B model (far more
# reliable at emitting tool calls than the 1B). Override anything via env:
#   MODEL_FILE=Llama-3.2-1B-Instruct-Q4_K_M.gguf ./start-llm.sh   # faster, weaker
#   PORT=9000 ./start-llm.sh
set -euo pipefail

BINARY="${LLAMA_BINARY:-/Users/caribou/llama.cpp/build/bin/llama-server}"
MODEL_DIR="${MODEL_DIR:-/Users/caribou/test-llama/models}"
MODEL_FILE="${MODEL_FILE:-Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}"
MODEL="${MODEL:-$MODEL_DIR/$MODEL_FILE}"

PORT="${PORT:-8080}"
CTX_SIZE="${CTX_SIZE:-8192}"
GPU_LAYERS="${GPU_LAYERS:-99}"
# Single-user CLI agent: one slot gets the full context window. Raise only if
# you intend to drive several concurrent conversations against this server.
PARALLEL_SLOTS="${PARALLEL_SLOTS:-1}"
CPU_THREADS="${CPU_THREADS:-8}"

# Fail loudly rather than starting a broken server.
if [ ! -x "$BINARY" ]; then
    echo "❌ Error: llama-server not found/executable at $BINARY" >&2
    echo "   Set LLAMA_BINARY=/path/to/llama-server to override." >&2
    exit 1
fi
if [ ! -f "$MODEL" ]; then
    echo "❌ Error: model not found at $MODEL" >&2
    echo "   Available models in $MODEL_DIR:" >&2
    ls -lh "$MODEL_DIR"/*.gguf 2>/dev/null >&2 || echo "   (none)" >&2
    echo "   Override with MODEL_FILE=name.gguf or MODEL=/path/to/model.gguf" >&2
    exit 1
fi

echo "🚀 llama.cpp server on :$PORT  (OpenAI API at http://127.0.0.1:$PORT/v1)"
echo "   Model: $(basename "$MODEL")  |  ctx: $CTX_SIZE  |  gpu-layers: $GPU_LAYERS"
echo "   Point the agent at it with: LLM_BASE_URL=http://127.0.0.1:$PORT/v1"
echo "Press Ctrl+C to stop."

exec "$BINARY" \
  -m "$MODEL" \
  -c "$CTX_SIZE" \
  --n-gpu-layers "$GPU_LAYERS" \
  --parallel "$PARALLEL_SLOTS" \
  --cont-batching \
  -fa on \
  --port "$PORT" \
  -t "$CPU_THREADS" \
  --no-mmap
