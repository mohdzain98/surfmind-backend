# Full Execution Flow

```mermaid
flowchart TD
  dir_src_services_task_detection_service["src/services/task_detection_service<br/>1 file"]
  dir_src_utility["src/utility<br/>8 files"]
  dir_src_services_core_service["src/services/core_service<br/>3 files"]
  dir_src_services_ingestion_service["src/services/ingestion_service<br/>1 file"]
  dir_src_services_search_history_service["src/services/search_history_service<br/>1 file"]
  dir_src_services_post_processing_service["src/services/post_processing_service<br/>1 file"]
  dir_src_db["src/db<br/>3 files"]
  dir_src_services_admin_service["src/services/admin_service<br/>1 file"]
  dir_src_controller["src/controller<br/>4 files"]
  dir_src_services_privacy_service["src/services/privacy_service<br/>1 file"]
  dir_src_services_llm_service["src/services/llm_service<br/>2 files"]
  dir_src_handlers_mappers["src/handlers/mappers<br/>5 files"]
  dir_src_models["src/models<br/>2 files"]
  dir_src_handlers["src/handlers<br/>2 files"]
  dir_src_services_sync_service["src/services/sync_service<br/>1 file"]
  dir_src_controller -->|2| dir_src_handlers
  dir_src_controller -->|3| dir_src_models
  dir_src_controller --> dir_src_services_admin_service
  dir_src_controller --> dir_src_services_core_service
  dir_src_controller --> dir_src_services_ingestion_service
  dir_src_controller -->|2| dir_src_services_privacy_service
  dir_src_controller --> dir_src_services_search_history_service
  dir_src_controller -->|3| dir_src_services_sync_service
  dir_src_handlers -->|2| dir_src_handlers_mappers
  dir_src_services_core_service -->|2| dir_src_models
  dir_src_services_core_service -->|3| dir_src_services_llm_service
  dir_src_services_core_service --> dir_src_services_post_processing_service
  dir_src_services_core_service --> dir_src_services_sync_service
  dir_src_services_core_service --> dir_src_services_task_detection_service
  dir_src_services_ingestion_service -->|2| dir_src_models
  dir_src_services_ingestion_service -->|2| dir_src_services_llm_service
  dir_src_services_post_processing_service --> dir_src_models
  dir_src_services_post_processing_service --> dir_src_services_llm_service
  dir_src_services_sync_service --> dir_src_services_ingestion_service
  dir_src_services_task_detection_service --> dir_src_services_llm_service
```

> Grouped by folder to stay readable: 15 folders; numbers on arrows count the file-level imports they stand for.
> Arrows into `src/db`, `src/utility` are not drawn: most folders import them, and drawing every arrow would hide the structure.

# Detail by folder

The diagram above groups files by folder. These show the files inside the biggest folders.

## `src/utility` (8 files)

```mermaid
flowchart TD
  src_utility_db_log_handler_py["src/utility/db_log_handler.py"]
  src_utility_logger_py["src/utility/logger.py"]
  src_utility_path_finder_py["src/utility/path_finder.py"]
  src_utility_provider_py["src/utility/provider.py"]
  src_utility_settings_py["src/utility/settings.py"]
  src_utility_token_usage_callback_py["src/utility/token_usage_callback.py"]
  src_utility_utils_py["src/utility/utils.py"]
  src_utility_db_log_handler_py --> src_utility_settings_py
  src_utility_logger_py -.-> src_utility_db_log_handler_py
  src_utility_logger_py --> src_utility_settings_py
  src_utility_path_finder_py --> src_utility_logger_py
  src_utility_provider_py --> src_utility_logger_py
  src_utility_provider_py --> src_utility_path_finder_py
  src_utility_provider_py --> src_utility_settings_py
  src_utility_token_usage_callback_py --> src_utility_logger_py
  src_utility_utils_py --> src_utility_logger_py
  src_utility_utils_py --> src_utility_path_finder_py
```

> Dotted arrows: imports that do not run when the module loads.

## `src/handlers/mappers` (5 files)

```mermaid
flowchart TD
  src_handlers_mappers___init___py["src/handlers/mappers/__init__.py"]
  src_handlers_mappers_base_mapper_py["src/handlers/mappers/base_mapper.py"]
  src_handlers_mappers_gemini_mapper_py["src/handlers/mappers/gemini_mapper.py"]
  src_handlers_mappers_openai_mapper_py["src/handlers/mappers/openai_mapper.py"]
  src_handlers_mappers_redis_mapper_py["src/handlers/mappers/redis_mapper.py"]
  src_handlers_mappers___init___py --> src_handlers_mappers_base_mapper_py
  src_handlers_mappers___init___py --> src_handlers_mappers_gemini_mapper_py
  src_handlers_mappers___init___py --> src_handlers_mappers_openai_mapper_py
  src_handlers_mappers___init___py --> src_handlers_mappers_redis_mapper_py
  src_handlers_mappers_gemini_mapper_py --> src_handlers_mappers_base_mapper_py
  src_handlers_mappers_openai_mapper_py --> src_handlers_mappers_base_mapper_py
  src_handlers_mappers_redis_mapper_py --> src_handlers_mappers_base_mapper_py
```

## `src/controller` (4 files)

```mermaid
flowchart TD
  src_controller_admin_controller_py["src/controller/admin_controller.py"]
  src_controller_core_controller_py["src/controller/core_controller.py"]
  src_controller_main_controller_py["src/controller/main_controller.py"]
  src_controller_sync_controller_py["src/controller/sync_controller.py"]
  src_controller_admin_controller_py --> src_controller_core_controller_py
  src_controller_main_controller_py --> src_controller_admin_controller_py
  src_controller_main_controller_py --> src_controller_core_controller_py
  src_controller_main_controller_py --> src_controller_sync_controller_py
```

## `src/db` (3 files)

```mermaid
flowchart TD
  src_db_base_py["src/db/base.py"]
  src_db_models_py["src/db/models.py"]
  src_db_models_py --> src_db_base_py
```

## `src/services/core_service` (3 files)

```mermaid
flowchart TD
  src_services_core_service_fast_search_py["src/services/core_service/fast_search.py"]
  src_services_core_service_main_py["src/services/core_service/main.py"]
  src_services_core_service_rag_py["src/services/core_service/rag.py"]
  src_services_core_service_main_py --> src_services_core_service_fast_search_py
  src_services_core_service_main_py --> src_services_core_service_rag_py
```

> ℹ️ This file renders the complete Mermaid diagram on GitHub.
> For raw Mermaid source, see [**FLOW-full.mmd**](./FLOW-full.mmd). Every file and import, ungrouped and nothing omitted: [**flow-complete.mmd**](./flow-complete.mmd)

---

<sub>Generated by [GNOST](https://gnost.readthedocs.io) 0.7.1. Try it on your own code: `uvx gnost onboard .`</sub>
