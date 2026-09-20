# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This backend didn't track changes before this file existed — the first
entry covers everything landed in the initial Postgres migration commit,
not a single day's work.

## 2026-09-20 — Admin API, cross-browser result attribution, pre-pairing recovery, cost tracking

### Added
- JWT-gated admin API (`/v1/admin`, `admin_controller.py`): `POST /login`;
  read-only `status/health` (now including systemd service status via
  `systemctl is-active` and disk usage), `status/stats`, `status/logs`
  (every WARNING+ log app-wide, captured automatically into a new
  `app_logs` table via a background-thread `QueueListener`, decoupled from
  the async engine to avoid a cross-event-loop connection-pool bug),
  `status/llm-usage` (token usage + `costUsd`/`totalCostUsd` estimates
  against a manually maintained pricing table, `src/utility/pricing.py`),
  `status/search-metrics`, `status/nginx-logs` (tails nginx's own log
  files off disk); `GET /accounts` (paginated, sortable by
  `activity_score`/`created_at`/`browser_count`, includes a normalized
  0-100 `activityScore`) and `/accounts/{id}`. Mutating actions
  (`unlink-browser`, `clear-data`, sync-code `revoke`, account `delete`)
  each log an audit-trail entry back into `app_logs`. Admins are
  provisioned only via `scripts/create_admin.py` — no public registration.
- Cross-browser search-result attribution: `pages.source_browser_uuid`
  (set on insert only — "who found this first") and, separately,
  `pages.last_synced_browser_uuid` (updated on every insert/update — "did
  this browser's sync actually land"). Every search result now carries
  `metadata.found_on_other_browser` (computed server-side, not left to the
  frontend to diff against its own `browser_uuid`).
- Pre-pairing data recovery: redeeming a pairing code now migrates the
  joining browser's own pre-pairing pages onto the shared account
  (matched via `source_browser_uuid`), instead of leaving them stranded
  under an account no browser resolves to anymore. A "recency wins"
  policy resolves any URL both browsers independently visited before
  pairing.
- `POST /v1/sync/page-counts` — a browser's own persisted history/bookmark
  counts (via `last_synced_browser_uuid`), so the extension can compare
  against its local counts and offer a manual resync only when they
  genuinely differ.
- `DATA_SCHEMA_VERSION` (`settings.py`, exposed on `/health` and
  `/v1/sync/status`) — lets the extension detect a backend storage change
  that could strand already-"synced" local data and force one resync,
  without a new polling loop (piggybacks on calls it already makes).
- LLM/embedding token-usage tracking (`llm_usage` table): every
  `safe_invoke_llm_response`/`post_process`/embedding call now records
  provider, model, and token counts — embedding calls were previously
  invisible to any usage/cost accounting entirely.
- Embedding requests are now chunked to stay under a 250k-token budget
  (`tiktoken`) instead of one call per ingest batch.

### Fixed
- **Prod incident**: a large sync's changed sections were sent to the
  embeddings API in a single call, exceeding OpenAI's 300k-token
  per-request cap and failing the *entire* embedding step at once —
  every section in that sync silently lost its embedding. Fixed by the
  chunking above; a single oversized input is truncated at a token
  boundary rather than crashing the batch.
- `pgvector` retrieval had no `flag` filter, letting a `bookmark`-flagged
  search pull in `history` rows (and vice versa) — combined-search result
  inflation/duplication.
- `unlink` on an already-solo browser was a silent no-op that just
  created an orphaned empty account — now rejected (`AlreadySolo`, 400).
- `page-counts`/attribution used `source_browser_uuid` (insert-only) to
  answer "is my data synced," which undercounted any page a *different*
  linked browser had originally contributed — fixed by introducing the
  separate `last_synced_browser_uuid` column instead of overloading one
  column for two different questions.
- `GET /v1/sync/status` and `GET /v1/recent-searches` → `POST` (same MV3
  service-worker missing-`Origin`-header issue already fixed elsewhere).

## 2026-08-28 — Postgres/pgvector storage, cross-browser sync, privacy endpoints

### Added
- Persisted Postgres + pgvector storage (`pages` / `page_sections` /
  `section_embeddings`), replacing per-request in-memory FAISS. Retrieval
  now runs a hybrid BM25 (Redis-cached corpus) + pgvector (persisted)
  search, merged and re-ranked.
- Heading-scoped section chunking: a page's sections are stored and
  retrieved individually, not as one flat blob — a query matching one
  heading doesn't pull in a page's unrelated sections.
- Upsert-by-key ingestion with per-flag retention caps
  (`history_cap` / `bookmark_cap`, config-driven per environment). Only
  sections whose content actually changed get re-embedded on a re-sync.
- Cross-browser sync: `sync_accounts` / `users` / `sync_codes`, short-lived
  pairing codes, `GET /v1/sync/status`. All storage/retrieval scoped to
  the resolved `sync_account_id`, not the raw browser id, so paired
  browsers share one history/bookmark pool and cap.
- Recent search history (`SearchHistory`, `GET /v1/recent-searches`) —
  successful searches persisted after the response, not blocking it.
- Concurrent history + bookmark ingestion for combined `/save-data` calls
  (`asyncio.gather`, independent sessions) — roughly halves pre-search
  flush latency versus sequential ingestion.
- Data-deletion endpoints for the Settings privacy section:
  `DELETE /v1/user/history` (history only) and `DELETE /v1/user/data`
  (full reset — history, bookmarks, search history, matching Redis cache;
  account/tier/paired-browser links persist).
- `alembic` migrations (`migrations/versions/0001`-`0006`) and
  `docker-compose.yml` for a local pgvector Postgres instance.
- Load-testing tooling (`load_tests/`, local-only): Locust scenarios for
  search/ingestion/sync-pairing concurrency, a targeted sync
  race-condition script, and a CSV-to-terminal-table result renderer.
  `scripts/cleanup_test_data.py` (tracked, deployable) removes everything
  those tools create, identified by a `loadtest-` identity prefix.
- `.github/workflows/staging.yml` for a separate staging deploy target
  (own systemd unit, own branch).

### Fixed
- Bookmark `heading_path` defaulted to the tab title, which drifts
  (notification badges, live page state) — each drift missed the
  `(page_id, heading_path_hash)` upsert conflict target and inserted a new
  orphaned section instead of updating in place, causing unbounded row
  accumulation and near-total re-embedding on every sync. Bookmarks
  without real extracted heading data now fall back to a stable constant
  instead.
- A too-low `bookmark_cap` relative to real bookmark counts caused the
  same symptom by a different path: cap eviction deleted and immediately
  recreated pages every sync, permanently defeating change-detection for
  the evicted set.
- Combined search (`flag=combined`) always returned "No data found" —
  it read from Redis keys (`:ch`/`:cb`) that only a combined-flagged
  *save* ever wrote, while the extension syncs history and bookmarks as
  two separate calls. Combined search now reads the same `:history`/
  `:bookmark` keys a plain sync already populates.
- Sync code double-redemption race: two simultaneous redemptions of one
  code could both succeed (select-then-update, not atomic). Redemption is
  now a single atomic `UPDATE ... WHERE used = false ... RETURNING`.
- Sync code rate-limit TOCTOU race: concurrent `generate-code` calls could
  all pass the count check before any committed, overshooting the hourly
  cap. Now serialized per-account via a Postgres advisory lock.
- A hardcoded "Nothing matched in the bookmarks..." message in the shared
  history/bookmark streaming search handler fired regardless of which
  flag was actually searched.

### Changed
- `EmbeddingsProvider`/`LLMProvider` are fully settings-driven
  (`config/params.dev.yml` / `params.prod.yml` via
  `src/utility/settings.py`, the single entry point for runtime config) —
  no more hardcoded model names or scattered YAML reads.
