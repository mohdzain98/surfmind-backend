# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FastAPI backend for SurfMind: accepts browser history/bookmark payloads,
caches them in Redis (1-hour TTL), and persists them to Postgres/pgvector
(`pages` / `page_sections` / `section_embeddings`) so search doesn't rebuild
an index per request. Search runs a hybrid BM25 (Redis-cached corpus) +
pgvector (persisted) retrieval, merged and re-ranked, then an LLM
post-processing/judge pass and structured output extraction. Browsers can
pair into a shared `sync_account_id` (cross-browser sync); LLM/embedding
calls are provider-based (OpenAI/Gemini, which is primary vs. fallback is
configured per use-case in `config/params.<env>.yml`) with automatic
failover in the client layer. A separate JWT-gated admin API exposes
server/data status and a handful of account-management actions.

## Commands

Setup (from repo root):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires a `.env` with `OPENAI_API_KEY`, `GEMINI_API_KEY`, `REDIS_HOST`,
`REDIS_PORT`, `DATABASE_URL` (Postgres/pgvector), `ADMIN_JWT_SECRET` (admin
API login), and a running Redis + Postgres (with the `vector` extension).

Run migrations, then the server:

```bash
alembic upgrade head
uvicorn src.controller.main_controller:app --reload --host 0.0.0.0 --port 8000
```

Create an admin login (required once before the admin API is usable):

```bash
python -m scripts.create_admin --username <name>
```

Lint/format (config lives in root `pyproject.toml`, line-length 88, py311
target; ruff rules: E, F, I):

```bash
black .
ruff check .
```

There is no test suite in this repo currently — changes are verified with
ad-hoc scripts against a real local Postgres/Redis instead.

## Architecture

`main_controller.py` (FastAPI app, CORS, startup Postgres/Redis connectivity
logging, the DB log listener) mounts three routers: `core_controller.py`
(`/v1`, search/save-data), `sync_controller.py` (`/v1/sync`, pairing), and
`admin_controller.py` (`/v1/admin`, gated by JWT).

### Core (`core_controller.py`)
- **`POST /v1/save-data`** caches the payload in Redis (`user:{sync_account_id}
  :{flag}`, 1h TTL) and ingests it into Postgres via `ingestion_service`
  (embeddings written once at save time, not rebuilt per search). Keys and
  storage are scoped to the *resolved* `sync_account_id`, not the raw
  browser id, so paired browsers share one pool/cap.
- **`POST /v1/search`** / **`POST /v1/search-stream`** (SSE) run
  `CoreRetrieval.invoke_rag`/`stream_rag`/`stream_combined_rag`. Every doc
  in the response carries `metadata.found_on_other_browser` (computed
  server-side by comparing `source_browser_uuid` against the requesting
  browser — the frontend just renders the flag, no client-side comparison
  needed).
- Endpoints that need identity for MV3 service workers are **POST**, not
  GET — a GET request from an MV3 background service worker doesn't
  reliably carry an `Origin` header, which breaks nginx's Origin-allowlist
  check. Applies to `/v1/sync/status`, `/v1/recent-searches`, and everything
  under `/v1/sync`.

### Ingestion (`src/services/ingestion_service/ingestion.py`)
`ingest_batch` upserts one `Page` row per URL (`(user_id, url_hash, flag)`
unique), its `PageSection`s, and embeds only sections whose content
actually changed. Embedding requests are chunked to stay under a
250k-token budget (`_chunk_by_token_budget`, `tiktoken`) — a single large
sync's sections can otherwise collectively exceed OpenAI's 300k-token
per-request cap and fail the *entire* embedding step at once (hit live in
prod). Every embedding call also records an `LLMUsage` row
(`use_case="embeddings"`) for cost tracking. `_trim_to_cap` evicts oldest
pages beyond the per-flag retention cap (`history_cap`/`bookmark_cap`,
env-tiered in `config/params.yml`) after every ingest.

Two attribution columns on `Page`, easy to confuse:
- `source_browser_uuid` — set on **insert only**, never overwritten. "Who
  found this first," used for search attribution
  (`found_on_other_browser`).
- `last_synced_browser_uuid` — updated on **every** insert/update. "Did
  *this* browser's sync actually land," used by
  `sync_service.get_page_counts` (`POST /v1/sync/page-counts`) so the
  extension can compare its local counts against what's actually
  persisted and decide whether to offer a manual resync.

### Sync/pairing (`src/services/sync_service/sync.py`, `sync_controller.py`)
`browser_uuid` → `sync_account_id` via `users`. `generate_code`/`redeem_code`
pair browsers (rate-limited via a Postgres advisory lock; redemption is a
single atomic `UPDATE ... RETURNING`, not select-then-update, to avoid a
double-redemption race). On redeem, `_migrate_browser_pages` moves the
joining browser's own pre-pairing pages (matched by `source_browser_uuid`)
onto the shared account — a "recency wins" policy resolves any URL a
browser independently visited on both sides of the pairing. `unlink`
detaches a browser back to its own account, reclaiming its own pages —
raises `AlreadySolo` if the browser isn't actually linked to anyone (was
previously a silent no-op that just created an orphaned account).
`delete_account` (admin-only) permanently removes a solo account; raises
`AccountStillLinked` if it still has 2+ browsers.

`DATA_SCHEMA_VERSION` (`src/utility/settings.py`, exposed on `/health` and
`/v1/sync/status`) lets the extension detect a backend storage/ingestion
change that could strand already-"synced" local data (e.g. the Redis-only
→ Postgres migration did) and force one resync — bump it only when that
kind of change ships.

### Retrieval (`src/services/core_service/rag.py`, `main.py`)
**`HybridRAGService`** splits parent docs (full page content) into
sentence-grouped, token-bounded child chunks, runs BM25 (in-app, over the
Redis-cached corpus) and pgvector (persisted, via `_run_pgvector`, scoped
by `user_id`+`flag`) in parallel, then merges hits back to parent docs —
pgvector weighted higher normally, BM25 higher when its own hits look weak.
A typo-tolerant query expansion pass runs before BM25.

**`LLMRag`** builds the LangChain prompt chains: one produces a free-text
answer, a second (`structure`) parses it into a Pydantic schema via
`JsonOutputParser`. `safe_invoke_llm_response` tries the primary provider
and falls back to the secondary on failure — both the response text and a
`{"provider", "model", "input_tokens", "output_tokens"}` usage dict are
returned, recorded by the caller as an `LLMUsage` row.

**`PostProcessing`** (`post_processing_service/post_processing.py`) is an
LLM-as-judge pass (prompt from `config/prompts.yml`) that drops irrelevant
docs from the retrieved set — same usage-recording pattern as `LLMRag`.

### Provider/model layer
`src/services/llm_service/llm_provider.py` (`LLMProvider`) registers chat
clients (rate-limited). `src/utility/provider.py` (`EmbeddingsProvider`)
provides cached embedding clients wrapped in `FallbackEmbeddings`
(auto-switches on quota/rate-limit errors) — it does not report back which
provider actually served a call, so embedding cost attribution
(`src/utility/pricing.py`) uses the configured primary as a best-effort
label. Primary/fallback provider and model are configured per use-case
(`rag`, `post_processing`, `embeddings`) in `config/params.<env>.yml`, read
through `src/utility/settings.py` (the single entry point for runtime
config — nothing else should read those YAML files directly).

### Admin API (`admin_controller.py`, `/v1/admin`)
JWT-gated (`POST /login`; every other route requires
`Authorization: Bearer <token>`). Admin accounts exist only via
`scripts/create_admin.py` — no public registration. Read-only status:
`status/health` (Postgres/pgvector/Redis + systemd service status via
`systemctl is-active` + disk usage), `status/stats`, `status/logs`
(persisted `app_logs`, populated automatically from every WARNING+ log
line app-wide via `src/utility/db_log_handler.py` — a `QueueListener` on a
background thread, decoupled from the async engine to avoid a
cross-event-loop connection-pool reuse bug), `status/llm-usage` (token
usage + `costUsd` estimates from `src/utility/pricing.py`, a manually
maintained rate table — no live billing API exists), `status/search-metrics`,
`status/nginx-logs` (tails nginx's log files directly off disk — a
different source than `app_logs`, since nginx runs as its own process).
`GET /accounts` (paginated, sortable, includes a normalized 0-100
`activityScore`) and `/accounts/{id}` for lookup. Mutating actions
(`unlink-browser`, `clear-data`, sync-code `revoke`, account `delete`) all
log an entry back into `app_logs` as a lightweight audit trail.

### Exception handling
`src/handlers/llm_exception_handler.py` and `redis_exception_handler.py`
map raw exceptions to user-facing messages via per-provider mappers in
`src/handlers/mappers/`.

## Deployment

`.github/workflows/main.yml` (prod) and `staging.yml` (staging) deploy via
SSH on push: reset to the branch tip, clean untracked files (excluding
`.env`, `requirements.lock`, `data/`, `logs/`, `senv/`), reinstall
dependencies only if `requirements.txt` changed, run `alembic upgrade
head`, and restart the systemd unit (`surfmind.service` prod,
`surfmind-staging.service` staging). Prod's virtualenv directory is
`senv/`, not `.venv/`. nginx reverse-proxies both, with a per-path Origin
allowlist and `client_max_body_size` (raised from nginx's 1MB default —
a large sync payload can exceed it) — both are nginx config, not
something this app controls.
