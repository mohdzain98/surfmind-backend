# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FastAPI backend for SurfMind: accepts browser history/bookmark payloads, caches
them in Redis (1-hour TTL), and answers search queries using a hybrid
BM25+FAISS retrieval pipeline with LLM-based post-processing and structured
output extraction. LLM/embedding calls are provider-based (Gemini default,
OpenAI fallback) with automatic failover baked into the client layer.

## Commands

Setup (from repo root):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires a `.env` with `OPENAI_API_KEY`, `GEMINI_API_KEY`, `REDIS_HOST`,
`REDIS_PORT`, and a running Redis instance.

Run the server:

```bash
uvicorn src.controller.main_controller:app --reload --host 0.0.0.0 --port 8000
```

Lint/format (config lives in root `pyproject.toml`, line-length 88, py311
target; ruff rules: E, F, I):

```bash
black .
ruff check .
```

There is no test suite in this repo currently.

## Architecture

Request flow: `main_controller.py` (FastAPI app, CORS, health checks) mounts
`core_controller.py` (`/v1` router). The controller owns the Redis client
directly and talks to `CoreRetrieval` (via `Retrieval.get_retrieval_service`
FastAPI dependency) for anything RAG-related.

- **`POST /v1/save-data`** writes payloads to Redis under
  `user:{user_id}:{flag}` (or `:ch`/`:cb` sub-keys when `flag == "combined"`,
  splitting history and bookmarks).
- **`POST /v1/search`** runs `CoreRetrieval.invoke_rag` and returns a full
  `SearchResponse`.
- **`POST /v1/search-stream`** runs `stream_rag` or `stream_combined_rag`
  (SSE), yielding step events (`retrieved_parents` → `post_processing` →
  `llm_response` → `output_parser` → `final`). `combined` flag retrieves and
  post-processes history and bookmarks as two independent corpora (in
  parallel for retrieval, sequential for LLM post-processing to avoid rate
  limits) then concatenates results — history first, then bookmarks — so the
  frontend (`Popup.js`) can re-split them by `metadata.type`.

**`CoreRetrieval`** (`src/services/core_service/main.py`) is the orchestrator:
builds parent `Document`s from raw history/bookmark dicts, calls
`HybridRAGService.retrieve_parents`, runs the LLM response chain, parses
structured output, and applies post-processing filtering.

**`HybridRAGService`** (`src/services/core_service/rag.py`) implements
parent/child chunking: parent docs (full page content) are split into child
chunks via `RecursiveCharacterTextSplitter`, then BM25 and FAISS retrievers
run in parallel over the children. A typo-tolerant query expansion pass runs
before BM25. Scores are merged back to parent docs — FAISS weighted higher
normally, BM25 weighted higher when its own hits look weak (`_bm25_is_weak`).

**`LLMRag`** (same file) builds the LangChain prompt chains: one chain
produces a free-text answer (`history`/`bookmark`/`combined` prompt
variants), a second (`structure`) parses that answer into a Pydantic schema
(`Ans_history`/`Ans_bookmark`/`Ans_combined` in `src/models/core.py`) via
`JsonOutputParser` with retry. `safe_invoke_llm_response` tries the default
model (Gemini) and falls back to the other (OpenAI) on failure.

**`PostProcessing`** (`src/services/post_processing_service/post_processing.py`)
uses an LLM-as-judge call (Gemini, falling back to GPT) against a prompt
template loaded from `config/prompts.yml` to identify and drop irrelevant
docs from the retrieved set.

**Provider/model layer**: `src/models/ai_models.py` defines the `Models` enum
(`GEMINI` is default, `GPT` is other) used throughout to pick primary vs.
fallback. `src/services/llm_service/llm_provider.py` (`LLMProvider`)
registers the actual chat clients (rate-limited via `InMemoryRateLimiter`).
`src/utility/provider.py` (`EmbeddingsProvider`) provides cached embedding
clients, wrapped in `FallbackEmbeddings` which auto-switches provider on
quota/rate-limit errors (429, `resource_exhausted`, etc.) transparently to
callers.

**Exception handling**: `src/handlers/llm_exception_handler.py` and
`redis_exception_handler.py` map raw exceptions to user-facing messages via
per-provider mappers in `src/handlers/mappers/` (`openai_mapper.py`,
`gemini_mapper.py`, `redis_mapper.py`, `base_mapper.py`).

**Prompts** live in `config/prompts.yml` and are loaded through
`src/utility/utils.py` (`Utility.load_prompts`), consumed by
`src/services/llm_service/prompt_builder.py` (`Prompts`) and
`PostProcessing`.

## Deployment

`.github/workflows/main.yml` deploys on push to `main` via SSH: resets to
`origin/main`, cleans untracked files (excluding `data/`, `logs/`, `senv/`),
reinstalls dependencies only if `requirements.txt` changed, and restarts the
`surfmind.service` systemd unit. The prod virtualenv directory is `senv/`,
not `.venv/`.
