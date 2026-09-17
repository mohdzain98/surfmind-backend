# SurfMind Backend

FastAPI service for SurfMind's retrieval pipeline. It accepts browser history
and bookmark payloads, caches them in Redis, persists them to Postgres with
pgvector embeddings, and answers search requests using hybrid retrieval
(BM25 + pgvector) with LLM-based post-processing and answer generation.

## Stack

- FastAPI
- Redis (short-lived cache + BM25 corpus)
- Postgres + pgvector (persisted storage + vector search)
- Alembic (migrations)
- LangChain
- OpenAI and Gemini (generation, embeddings — provider-based with fallback)

## Prerequisites

- Python 3.11
- Redis
- Postgres with the `pgvector` extension (`docker-compose.yml` provides a
  local one via `pgvector/pgvector:pg16`)

## Setup

From the repo root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`):

```env
OPENAI_API_KEY=...
GEMINI_API_KEY=...
REDIS_HOST=localhost
REDIS_PORT=6379
DATABASE_URL=postgresql+asyncpg://surfmind_app:password@localhost:5432/surfmind_db
ENVIRONMENT=development
```

`ENVIRONMENT` selects `config/params.dev.yml` or `config/params.prod.yml`
(retention caps, sync rate limits, LLM provider/model choices) — see
`src/utility/settings.py`, the single entry point for all runtime config.

Start Postgres (local dev):

```bash
docker compose up -d
```

Run migrations:

```bash
alembic upgrade head
```

## Run

Start Redis and Postgres, then launch the API:

```bash
uvicorn src.controller.main_controller:app --reload --host 0.0.0.0 --port 8000
```

Health checks:

- `GET /`
- `GET /health`

## API

Base router prefix: `/v1`

**Core**
- `POST /v1/save-data` — saves history, bookmark, or combined payloads to
  Redis (1-hour TTL) and upserts them into Postgres with embeddings.
- `POST /v1/search` — runs the non-streaming RAG pipeline, returns a
  `SearchResponse`.
- `POST /v1/search-stream` — streams retrieval/generation progress and the
  final result as server-sent events.
- `GET /v1/recent-searches` — the requesting account's recent successful
  searches.
- `DELETE /v1/user/history` — clears history only (bookmarks, search
  history, and account/sync links are untouched).
- `DELETE /v1/user/data` — full reset: history, bookmarks, search history,
  and their Redis cache (account, tier, and paired browsers persist).

**Sync** (prefix `/v1/sync`)
- `POST /generate-code` — issue a short-lived pairing code for the
  requesting browser's account.
- `POST /redeem-code` — join the requesting browser to the code's account.
- `POST /unlink` — repoint the requesting browser onto a fresh solo account.
- `GET /status` — the requesting browser's link status (never errors on an
  unknown browser — a normal "not yet linked" response).

## Request Shapes

`save-data` expects one entry per heading-scoped section (a single item's
`content` field can also be a nested array of section objects sharing one
outer url/title, which the backend flattens automatically):

```json
{
  "browser_uuid": "stable-browser-uuid",
  "flag": "history",
  "data": [
    {
      "url": "https://example.com",
      "content": "Page content",
      "date": 1700000000000,
      "domain": "example.com",
      "folder": "",
      "title": "Example",
      "heading_path": ["Example", "Section"],
      "heading_level": 1,
      "section_index": 0
    }
  ],
  "bookmarks": []
}
```

`search` and `search-stream` expect:

```json
{
  "browser_uuid": "stable-browser-uuid",
  "query": "what did I read about embeddings?",
  "flag": "history"
}
```

Supported `flag` values are `history`, `bookmark`, and `combined`. Every
request identity field accepts either `browser_uuid` or the camelCase
`userId`/`browserUuid` alias.

## Load Testing

`load_tests/` (gitignored, local-only) has Locust scenarios for search,
ingestion, and sync-pairing concurrency, plus a targeted race-condition
script for sync code generation/redemption. See
`docs/task_and_plans/load_testing.md` for how to run them.
`scripts/cleanup_test_data.py` is tracked and deployable — it removes
everything those tools create (tagged with a `loadtest-` identity prefix),
safe to run on any server including prod after a load test run there.

## Notes

- Embeddings and generation are provider-based with OpenAI/Gemini fallback.
- Redis is required for both save and search flows; Postgres is required
  for persisted storage, retrieval, and sync/privacy endpoints.
- Formatting and linting are configured through the repo root
  `pyproject.toml` (black, ruff). See `CONTRIBUTING.md` for conventions.
