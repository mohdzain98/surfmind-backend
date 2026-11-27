# Function-level Flow

What each entry point calls, function by function (Python only). Dotted arrows lead to a function already drawn elsewhere in the same diagram. Calls through other objects (`self.client.send()`) are not followed.

## `POST /v1/save-data` → `save_data`

`src/controller/core_controller.py:174` · 26 functions · cut short

```mermaid
flowchart LR
  src_controller_core_controller_py__save_data["save_data<br/>src/controller/core_controller.py"]
  src_services_ingestion_service_ingestion_py___default_heading_path["_default_heading_path<br/>src/services/ingestion_service/ingestion.py"]
  src_services_sync_service_sync_py__resolve_sync_account_id["resolve_sync_account_id<br/>src/services/sync_service/sync.py"]
  src_controller_core_controller_py___persist_embeddings["_persist_embeddings<br/>src/controller/core_controller.py"]
  src_controller_core_controller_py___ingest_with_own_session["_ingest_with_own_session<br/>src/controller/core_controller.py"]
  src_services_ingestion_service_ingestion_py__ingest_batch["ingest_batch<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___dedupe_sections["_dedupe_sections<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___group_by_url["_group_by_url<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___hash_url["_hash_url<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___upsert_pages["_upsert_pages<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___classify_page_type["_classify_page_type<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___parse_bookmark_visited_at["_parse_bookmark_visited_at<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___hash_heading_path["_hash_heading_path<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___get_account_tier["_get_account_tier<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___build_embedding_inputs["_build_embedding_inputs<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___embedding_input["_embedding_input<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___bookmark_embedding_text["_bookmark_embedding_text<br/>src/services/ingestion_service/ingestion.py"]
  src_services_llm_service_llm_provider_py__LLMProvider___init__["LLMProvider.__init__<br/>src/services/llm_service/llm_provider.py"]
  src_services_llm_service_prompt_builder_py__Prompts___init__["Prompts.__init__<br/>src/services/llm_service/prompt_builder.py"]
  src_services_ingestion_service_ingestion_py___summarize_section["_summarize_section<br/>src/services/ingestion_service/ingestion.py"]
  src_utility_provider_py__EmbeddingsProvider_get_default_embeddings["EmbeddingsProvider.get_default_embeddings<br/>src/utility/provider.py"]
  src_utility_provider_py__EmbeddingsProvider__build_embeddings["EmbeddingsProvider._build_embeddings<br/>src/utility/provider.py"]
  src_utility_provider_py__FallbackEmbeddings___init__["FallbackEmbeddings.__init__<br/>src/utility/provider.py"]
  src_services_ingestion_service_ingestion_py___chunk_by_token_budget["_chunk_by_token_budget<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___trim_to_cap["_trim_to_cap<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___cap_for["_cap_for<br/>src/services/ingestion_service/ingestion.py"]
  src_controller_core_controller_py___ingest_with_own_session --> src_services_ingestion_service_ingestion_py__ingest_batch
  src_controller_core_controller_py___persist_embeddings --> src_controller_core_controller_py___ingest_with_own_session
  src_controller_core_controller_py___persist_embeddings -.-> src_services_ingestion_service_ingestion_py__ingest_batch
  src_controller_core_controller_py__save_data --> src_controller_core_controller_py___persist_embeddings
  src_controller_core_controller_py__save_data --> src_services_ingestion_service_ingestion_py___default_heading_path
  src_controller_core_controller_py__save_data --> src_services_sync_service_sync_py__resolve_sync_account_id
  src_services_ingestion_service_ingestion_py___build_embedding_inputs --> src_services_ingestion_service_ingestion_py___bookmark_embedding_text
  src_services_ingestion_service_ingestion_py___build_embedding_inputs -.-> src_services_ingestion_service_ingestion_py___default_heading_path
  src_services_ingestion_service_ingestion_py___build_embedding_inputs --> src_services_ingestion_service_ingestion_py___embedding_input
  src_services_ingestion_service_ingestion_py___build_embedding_inputs --> src_services_ingestion_service_ingestion_py___summarize_section
  src_services_ingestion_service_ingestion_py___build_embedding_inputs --> src_services_llm_service_llm_provider_py__LLMProvider___init__
  src_services_ingestion_service_ingestion_py___build_embedding_inputs --> src_services_llm_service_prompt_builder_py__Prompts___init__
  src_services_ingestion_service_ingestion_py___dedupe_sections -.-> src_services_ingestion_service_ingestion_py___default_heading_path
  src_services_ingestion_service_ingestion_py___trim_to_cap --> src_services_ingestion_service_ingestion_py___cap_for
  src_services_ingestion_service_ingestion_py___upsert_pages --> src_services_ingestion_service_ingestion_py___classify_page_type
  src_services_ingestion_service_ingestion_py___upsert_pages -.-> src_services_ingestion_service_ingestion_py___hash_url
  src_services_ingestion_service_ingestion_py___upsert_pages --> src_services_ingestion_service_ingestion_py___parse_bookmark_visited_at
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___build_embedding_inputs
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___chunk_by_token_budget
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___dedupe_sections
  src_services_ingestion_service_ingestion_py__ingest_batch -.-> src_services_ingestion_service_ingestion_py___default_heading_path
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___get_account_tier
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___group_by_url
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___hash_heading_path
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___hash_url
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___trim_to_cap
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_services_ingestion_service_ingestion_py___upsert_pages
  src_services_ingestion_service_ingestion_py__ingest_batch --> src_utility_provider_py__EmbeddingsProvider_get_default_embeddings
  src_utility_provider_py__EmbeddingsProvider_get_default_embeddings --> src_utility_provider_py__EmbeddingsProvider__build_embeddings
  src_utility_provider_py__EmbeddingsProvider_get_default_embeddings --> src_utility_provider_py__FallbackEmbeddings___init__
```

## `POST /v1/sync/redeem-code` → `redeem_code_route`

`src/controller/sync_controller.py:68` · 9 functions

```mermaid
flowchart LR
  src_controller_sync_controller_py__redeem_code_route["redeem_code_route<br/>src/controller/sync_controller.py"]
  src_services_sync_service_sync_py__redeem_code["redeem_code<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___migrate_browser_pages["_migrate_browser_pages<br/>src/services/sync_service/sync.py"]
  src_services_ingestion_service_ingestion_py___get_account_tier["_get_account_tier<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___trim_to_cap["_trim_to_cap<br/>src/services/ingestion_service/ingestion.py"]
  src_services_ingestion_service_ingestion_py___cap_for["_cap_for<br/>src/services/ingestion_service/ingestion.py"]
  src_services_sync_service_sync_py___set_sync_account["_set_sync_account<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___apply_device_metadata["_apply_device_metadata<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___normalize_device_name["_normalize_device_name<br/>src/services/sync_service/sync.py"]
  src_controller_sync_controller_py__redeem_code_route --> src_services_sync_service_sync_py__redeem_code
  src_services_ingestion_service_ingestion_py___trim_to_cap --> src_services_ingestion_service_ingestion_py___cap_for
  src_services_sync_service_sync_py___apply_device_metadata --> src_services_sync_service_sync_py___normalize_device_name
  src_services_sync_service_sync_py__redeem_code --> src_services_ingestion_service_ingestion_py___get_account_tier
  src_services_sync_service_sync_py__redeem_code --> src_services_ingestion_service_ingestion_py___trim_to_cap
  src_services_sync_service_sync_py__redeem_code --> src_services_sync_service_sync_py___apply_device_metadata
  src_services_sync_service_sync_py__redeem_code --> src_services_sync_service_sync_py___migrate_browser_pages
  src_services_sync_service_sync_py__redeem_code --> src_services_sync_service_sync_py___set_sync_account
```

## `POST /v1/sync/generate-code` → `generate_code_route`

`src/controller/sync_controller.py:50` · 7 functions

```mermaid
flowchart LR
  src_controller_sync_controller_py__generate_code_route["generate_code_route<br/>src/controller/sync_controller.py"]
  src_services_sync_service_sync_py__generate_code["generate_code<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py__resolve_sync_account_id["resolve_sync_account_id<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___delete_expired_codes["_delete_expired_codes<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___apply_device_metadata["_apply_device_metadata<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___normalize_device_name["_normalize_device_name<br/>src/services/sync_service/sync.py"]
  src_services_sync_service_sync_py___generate_code["_generate_code<br/>src/services/sync_service/sync.py"]
  src_controller_sync_controller_py__generate_code_route --> src_services_sync_service_sync_py__generate_code
  src_services_sync_service_sync_py___apply_device_metadata --> src_services_sync_service_sync_py___normalize_device_name
  src_services_sync_service_sync_py__generate_code --> src_services_sync_service_sync_py___apply_device_metadata
  src_services_sync_service_sync_py__generate_code --> src_services_sync_service_sync_py___delete_expired_codes
  src_services_sync_service_sync_py__generate_code --> src_services_sync_service_sync_py___generate_code
  src_services_sync_service_sync_py__generate_code --> src_services_sync_service_sync_py__resolve_sync_account_id
```

## `POST /v1/search-stream` → `search_stream`

`src/controller/core_controller.py:332` · 6 functions

```mermaid
flowchart LR
  src_controller_core_controller_py__search_stream["search_stream<br/>src/controller/core_controller.py"]
  src_services_sync_service_sync_py__resolve_sync_account_id["resolve_sync_account_id<br/>src/services/sync_service/sync.py"]
  src_controller_core_controller_py___annotate_source_browser["_annotate_source_browser<br/>src/controller/core_controller.py"]
  src_services_sync_service_sync_py__get_device_names["get_device_names<br/>src/services/sync_service/sync.py"]
  src_services_search_history_service_search_history_py__persist_search["persist_search<br/>src/services/search_history_service/search_history.py"]
  src_services_search_history_service_search_history_py___trim_to_cap["_trim_to_cap<br/>src/services/search_history_service/search_history.py"]
  src_controller_core_controller_py___annotate_source_browser --> src_services_sync_service_sync_py__get_device_names
  src_controller_core_controller_py__search_stream --> src_controller_core_controller_py___annotate_source_browser
  src_controller_core_controller_py__search_stream --> src_services_search_history_service_search_history_py__persist_search
  src_controller_core_controller_py__search_stream --> src_services_sync_service_sync_py__resolve_sync_account_id
  src_services_search_history_service_search_history_py__persist_search --> src_services_search_history_service_search_history_py___trim_to_cap
```

## `DELETE /v1/user/history` → `clear_history_route`

`src/controller/core_controller.py:490` · 4 functions

```mermaid
flowchart LR
  src_controller_core_controller_py__clear_history_route["clear_history_route<br/>src/controller/core_controller.py"]
  src_services_sync_service_sync_py__resolve_sync_account_id["resolve_sync_account_id<br/>src/services/sync_service/sync.py"]
  src_services_privacy_service_privacy_py__resolve_history_clear_range["resolve_history_clear_range<br/>src/services/privacy_service/privacy.py"]
  src_services_privacy_service_privacy_py__clear_history["clear_history<br/>src/services/privacy_service/privacy.py"]
  src_controller_core_controller_py__clear_history_route --> src_services_privacy_service_privacy_py__clear_history
  src_controller_core_controller_py__clear_history_route --> src_services_privacy_service_privacy_py__resolve_history_clear_range
  src_controller_core_controller_py__clear_history_route --> src_services_sync_service_sync_py__resolve_sync_account_id
```

_...and 16 more entry points; see the insights JSON (`--json`)._

---

<sub>Generated by [GNOST](https://gnost.readthedocs.io) 0.7.1. Try it on your own code: `uvx gnost onboard .`</sub>
