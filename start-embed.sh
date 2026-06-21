#!/bin/bash
#
# start-embed.sh — launch a dedicated llama.cpp embedding server.
#
# The personal-memory-agent needs TWO servers at once: the chat model
# (start-llm.sh, :8081) and this embedding model. They MUST be on different
# ports, so embeddings default to :8082.
#   ./start-embed.sh                 # nomic-embed on :8082
#   PORT=9001 ./start-embed.sh
set -euo pipefail

BINARY="${LLAMA_BINARY:-/Users/caribou/llama.cpp/build/bin/llama-server}"
MODEL="${EMBED_MODEL:-/Users/caribou/test-llama/bret/autonomous-researcher/nomic-embed-text-v1.5.Q8_0.gguf}"

PORT="${PORT:-8082}"
CTX_SIZE="${CTX_SIZE:-8192}"
CPU_THREADS="${CPU_THREADS:-8}"

# Fail loudly rather than starting a broken server.
if [ ! -x "$BINARY" ]; then
    echo "❌ Error: llama-server not found/executable at $BINARY" >&2
    exit 1
fi
if [ ! -f "$MODEL" ]; then
    echo "❌ Error: embedding model not found at $MODEL" >&2
    exit 1
fi

echo "🧬 llama.cpp EMBEDDING server on :$PORT  (OpenAI API at http://127.0.0.1:$PORT/v1)"
echo "   Model: $(basename "$MODEL")  |  ctx: $CTX_SIZE"
echo "   Point the agent at it with: EMBED_BASE_URL=http://127.0.0.1:$PORT/v1"

exec "$BINARY" \
  -m "$MODEL" \
  -c "$CTX_SIZE" \
  --embedding \
  --pooling mean \
  --port "$PORT" \
  -t "$CPU_THREADS" \
  --no-mmap
