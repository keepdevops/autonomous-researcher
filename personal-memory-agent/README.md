# personal-memory-agent

A fully local, **RAG-powered private recall system** — a lifelong chat assistant
that remembers everything you tell it and recalls it with hybrid semantic +
lexical search. No cloud APIs: the chat model, the embedding model, and the
vector store all run on your machine.

## How it works

```
You ──▶ main.py (chat loop)
          │
          │  1. embed the question (dense + BM25)
          ▼
   memory.py: search_memories()  ──▶  Qdrant (:6333)   hybrid recall (RRF)
          │                                │
          │  2. inject recalled memories   │  dense: 768-d nomic vectors
          │     into THIS turn only        │  bm25:  IDF-weighted sparse
          ▼                                ▼
   chat model (:8081) ◀── system + recent turns + recall-augmented question
          │
          │  3. persist the clean exchange back to long-term memory
          ▼
   add_memory("user", ...) / add_memory("assistant", ...)  ──▶  Qdrant
```

Every exchange is embedded and stored as one Qdrant point carrying **two
vectors**: a 768-d dense `nomic-embed-text-v1.5` embedding (semantic similarity)
and a sparse BM25 vector (exact lexical match). Queries run both branches and
fuse the rankings with **Reciprocal Rank Fusion (RRF)** for high recall.

### Bounded context, unbounded memory

The chat loop keeps only the last `HISTORY_WINDOW_TURNS` (default 8) verbatim
turns in the prompt. Everything older is recalled from the vector store on
demand and injected into the *current* turn only — never accumulated. This keeps
the prompt within the model's context window no matter how long the conversation
runs, which is what makes "lifelong" recall actually work.

A background thread runs `reflector.run_daily_reflection()` every 24h to scan
recent assistant memories for contradictions and store corrections.

## Components

| File | Role |
|------|------|
| `main.py` | Chat loop: recall → prompt → respond → persist |
| `memory.py` | Qdrant hybrid (dense + BM25) store and RRF search |
| `embedder.py` | Client for the llama.cpp embedding server (:8082) |
| `sparse.py` | FastEmbed BM25 sparse encoder |
| `reflector.py` | Daily self-reflection / contradiction correction |

## Prerequisites

This agent needs **three** services running:

| Service | Port | Start with |
|---------|------|------------|
| Chat model (llama.cpp `/v1`) | `8081` | `../start-llm.sh` |
| Embedding model (`nomic-embed-text-v1.5`) | `8082` | `../start-embed.sh` |
| Qdrant vector store | `6333` | see below |

Qdrant runs in docker with this project's `qdrant_storage/` bind-mounted as its
data volume (so memories survive restarts):

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_storage:/qdrant/storage" qdrant/qdrant
```

> ⚠️ `qdrant_storage/` is **live data**, not a build artifact. Never delete it
> while the container is running, or you'll corrupt the running store.

The chat and embedding models **must** be on separate ports — they are two
distinct llama.cpp servers.

## Run

```bash
pip install -r requirements.txt   # qdrant-client[fastembed], httpx, rich, pydantic
python main.py                    # type 'exit' to quit
```

## Durable task-graph orchestrator

Beyond the linear chat loop, the agent can run multi-step plans as a **checkpointed
DAG** with branching, parallelism, crash/approval resume, and a full event trace.

| File | Role |
|------|------|
| `state.py` | `RunState`/`StepState` Pydantic models (the resumable state) |
| `graph.py` | `Step` nodes wired by `deps`; routing via `choose`, joins via `join_any` |
| `executor.py` | Async walk: ready frontier → parallel fan-out → checkpoint each transition; pauses on failure or approval gate |
| `checkpoint.py` | SQLite (`runs.db`) — latest state per run + append-only event trace |
| `example_plan.py` | A 12-step demo plan exercising every feature |
| `orchestrate.py` | CLI: `run` / `status` / `resume` / `list` |

```bash
python orchestrate.py run "Compare local vector databases for personal recall"
#   ...runs steps 1-6 in parallel where possible, then (in the demo) FAILS at
#   step 7 and checkpoints. Inspect and resume:
python orchestrate.py status <run_id>          # plan with ✔/✘/–/⏸ + event trace
python orchestrate.py resume <run_id>          # picks up at step 7, runs to the gate
python orchestrate.py resume <run_id> --approve persist   # clears the human gate
```

What each feature maps to: **branching** = a router step's `choose` (unchosen
successors are SKIPPED); **parallelism** = the executor fans out every ready step
via `asyncio.to_thread`, and a `join_any` step reconverges them; **persistence** =
state is checkpointed after every transition, so a crash at "7 of 12" resumes at
7; **observability/intervention** = the event trace plus `requires_approval` gates
that pause the run for human review.

> For real parallel *speedup* (not just interleaving), start `llama-server` with
> continuous batching: `--parallel N` and a context sized for N concurrent slots.

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_BASE_URL` | `http://127.0.0.1:8081/v1` | Chat model endpoint |
| `EMBED_BASE_URL` | `http://127.0.0.1:8082/v1` | Embedding model endpoint |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant server |
| `QDRANT_COLLECTION` | `agent_memories` | Collection name |
| `HISTORY_WINDOW_TURNS` | `8` | Verbatim turns kept in-prompt |
