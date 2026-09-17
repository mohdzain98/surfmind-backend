# Contributing

## Setup

See `README.md` for environment setup, `.env`, Postgres, and migrations.

## Code Style

- **Type hints** on every function/method signature.
- **Docstrings**: module-level 4-5 lines, class-level 3-4 lines,
  method/function-level 2-3 lines. Keep inline comments short and
  non-narrative — only where the *why* isn't obvious from the code itself
  (a hidden constraint, a workaround, a non-obvious invariant), not
  restating what the code already says.
- Format and lint before committing:

  ```bash
  black .
  ruff check .
  ```

  Config lives in the root `pyproject.toml` (line length 88, Python 3.11
  target, ruff rules `E`, `F`, `I`).

- When touching an existing file, bring the specific function/class you're
  editing into style compliance — not a drive-by reformat of the whole
  file.

## Database Changes

- Every schema change is an Alembic migration under `migrations/versions/`,
  numbered sequentially after the last one (`alembic revision --autogenerate
  -m "..."`, then review the generated file — autogenerate doesn't always
  get constraints/indexes right).
- Test migrations against a real local Postgres before merging
  (`docker compose up -d`, `alembic upgrade head`) — this repo has no
  migration test suite, so this is the only verification.
- All storage/retrieval is scoped to the resolved `sync_account_id`
  (`src/services/sync_service/sync.py::resolve_sync_account_id`), never a
  raw `browser_uuid` directly — a schema or query that keys off the wrong
  identity silently breaks cross-browser sync.

## Testing

There is no unit test suite in this repo currently. `load_tests/`
(gitignored, local-only) has Locust scenarios and a targeted
race-condition script for load/concurrency testing — see
`docs/task_and_plans/load_testing.md`. Verify changes manually against a
local server and Postgres/Redis before opening a PR.

## Branching & Deployment

- `main` deploys to production on push (`.github/workflows/main.yml`).
- `staging` deploys to the staging server on push
  (`.github/workflows/staging.yml`).
- Both restart their own systemd unit (`surfmind.service` /
  `surfmind-staging.service`) and run `alembic upgrade head` as part of
  deploy — a schema change won't take effect without a successful
  migration run, so confirm it applies cleanly before pushing to either
  branch.

## Commits

- Focus commit messages on *why*, not a restatement of the diff.
- Don't force-push or rewrite history on `main` or `staging` — both are
  live deploy targets.
