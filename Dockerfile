# Autonomous Researcher — FastAPI web UI + agent loop.
# Backing services run separately (llama.cpp on :8081, SearXNG on :8888).
#
# Build:
#   docker build -t autonomous-researcher .
#
# Run (LLM + SearXNG on host):
#   docker run --rm -p 8800:8800 \
#     -e LLM_BASE_URL=http://host.docker.internal:8081/v1 \
#     -e SEARXNG_URL=http://host.docker.internal:8888 \
#     autonomous-researcher
#
# CLI one-shot:
#   docker run --rm \
#     -e LLM_BASE_URL=http://host.docker.internal:8081/v1 \
#     -e SEARXNG_URL=http://host.docker.internal:8888 \
#     autonomous-researcher \
#     python main.py "What changed in Python 3.13?"

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOST=0.0.0.0 \
    PORT=8800 \
    LLM_BASE_URL=http://host.docker.internal:8081/v1 \
    SEARXNG_URL=http://host.docker.internal:8888

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app.py main.py tools.py searcher.py rendering.py research_engine.py ./
COPY static/ ./static/
COPY observer/ ./observer/
COPY ingest/ ./ingest/
COPY orchestrator/ ./orchestrator/
COPY agents/ ./agents/
COPY research_graph/ ./research_graph/
COPY retrieval/ ./retrieval/
COPY monitor/ ./monitor/

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8800/api/health')" || exit 1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8800"]
