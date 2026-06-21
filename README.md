# autonomous-researcher

A fully local research agent. Ask a question; a local LLM (served by
[llama.cpp](https://github.com/ggml-org/llama.cpp) over its OpenAI-compatible
`/v1` API) autonomously searches the web, reads pages, and writes a **cited
markdown report** — no cloud APIs involved. Web search runs through a local
[SearXNG](https://github.com/searxng/searxng) instance.

## How it works

```
User ──▶ main.py (CLI)  or  app.py (FastAPI + web UI)
              │
              ▼
       research() agent loop  ── calls ──▶ llama.cpp /v1 server  (:8081)
              │
              ▼
       tools.py: search_web / read_url / ingest_file / write_file
              │                  │
              ▼                  ▼
       SearXNG (:8888)      web pages (HTTP)
```

The agent loop (`research()` in `main.py`) runs up to `MAX_ITERATIONS` turns.
Each turn it calls the LLM with three tools; if the model returns tool calls
they're executed and the results fed back, and when it returns plain text that
becomes the final report. Malformed tool calls (which weak local models emit)
are caught, surfaced back to the model to retry, and the loop bails after a few
consecutive failures.

## Components

| File | Role |
|------|------|
| `main.py` | Core agentic loop + CLI entry point |
| `tools.py` | The three agent tools (Pydantic-validated) and the tool dispatcher |
| `app.py` | FastAPI server: serves the web UI and exposes `/api/research`, `/api/health` |
| `searcher.py` | Standalone CLI to test `search`/`read` without the LLM |
| `rendering.py` | Headless-Chromium fallback for JavaScript-heavy (SPA) pages |
| `static/index.html` | Single-page web UI |

### Tools

- **`search_web`** — query the local SearXNG instance, return title/url/snippet
- **`read_url`** — fetch a page, strip chrome, truncate to ~12k chars to protect the context window
- **`write_file`** — write within the working directory only (path-traversal protected)

## Ports

| Service | Default port |
|---------|--------------|
| llama.cpp (LLM `/v1`) | `8081` |
| SearXNG | `8888` |
| Web UI (FastAPI) | `8800` |

## Prerequisites

- Python 3.10+
- [llama.cpp](https://github.com/ggml-org/llama.cpp) built, with a GGUF model
  (default: `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` — the 8B is far more
  reliable at tool-calling than the 1B)
- Docker (for SearXNG)

## Quick start

```bash
./setup.sh                              # create .venv, install deps (run once)

# one-command path: bring up both services, then run the agent
./start-all.sh "What changed in Python 3.13?"
./stop.sh                               # tear everything down
```

Or start the pieces manually:

```bash
./start-llm.sh                          # llama.cpp server on :8081
./start-searxng.sh                      # SearXNG on :8888 (Docker)

./run.sh "Summarize the latest on <topic>"   # CLI agent
./run.sh                                      # interactive prompt
./serve.sh                                    # web UI on http://127.0.0.1:8800
```

Test the search/read tools directly, without the LLM:

```bash
./.venv/bin/python searcher.py search "claude code"
./.venv/bin/python searcher.py read https://example.com
```

## Configuration

Everything is overridable via environment variables:

| Variable | Default | Used by |
|----------|---------|---------|
| `LLM_BASE_URL` | `http://127.0.0.1:8081/v1` | agent |
| `LLM_MODEL` | `local` | agent |
| `LLM_TEMPERATURE` | `0.2` | agent |
| `LLM_MAX_TOKENS` | `8192` | agent |
| `MAX_ITERATIONS` | `12` | agent loop |
| `SEARXNG_URL` | `http://localhost:8888` | `search_web` |
| `READ_URL_MAX_CHARS` | `12000` | `read_url` |
| `HTTP_TIMEOUT` | `20` | tools |
| `PORT` (llama.cpp) | `8081` | `start-llm.sh` |
| `MODEL_FILE` / `MODEL` | `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` | `start-llm.sh` |

## Plan A (default research mode)

By default `research()` runs the **Plan A orchestrator** (`RESEARCH_MODE=plan_a`):
SearXNG search → web ingest (chunked) → cited synthesis → claim verification → report.

```
User ──▶ main.py / app.py
              │
              ▼
       research_engine.run_research_plan()
              │
              ▼
   plan → search → ingest → synthesize → verify → critique → finalize
              │       │        │
              ▼       ▼        ▼
          SearXNG  Internet  ingest/ (≤1024-token chunks)
              │
              ▼
       research_graph/ (claims + verification footer)
              │
              ▼
       observer/ (cross-component event bus)
```

### Run Plan A

```bash
./start-llm.sh
./start-searxng.sh
# optional semantic chunk boundaries:
./start-embed.sh

./run.sh "What changed in Python 3.13?"
./serve.sh                    # http://127.0.0.1:8800
# live events: http://127.0.0.1:8800/monitor

python -m orchestrator.cli run "your question"
python -m observer tail
python -m ingest path/to/doc.pdf
```

### Docker

```bash
docker compose up --build
# LLM still on host :8081 — set LLM_BASE_URL=http://host.docker.internal:8081/v1
```

### Plan A configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESEARCH_MODE` | `plan_a` | Set `legacy` for the original tool loop |
| `RESEARCH_ALLOW_UNVERIFIED` | off | Set `1` to publish with unsupported claims |
| `RESEARCH_PERSIST_MEMORY` | off | Set `1` to save report to Qdrant via memory agent |
| `RESEARCH_MAX_URLS` | `6` | Max URLs ingested per run |
| `MAX_CHUNK_TOKENS` | `1024` | Ingest chunk cap |
| `EMBED_BASE_URL` | — | Enable semantic boundary splits (`:8082`) |
| `SEMANTIC_BOUNDARY_THRESHOLD` | `0.35` | Cosine cut between sentences |
| `HTTP_USER_AGENT` | Chrome-like + `AutonomousResearcher/2.0` | Browser-like fetch headers |
| `RESEARCH_URL_ALLOWLIST` | — | Comma-separated hostnames; empty = all URLs |

### Legacy mode

```bash
RESEARCH_MODE=legacy ./run.sh "your question"
```

Uses the original LLM tool loop (`search_web`, `read_url`, `write_file`) in `main.py`.

## personal-memory-agent

See [`personal-memory-agent/README.md`](personal-memory-agent/README.md) for the
lifelong chat assistant with Qdrant recall. When `RESEARCH_PERSIST_MEMORY=1`, Plan A
reports are stored in `agent_memories` and can be recalled in chat.
