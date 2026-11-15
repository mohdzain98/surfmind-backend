# Categorization — how it works

Opt-in, LLM-assigned categories for a user's browsing data (`Work`,
`Shopping`, `Learning`, `Entertainment` by default, plus custom
categories up to a tier's limit). Backend source: `category_controller.py`
(routes), `category_service/category.py` (CRUD + enable/disable),
`classification_service/tasks.py` (the actual classification work),
`src/celery_app.py` (the Celery app it runs on).

## Scope today: history only

No real "pro" tier exists yet to gate bookmark categorization behind, so
rather than offer it to everyone for free, **only history pages are ever
classified** — bookmarks are excluded from every categorization query
(classification targets, the categorized-pages view, search-category
analytics). This is a deliberate current limitation, not a bug — see
`src/services/classification_service/tasks.py` and
`src/services/category_service/category.py` for the exact `flag ==
"history"` filters.

## When a page actually gets categorized

This is the part that trips people up: **ingestion never triggers
classification.** A page lands in Postgres via `/v1/save-data` with
`category_id = NULL` and stays that way indefinitely — there is no
automatic, per-sync, or background classification today. Something has
to explicitly ask for it.

### Free tier (today): on Settings open only

- The frontend calls `POST /v1/categories/classify` when the user opens
  Settings — nothing else calls it.
- If categorization isn't enabled for the account, this is a silent
  no-op (`{"status": "not_enabled"}`) — safe to call unconditionally.
- If enabled, it checks `count_unclassified_pages` (history-only). Zero
  unclassified pages → no-op (`{"status": "nothing_to_classify"}`).
  One or more → queues `classify_pages_task` on Celery and returns a
  `task_id` immediately; the frontend polls
  `POST /v1/categories/classify-status` with that id to know when the
  async work is done.
- **Consequence**: a newly-visited page sits uncategorized until the
  user *next opens Settings* — however long that takes. There's no
  periodic sweep checking for it in the background.

### Pro tier (planned, not built yet): periodic re-classification

The plan is for pro accounts to get this handled automatically —
re-classification runs on a schedule instead of depending on the user
opening Settings, so newly-synced pages get categorized promptly without
needing that manual trigger. **Not implemented** — there's no Celery
Beat schedule, no cron, no periodic task in this codebase today
(`src/celery_app.py` is explicitly trigger-only, no Beat setup). This
is the main gap to close once a real pro tier exists to gate it behind.

## End-to-end flow (free tier, today)

1. **Enable**: `POST /v1/categories/enable` flips
   `sync_accounts.categorization_enabled` on, seeds the four default
   categories (idempotent — re-enabling after a disable doesn't
   duplicate them), and immediately queues a first classification pass
   so the user sees results right away instead of waiting for a second
   Settings visit.
2. **Classify** (every later Settings open): `POST /v1/categories/classify`
   as described above.
3. **Celery task** (`classify_pages_task`, `classification_service/tasks.py`):
   pulls every unclassified history page (or *every* history page, if
   `reclassify_all=True`), builds a classification input per page
   (title + domain + folder + up to 2000 chars of concatenated section
   content), and calls `PageClassifier` — Jev primary, Gemini fallback —
   once per page. A single page's total classification failure (both
   Jev and the fallback down) is logged and skipped, not allowed to sink
   the rest of the batch; the commit happens once at the end.
4. **Status**: `POST /v1/categories/classify-status` with the `task_id`
   returns Celery's own `status`/`ready` — the frontend polls this to
   know when to refresh its view.
5. **Reading results**: `POST /v1/categories/list` (enabled flag +
   category list), `POST /v1/categories/pages` (every history page
   grouped by category, uncategorized pages in their own bucket),
   `POST /v1/categories/search-analytics` (which categories past
   searches' matched sources fall into — "what is this user searching
   more").
6. **Disable**: `POST /v1/categories/disable` only flips the flag off —
   categories and every page's `category_id` survive, so re-enabling
   later picks up exactly where it left off, no data loss either way.

## Admin visibility

`GET /v1/admin/status/stats` includes `categorization_enabled_accounts`
— how many accounts have the feature turned on at all (adoption of the
feature as a whole, not split by flag, since there's only one mode
today). See `docs/task_and_plans/admin_api.md` for the full field list
(gitignored, not checked in — ask for a copy if needed outside this
repo).

## Running it locally

Celery needs its own worker process — `make celery` (uses `--pool=solo`;
macOS's `multiprocessing` defaults to `spawn`, which breaks Celery's
`prefork` pool, so `solo` is the standard local-dev workaround; the
`deploy/` systemd units don't need this, Linux's `fork` doesn't hit it).
Broker/result backend is the same Redis instance the app already uses —
no new infra.
