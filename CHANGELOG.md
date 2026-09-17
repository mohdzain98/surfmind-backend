# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This backend didn't track changes before this file existed — the first
entry covers everything landed in the initial Postgres migration commit,
not a single day's work.

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
