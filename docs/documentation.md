# Documentation

## What SurfMind Is

SurfMind is a Chrome extension paired with this FastAPI backend. The extension
captures a user's browsing history and bookmarks, sends them to the backend,
and lets the user ask natural-language questions about their own browsing —
"what was that pricing page I looked at last week?" — instead of scrolling
through Chrome's native history UI. The backend's job is to store that
captured content efficiently, retrieve the right pages for a given query, and
turn the retrieved content into a direct answer via an LLM.

## Architecture at a Glance

- **FastAPI** — the API surface (`src/controller/`), organized into three
  routers: core (`/v1/save-data`, `/v1/search`, `/v1/search-stream`,
  `/v1/user/*`), sync (`/v1/sync/*`), mounted from `main_controller.py`.
- **Redis** — a short-lived (1-hour TTL) cache of each sync account's raw
  history/bookmark payload, keyed by flag (`user:{id}:history`,
  `user:{id}:bookmark`). This is what BM25 keyword search runs against at
  query time — chunked and indexed in memory per request, not persisted.
- **Postgres + pgvector** — the durable store. Every page a user visits or
  bookmarks is upserted here, chunked into heading-scoped sections, and
  embedded once at ingestion time. This is what semantic (vector) search
  runs against, and what survives past the Redis TTL.
- **LLM providers** — OpenAI is the default for generation and embeddings,
  Gemini is the fallback; both directions exist (post-processing defaults to
  Gemini, falls back to OpenAI). Provider/model choice is entirely
  config-driven (`config/params.dev.yml` / `params.prod.yml`), not
  hardcoded, so swapping models doesn't require a code change.

## Data Model

- **`Page`** — one row per URL a user has visited or bookmarked (unique per
  `user_id` + `url` + `flag`). This is the retention-cap unit: a 24-section
  page still only costs one cap slot.
- **`PageSection`** — one row per heading-scoped section of a page. A simple
  page with no real heading structure gets exactly one section; a
  Readability-extracted article with several headings gets several.
- **`SectionEmbedding`** — the pgvector column for one section, queried via
  `ORDER BY embedding <=> :query` at search time. Only sections whose content
  actually changed get re-embedded on a re-sync — an unchanged resync costs
  nothing.
- **`SyncAccount` / `User` / `SyncCode`** — cross-browser identity. Every
  browser install gets an anonymous `browser_uuid`; `User` maps that to a
  shared `SyncAccount`. Pairing two browsers (via a short-lived code) points
  both at the same account, merging their history/bookmark pools and
  retention caps. All storage and retrieval is scoped to the resolved
  `sync_account_id`, never the raw browser id.
- **`SearchHistory`** — a snapshot of each successful search (query, answer,
  sources) so the "recent searches" UI can render instantly without
  re-running retrieval.

## Core Flows

**Ingestion (`POST /save-data`)** — the extension sends a batch of history or
bookmark items (one entry per heading-scoped section). The backend caches the
raw payload in Redis and, in the same request, upserts it into Postgres:
pages and sections are upserted by key, only genuinely changed sections get
re-embedded, and each user's page count is trimmed back to their configured
cap (oldest-by-visited-at evicted first, cascading to their sections and
embeddings). History and bookmark ingestion run concurrently when both are
present, each in its own database session.

**Retrieval (`POST /search-stream`, `POST /search`)** — a query runs through
a hybrid pipeline: BM25 keyword search over the Redis-cached, in-memory
chunked corpus, and a pgvector semantic search over the persisted section
embeddings, run concurrently. Their hits are merged and re-ranked (semantic
signal weighted higher when BM25's own matches look weak), deduplicated to
one section per page, then passed through an LLM-as-judge post-processing
step that filters out anything not actually relevant to the query. The
survivors go to the LLM to generate a direct answer, which is then parsed
into a small structured schema (source URL, date). The streaming endpoint
emits each stage as a separate SSE event so the extension's UI can show
retrieval progress rather than a blank wait.

**Cross-browser sync (`POST /sync/generate-code`, `POST /sync/redeem-code`,
`POST /sync/unlink`, `GET /sync/status`)** — one browser generates a
short-lived pairing code; another redeems it to join the same account. Code
redemption is atomic (an `UPDATE ... WHERE used = false ... RETURNING`, not
a check-then-update) so two simultaneous redemptions of the same code can't
both succeed, and code generation is serialized per-account via a Postgres
advisory lock so the hourly rate limit can't be raced past.

**Privacy (`DELETE /user/history`, `DELETE /user/data`)** — lets a user clear
just their history (bookmarks/search history untouched) or everything
(history, bookmarks, search history, and the matching Redis cache — but not
their account, tier, or paired-browser links, which persist as a reset
rather than a teardown).

## Configuration

`src/utility/settings.py` is the single entry point for all runtime
configuration — nothing else in the codebase reads `config/params.*.yml` or
environment variables directly. It loads `config/params.dev.yml` or
`config/params.prod.yml` based on `ENVIRONMENT` in `.env`, giving dev and
prod independently tunable retention caps, sync rate limits, and LLM
provider/model choices without touching code.

## Deployment

Both `main` (prod) and `staging` branches deploy via SSH + systemd on push
(`.github/workflows/main.yml` / `staging.yml`): the workflow resets the
target server's checkout to the pushed branch, reinstalls dependencies only
if `requirements.txt` changed, runs `alembic upgrade head`, and restarts the
corresponding systemd unit (`surfmind.service` for prod,
`surfmind-staging.service` for staging — distinct units so a staging push
can never restart prod). Postgres and Redis are expected to already be
running on the target server; the deploy workflow doesn't provision
infrastructure, only application code and schema.
