# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This backend didn't track changes before this file existed — the first
entry covers everything landed in the initial Postgres migration commit,
not a single day's work.

## upcoming
- sensitive data protection

## 2026-11-14 — Fast mode, clear-history ranges, prod retrieval fixes

### Added
- **Fast mode**: `mode: "fast"` on `POST /v1/search-stream` — retrieval
  only (BM25 + pgvector, same hybrid pipeline as Standard), no LLM calls
  at all. Results are filtered by a named strictness preset
  (`fast_strictness`: `"broad"`/`"balanced"`/`"precise"`, default
  `"balanced"`) against a floor on embedding similarity instead of an LLM
  judge — a result with no computed similarity (a BM25-only hit outside
  pgvector's own top-k) is dropped rather than shown unverified.
  `max_results` (clamped 1-10) and an unrecognized/missing preset name
  both fall back cleanly, never a 422. New response shape
  (`mode`/`results`/`no_match`/`fast_strictness`) over the existing SSE
  envelope — no new endpoint. `search_history` gained `mode`/
  `fast_strictness` columns so Recent Searches can tag and replay a fast
  search with the same preset it used. Benchmarked at ~13.8x faster than
  Standard on 15 real queries against real local data (~615ms vs
  ~8,492ms average) — see `docs/task_and_plans/fast_mode_benchmark.md`.
- `DELETE /v1/user/history` gained `?range=1h|24h|7d|30d|all` (default
  `24h`, matching today's behavior) — scopes the delete to history
  visited within that window via `Page.visited_at` instead of always
  wiping everything. `"all"` is the original full-wipe behavior, now
  reachable by name instead of only by omitting a cutoff entirely.
- Admin: `/status/search-metrics` now groups by `mode` as well as `flag`,
  with unpaginated `totalSearches`/`fastModeSearches`/`fastModeUsers`
  totals — lets Fast mode's actual latency and adoption be read directly
  instead of blended into one average. `/accounts/{id}/searches` now
  also surfaces `mode`/`fastStrictness` per row (was missing them despite
  the columns existing — see Fixed).
- Every completed `/search-stream` call (either mode) logs one
  `search-stream duration: mode=... flag=... duration_ms=...` line for a
  quick latency comparison without waiting on `search_history` to
  accumulate rows.
- Version bumped to `1.81.0`.

### Fixed
- **Prod incident**: `/search`/`/search-stream` fully depended on the
  Redis-cached corpus being non-empty before even attempting pgvector —
  in a multi-browser account, each `/save-data` call wholesale-overwrites
  the shared Redis cache key with just that browser's payload, so
  whichever browser synced most recently "won" the cache slot and every
  other linked browser's search silently lost pgvector access until it
  resynced too (reported as "sync coverage says fully synced, but search
  finds nothing"). `retrieve_parents` now always runs pgvector against
  Postgres regardless of Redis state.
- A bookmark moved to a new folder kept its *old* embedding indefinitely
  — re-embed detection only compared `content`, never `folder`/`title`/
  `domain`, even though sparse bookmarks embed exactly those fields.
  Compounded by the relevance judge never being shown a result's folder
  at all, so even a correctly folder-matched retrieval got rejected as
  irrelevant. Both fixed: folder/title/domain changes now trigger a
  re-embed, and the judge's prompt includes folder as valid identifying
  evidence for a sparse bookmark.

## 2026-10-11 — Named linked browsers, bookmark folder search, tier-split retention, versioning

### Added
- Named linked browsers: `users.device_name`/`linked_at`/`last_synced_at`.
  `generate-code`/`redeem-code` accept an optional `device_name`;
  `POST /v1/sync/devices` lists every browser in the account,
  `/devices/rename` renames any of them (not only the current one —
  fixing a device you aren't sitting at), `/devices/unlink` remotely
  detaches one (e.g. a lost/sold device), reusing the existing `unlink`
  logic. Cross-browser search results now also carry the source
  browser's `metadata.device_name`, falling back to `null` when unset.
  Name validation trims/collapses whitespace, strips control characters,
  and truncates at 40 chars rather than rejecting.
- Bookmark-only folder-scoped search: `SearchRequest.folder` restricts
  retrieval (both pgvector and the BM25 corpus) to a given folder path
  and everything nested under it (prefix match on the existing
  `" / "`-delimited `Page.folder`, e.g. `"Bookmarks bar / Work"` also
  matches `"Bookmarks bar / Work / Reading"`) — no schema change needed,
  `folder` was already persisted per bookmark. Ignored for
  `flag="history"`; scopes only the bookmark leg of a `flag="combined"`
  search.
- `POST /v1/sync/page-counts` now also returns account-wide totals
  (`history_total`/`bookmark_total`, every paired browser combined) and
  the account's resolved caps (`history_cap`/`bookmark_cap`), so the
  extension can tell "behind my other devices" apart from "account is at
  its retention cap" without hardcoding cap values client-side.
- `GET /v1/admin/accounts/{id}/searches` — paginated per-account recent
  searches (query/answer/sources/timing), for retrieval-quality review in
  the admin console.
- Tier-split `history_cap` (free=100, matching the extension's own local
  retention window; pro=500, unchanged) and `bookmark_cap` lowered from
  500 to 250 (flat — no real "pro" tier is reachable yet).
- Backend semantic versioning, starting at `1.80.1`/independent of the
  frontend's own version — read live from `pyproject.toml`, exposed on
  `/health` as `version`.
- `Makefile` wrapping the setup/run/lint commands already documented in
  `CLAUDE.md`.

### Fixed
- **Prod incident**: `systemctl` resolved fine over SSH but failed inside
  gunicorn's own process environment on staging (PATH-resolution
  difference, not a missing binary) — `status/health`'s service checks
  now resolve `systemctl`'s absolute path once at import time
  (`shutil.which` + standard-path fallback) instead of trusting a bare
  command name.
- A reported "Sync coverage" discrepancy (`100 local · 106 synced`,
  flagged as out-of-sync) was expected behavior given a flat `history_cap`
  of 500 versus the extension's own 100-item local window — resolved by
  the tier-split cap above, not a retrieval/counting bug.

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
