# surfmind-backend — Project Onboarding Guide

_Generated automatically by <a href='https://gnost.readthedocs.io'>GNOST</a>._

## Project Overview

- **Root:** `/Users/mohdzain/Documents/GitHub/surfmind/surfmind-backend`
- **Languages:** python (77)
- **Framework:** FastAPI

## Summary Table

| Language | Files | LOC |
|---|---:|---:|
| Python | 77 | 9435 |

## Stats Table

| Language | Files | Code | Comments | Blanks | LOC |
|---|---:|---:|---:|---:|---:|
| Python | 77 | 7607 | 433 | 1395 | 9435 |

## Get it running

_Read from this project's own files. Each line names its source; nothing is guessed._

**Prerequisites**

- Docker _(docker-compose.yml)_

**Install**

- `pip install -e .` _(pyproject.toml)_
- `make install` _(Makefile)_

**Run**

- `make run` _(Makefile)_
- `docker compose up` _(docker-compose.yml)_

**Test**

- `make check` _(Makefile)_

**Environment variables**

- OPENAI_API_KEY _(.env.example)_
- GEMINI_API_KEY _(.env.example)_
- TYPESAFE_API_KEY _(.env.example)_
- REDIS_HOST _(.env.example)_
- REDIS_PORT _(.env.example)_
- DATABASE_URL _(.env.example)_
- ENVIRONMENT _(.env.example)_
- DEBUG _(.env.example)_

## Entry Points

- `src/controller/main_controller.py` — FastAPI app initialization
- `scripts/cleanup_test_data.py` — __main__ guard
- `scripts/create_admin.py` — __main__ guard

## Routes

41 endpoints found. Each row is a URL and the code that handles it.

| Method | Path | Handler | File |
|---|---|---|---|
| GET | `/` | `root_health_check` | `src/controller/main_controller.py:76` |
| GET | `/health` | `health_check` | `src/controller/main_controller.py:82` |
| GET | `/v1/admin/accounts` | `list_accounts_route` | `src/controller/admin_controller.py:471` |
| DELETE | `/v1/admin/accounts/{sync_account_id}` | `admin_delete_account_route` | `src/controller/admin_controller.py:870` |
| GET | `/v1/admin/accounts/{sync_account_id}` | `account_detail_route` | `src/controller/admin_controller.py:666` |
| POST | `/v1/admin/accounts/{sync_account_id}/clear-data` | `admin_clear_data_route` | `src/controller/admin_controller.py:826` |
| GET | `/v1/admin/accounts/{sync_account_id}/searches` | `account_searches_route` | `src/controller/admin_controller.py:726` |
| POST | `/v1/admin/accounts/{sync_account_id}/unlink-browser` | `admin_unlink_browser_route` | `src/controller/admin_controller.py:793` |
| POST | `/v1/admin/login` | `login_route` | `src/controller/admin_controller.py:79` |
| GET | `/v1/admin/status/health` | `health_route` | `src/controller/admin_controller.py:89` |
| GET | `/v1/admin/status/llm-usage` | `llm_usage_route` | `src/controller/admin_controller.py:314` |
| GET | `/v1/admin/status/logs` | `logs_route` | `src/controller/admin_controller.py:258` |
| GET | `/v1/admin/status/nginx-logs` | `nginx_logs_route` | `src/controller/admin_controller.py:934` |
| GET | `/v1/admin/status/search-metrics` | `search_metrics_route` | `src/controller/admin_controller.py:388` |
| GET | `/v1/admin/status/stats` | `stats_route` | `src/controller/admin_controller.py:206` |
| POST | `/v1/admin/sync-codes/{code}/revoke` | `admin_revoke_sync_code_route` | `src/controller/admin_controller.py:851` |
| POST | `/v1/categories/classify` | `classify_route` | `src/controller/category_controller.py:214` |
| POST | `/v1/categories/classify-status` | `classify_status_route` | `src/controller/category_controller.py:236` |
| POST | `/v1/categories/create` | `create_category_route` | `src/controller/category_controller.py:119` |
| POST | `/v1/categories/disable` | `disable_route` | `src/controller/category_controller.py:201` |
| POST | `/v1/categories/enable` | `enable_route` | `src/controller/category_controller.py:184` |
| POST | `/v1/categories/list` | `list_categories_route` | `src/controller/category_controller.py:68` |
| POST | `/v1/categories/pages` | `list_categorized_pages_route` | `src/controller/category_controller.py:95` |
| POST | `/v1/categories/refresh` | `refresh_route` | `src/controller/category_controller.py:242` |
| POST | `/v1/categories/search-analytics` | `search_analytics_route` | `src/controller/category_controller.py:107` |
| DELETE | `/v1/categories/{category_id}` | `delete_category_route` | `src/controller/category_controller.py:170` |
| POST | `/v1/categories/{category_id}/update` | `update_category_route` | `src/controller/category_controller.py:146` |
| POST | `/v1/recent-searches` | `recent_searches_route` | `src/controller/core_controller.py:461` |
| POST | `/v1/save-data` | `save_data` | `src/controller/core_controller.py:170` |
| POST | `/v1/search` | `search` | `src/controller/core_controller.py:281` |
| POST | `/v1/search-stream` | `search_stream` | `src/controller/core_controller.py:327` |
| POST | `/v1/sync/devices` | `list_devices_route` | `src/controller/sync_controller.py:135` |
| POST | `/v1/sync/devices/rename` | `rename_device_route` | `src/controller/sync_controller.py:148` |
| POST | `/v1/sync/devices/unlink` | `unlink_device_route` | `src/controller/sync_controller.py:172` |
| POST | `/v1/sync/generate-code` | `generate_code_route` | `src/controller/sync_controller.py:46` |
| POST | `/v1/sync/page-counts` | `page_counts_route` | `src/controller/sync_controller.py:116` |
| POST | `/v1/sync/redeem-code` | `redeem_code_route` | `src/controller/sync_controller.py:64` |
| POST | `/v1/sync/status` | `sync_status_route` | `src/controller/sync_controller.py:95` |
| POST | `/v1/sync/unlink` | `unlink_route` | `src/controller/sync_controller.py:83` |
| DELETE | `/v1/user/data` | `clear_all_data_route` | `src/controller/core_controller.py:524` |

_...and 1 more; the full list is in the insights JSON (`--json`)._

## Execution Flow (High Level)

- `src/controller/main_controller.py` → `src/controller/sync_controller.py`
- `src/controller/main_controller.py` → `src/utility/db_log_handler.py`
- `src/controller/main_controller.py` → `src/utility/logger.py`
- `src/controller/main_controller.py` → `src/utility/settings.py`
- `src/controller/main_controller.py` → `src/controller/admin_controller.py` → `src/models/core.py`

_(21 additional paths omitted for clarity.)_

## Function-level Flow

What each entry point calls, function by function (Python only; calls through other objects such as `self.client.send()` are not followed). Full diagrams: [function-flow.md](flow/function-flow.md).

### `POST /v1/save-data` → `save_data`

`src/controller/core_controller.py:170`

- `_default_heading_path` (`src/services/ingestion_service/ingestion.py:97`)
- `resolve_sync_account_id` (`src/services/sync_service/sync.py:120`)
- `_persist_embeddings` (`src/controller/core_controller.py:134`)
  - `_ingest_with_own_session` (`src/controller/core_controller.py:109`)
    - `ingest_batch` (`src/services/ingestion_service/ingestion.py:377`)
      - _..._
  - `ingest_batch` (`src/services/ingestion_service/ingestion.py:377`) _(shown above)_

### `POST /v1/categories/enable` → `enable_route`

`src/controller/category_controller.py:184`

- `resolve_sync_account_id` (`src/services/sync_service/sync.py:120`)
- `enable_categorization` (`src/services/category_service/category.py:89`)
  - `is_categorization_enabled` (`src/services/category_service/category.py:60`)
  - `_create_default_categories` (`src/services/category_service/category.py:69`)
- `classify_pages_task` (`src/services/classification_service/tasks.py:173`)
  - `_run_and_dispose` (`src/services/classification_service/tasks.py:155`)
    - `classify_pages_async` (`src/services/classification_service/tasks.py:87`)
      - _..._

### `POST /v1/categories/refresh` → `refresh_route`

`src/controller/category_controller.py:242`

- `resolve_sync_account_id` (`src/services/sync_service/sync.py:120`)
- `is_categorization_enabled` (`src/services/category_service/category.py:60`)
- `get_refresh_available_at` (`src/services/category_service/category.py:118`)
- `refresh_categorization` (`src/services/category_service/category.py:141`)
- `classify_pages_task` (`src/services/classification_service/tasks.py:173`)
  - `_run_and_dispose` (`src/services/classification_service/tasks.py:155`)
    - `classify_pages_async` (`src/services/classification_service/tasks.py:87`)
      - _..._

### `POST /v1/categories/classify` → `classify_route`

`src/controller/category_controller.py:214`

- `resolve_sync_account_id` (`src/services/sync_service/sync.py:120`)
- `is_categorization_enabled` (`src/services/category_service/category.py:60`)
- `count_unclassified_pages` (`src/services/classification_service/tasks.py:35`)
- `classify_pages_task` (`src/services/classification_service/tasks.py:173`)
  - `_run_and_dispose` (`src/services/classification_service/tasks.py:155`)
    - `classify_pages_async` (`src/services/classification_service/tasks.py:87`)
      - _..._

### `POST /v1/sync/redeem-code` → `redeem_code_route`

`src/controller/sync_controller.py:64`

- `redeem_code` (`src/services/sync_service/sync.py:307`)
  - `_migrate_browser_pages` (`src/services/sync_service/sync.py:254`)
  - `_get_account_tier` (`src/services/ingestion_service/ingestion.py:209`)
  - `_trim_to_cap` (`src/services/ingestion_service/ingestion.py:561`)
    - `_cap_for` (`src/services/ingestion_service/ingestion.py:89`)
  - `_set_sync_account` (`src/services/sync_service/sync.py:155`)
  - `_apply_device_metadata` (`src/services/sync_service/sync.py:92`)
    - `_normalize_device_name` (`src/services/sync_service/sync.py:72`)

_...and 20 more entry points in the insights JSON (`--json`)._

## Execution Flow (Overview)

```mermaid
flowchart TD
  dir_src_utility["src/utility<br/>6 files"]
  dir_src_controller["src/controller<br/>5 files"]
  dir_src_services_core_service["src/services/core_service<br/>3 files"]
  dir_src_services_search_history_service["src/services/search_history_service<br/>1 file"]
  dir_src_services_category_service["src/services/category_service<br/>1 file"]
  dir_src_db["src/db<br/>2 files"]
  dir_src_services_llm_service["src/services/llm_service<br/>2 files"]
  dir_src_handlers_mappers["src/handlers/mappers<br/>4 files"]
  dir_src_services_sync_service["src/services/sync_service<br/>1 file"]
  dir_src_services_admin_service["src/services/admin_service<br/>1 file"]
  dir_src_services_post_processing_service["src/services/post_processing_service<br/>1 file"]
  dir_src_handlers["src/handlers<br/>2 files"]
  dir_src_services_ingestion_service["src/services/ingestion_service<br/>1 file"]
  dir_src_services_classification_service["src/services/classification_service<br/>2 files"]
  dir_src_services_privacy_service["src/services/privacy_service<br/>1 file"]
  dir_src["src<br/>1 file"]
  dir_src_controller --> dir_src
  dir_src_controller -->|2| dir_src_handlers
  dir_src_controller --> dir_src_services_admin_service
  dir_src_controller -->|2| dir_src_services_category_service
  dir_src_controller --> dir_src_services_classification_service
  dir_src_controller --> dir_src_services_core_service
  dir_src_controller --> dir_src_services_ingestion_service
  dir_src_controller -->|2| dir_src_services_privacy_service
  dir_src_controller --> dir_src_services_search_history_service
  dir_src_controller -->|4| dir_src_services_sync_service
  dir_src_handlers -->|2| dir_src_handlers_mappers
  dir_src_services_classification_service --> dir_src
  dir_src_services_classification_service --> dir_src_services_category_service
  dir_src_services_classification_service -->|2| dir_src_services_llm_service
  dir_src_services_core_service -->|3| dir_src_services_llm_service
  dir_src_services_core_service --> dir_src_services_post_processing_service
  dir_src_services_core_service --> dir_src_services_sync_service
  dir_src_services_ingestion_service -->|2| dir_src_services_llm_service
  dir_src_services_post_processing_service --> dir_src_services_llm_service
  dir_src_services_sync_service --> dir_src_services_ingestion_service
```

> Grouped by folder to stay readable: 16 folders; numbers on arrows count the file-level imports they stand for.
> Arrows into `src/db`, `src/utility` are not drawn: most folders import them, and drawing every arrow would hide the structure.

> 📌 This diagram shows the high-level execution flow.<br>For the complete flow, see [**flow/flow-full.md**](./flow/FLOW-full.md)<br>Raw Mermaid: [flow/flow-full.mmd](./flow/FLOW-full.mmd)<br>Every file and import, ungrouped (for tools and AI): [flow/flow-complete.mmd](./flow/flow-complete.mmd)<br>Interactive explorer: run `gnost open flow` (the page is `flow.html` in this folder; it is rebuilt, not committed)

## Recommended Reading Order

### Start Here

- `src/controller/main_controller.py`

### Core Logic

- `src/controller/admin_controller.py`
- `src/controller/category_controller.py`
- `src/controller/core_controller.py`
- `src/controller/sync_controller.py`
- `src/db/session.py`
- `src/utility/db_log_handler.py`
- `src/utility/logger.py`
- `src/celery_app.py`
- `src/db/models.py`
- `src/handlers/llm_exception_handler.py`
- `src/handlers/redis_exception_handler.py`
- `src/services/admin_service/admin.py`
- `src/services/category_service/category.py`
- `src/services/classification_service/tasks.py`
- `src/services/core_service/main.py`
- _...and 18 more (closest to an entry point listed first)_

### Supporting / Leaf Code

- `src/utility/settings.py`
- `src/models/core.py`
- `src/utility/pricing.py`
- `src/db/base.py`
- `src/models/ai_models.py`
- `src/handlers/mappers/base_mapper.py`

## 📘 First Files to Read
- **`src/controller/main_controller.py`**
  - Primary entry point into the application
- **`src/controller/core_controller.py`**
  - Core logic file referenced by multiple execution paths
- **`src/controller/admin_controller.py`**
  - Core logic file referenced by multiple execution paths
- **`src/controller/category_controller.py`**
  - Core logic file referenced by multiple execution paths
- **`src/services/core_service/main.py`**
  - Core logic file referenced by multiple execution paths
- **`scripts/cleanup_test_data.py`**
  - Primary entry point into the application
- **`scripts/create_admin.py`**
  - Primary entry point into the application
- **`src/services/classification_service/tasks.py`**
  - Core logic file referenced by multiple execution paths
- **`src/services/ingestion_service/ingestion.py`**
  - Core logic file referenced by multiple execution paths
- **`src/controller/sync_controller.py`**
  - Core logic file referenced by multiple execution paths

## ⚠️ Caution Areas
### `src/controller/admin_controller.py`
- **Type:** large_file
- **Severity:** 4
- **Caution score:** 76.4/100
- 849 lines of code; 8 except blocks that neither log nor re-raise; imports 11 project files
### `src/services/ingestion_service/ingestion.py`
- **Type:** high_complexity
- **Severity:** 4
- **Caution score:** 70.9/100
- A function with complexity 25; 508 lines of code; 3 except blocks that neither log nor re-raise
### `src/utility/settings.py`
- **Type:** high_impact
- **Severity:** 3
- **Caution score:** 51.5/100
- Imported by 20 files; 251 lines of code
### `src/services/core_service/rag.py`
- **Type:** large_file
- **Severity:** 3
- **Caution score:** 46.1/100
- 596 lines of code; a function with complexity 15
### `src/utility/logger.py`
- **Type:** high_impact
- **Severity:** 3
- **Caution score:** 43.1/100
- Imported by 18 files
### `src/services/sync_service/sync.py`
- **Type:** large_file
- **Severity:** 3
- **Caution score:** 42.2/100
- 602 lines of code; 2 except blocks that neither log nor re-raise; imported by 5 files

## Change Hotspots

Files that changed most in the last 365 days (57 commits). A file that changes often and is touched by many people is where merge conflicts and regressions tend to start.

| File | Commits | Authors | Last 90 days | Lines changed | Last change |
|---|---:|---:|---:|---|---|
| `src/controller/core_controller.py` | 17 | 1 | 13 | +668 / -121 | 2026-11-13 |
| `src/models/core.py` | 13 | 1 | 10 | +380 / -7 | 2026-11-15 |
| `src/services/core_service/main.py` | 11 | 1 | 8 | +733 / -81 | 2026-11-12 |
| `src/controller/main_controller.py` | 10 | 1 | 7 | +116 / -18 | 2026-11-14 |
| `src/services/core_service/rag.py` | 10 | 1 | 7 | +827 / -169 | 2026-11-12 |
| `src/controller/admin_controller.py` | 9 | 1 | 9 | +984 / -23 | 2026-11-15 |
| `src/db/models.py` | 9 | 1 | 9 | +376 / -0 | 2026-11-15 |
| `src/services/ingestion_service/ingestion.py` | 9 | 1 | 9 | +654 / -23 | 2026-11-04 |
| `src/services/sync_service/sync.py` | 9 | 1 | 9 | +751 / -44 | 2026-10-11 |
| `src/utility/settings.py` | 8 | 1 | 8 | +311 / -6 | 2026-11-15 |
| `src/controller/sync_controller.py` | 6 | 1 | 6 | +215 / -19 | 2026-10-11 |
| `src/services/post_processing_service/post_processing.py` | 6 | 1 | 3 | +180 / -26 | 2026-11-04 |
| `src/utility/logger.py` | 6 | 1 | 3 | +256 / -52 | 2026-09-18 |
| `src/services/category_service/category.py` | 5 | 1 | 5 | +414 / -14 | 2026-11-15 |
| `src/services/privacy_service/privacy.py` | 4 | 1 | 4 | +84 / -8 | 2026-11-13 |

## Risky and Changing

Files that are fragile to change (high caution score) and also change often. Start here when adding tests or reviewing changes. Risk = caution score scaled by how much the file changes.

| File | Risk | Caution | Change activity | Why fragile | Commits | Authors |
|---|---:|---:|---:|---|---:|---:|
| `src/controller/admin_controller.py` | 58.1 | 76.4 | 76.1 | large file, errors swallowed silently | 9 | 1 |
| `src/services/ingestion_service/ingestion.py` | 54 | 70.9 | 76.1 | complex code, large file | 9 | 1 |
| `src/utility/settings.py` | 35.6 | 51.5 | 69.2 | many files depend on it, large file | 8 | 1 |
| `src/services/core_service/rag.py` | 35.1 | 46.1 | 76.1 | large file, complex code | 10 | 1 |
| `src/services/sync_service/sync.py` | 32.1 | 42.2 | 76.1 | large file, errors swallowed silently | 9 | 1 |
| `src/services/core_service/main.py` | 28.7 | 35.6 | 80.5 | large file, imports many files | 11 | 1 |
| `src/controller/core_controller.py` | 27.5 | 30.6 | 90 | large file, imports many files | 17 | 1 |
| `src/db/models.py` | 26.5 | 34.8 | 76.1 | many files depend on it, large file | 9 | 1 |
| `src/utility/logger.py` | 24.9 | 43.1 | 57.7 | many files depend on it | 6 | 1 |

## 🔁 Circular Dependencies

_No circular dependencies detected._
## Key Execution Paths

To understand specific scenarios, see the entry-based execution paths:

- 📍 [Entry-based Paths](flow/entry-paths.md)

- 🧭 [folder-based Paths](flow/folder-paths.md)

(Whole system: [flow/FLOW-full.md](flow/FLOW-full.md). For a small project it is the same as [flow/flow-complete.mmd](flow/flow-complete.mmd), every file and import; for a big one FLOW-full groups them by folder to stay readable. Interactive: `gnost open flow`.)

---

<sub>Generated by [GNOST](https://gnost.readthedocs.io) 0.7.0. Try it on your own code: `uvx gnost onboard .`</sub>
