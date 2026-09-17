"""Central configuration: environment variables plus `config/params.<env>.yml`.

`Settings` is the single entry point for all tunable config in this app —
secrets/connection info from `.env` (via pydantic-settings), and dev/prod
params from `config/params.dev.yml` or `config/params.prod.yml` (selected by
`environment`, never both). Nothing else in the codebase should read these
files directly; import the module-level `settings` singleton instead.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Literal

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved directly (not via src.utility.path_finder.Finder) to avoid a
# circular import: path_finder -> logger -> settings.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=2)
def _load_params(filename: str) -> Dict[str, Any]:
    """Load and cache one `config/params.<env>.yml` file by name."""
    path = _BACKEND_ROOT / "config" / filename
    with open(path, "r") as f:
        return yaml.safe_load(f)


class Settings(BaseSettings):
    """Central configuration loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    environment: Literal["development", "production"] = "development"
    debug: bool = False
    # Gates DebugAwareLogger.print() (src/utility/logger.py) — separate from
    # `debug` (stdlib log level) so rich intermediate-output printing can be
    # toggled independently via one env var.
    print_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("PRINT", "PRINT_ENABLED")
    )

    # Secrets / connections — matches the env var names SecretsProvider already
    # reads in src/utility/provider.py.
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    redis_host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    redis_port: int = Field(default=6379, validation_alias="REDIS_PORT")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")

    @property
    def _params(self) -> Dict[str, Any]:
        filename = (
            "params.prod.yml" if self.environment == "production" else "params.dev.yml"
        )
        return _load_params(filename)

    def _free(self, *path: str) -> Any:
        """Read a value nested under `<path>.free` — the account-tier axis.

        No account-tier routing exists yet — every caller uses the free
        model config regardless of the account's actual tier.
        """
        node: Any = self._params
        for key in path:
            node = node[key]
        return node["free"]

    @property
    def history_cap(self) -> int:
        """Per-user history retention cap (ingestion.history_cap)."""
        return self._params["ingestion"]["history_cap"]

    @property
    def bookmark_cap(self) -> int:
        """Per-user bookmark retention cap (ingestion.bookmark_cap)."""
        return self._params["ingestion"]["bookmark_cap"]

    @property
    def sync_code_expiry_minutes(self) -> int:
        """Pairing code TTL in minutes (sync.code_expiry_minutes)."""
        return self._params["sync"]["code_expiry_minutes"]

    @property
    def sync_code_rate_limit_per_hour(self) -> int:
        """Max codes generated per account per hour (sync.code_rate_limit_per_hour)."""
        return self._params["sync"]["code_rate_limit_per_hour"]

    @property
    def search_history_retention_cap(self) -> int:
        """Max stored recent-search rows per account (search_history.retention_cap)."""
        return self._params["search_history"]["retention_cap"]

    @property
    def rag_provider(self) -> str:
        """Primary LLM provider for RAG response generation (rag.provider)."""
        return self._params["rag"]["provider"]

    @property
    def rag_model(self) -> str:
        """RAG generation model, free tier (rag.model.free)."""
        return self._free("rag", "model")

    @property
    def rag_temperature(self) -> float:
        """RAG generation temperature (rag.temperature)."""
        return self._params["rag"]["temperature"]

    @property
    def rag_max_tokens(self) -> int:
        """RAG generation max tokens, free tier (rag.max_tokens.free)."""
        return self._free("rag", "max_tokens")

    @property
    def rag_fallback_provider(self) -> str:
        """Fallback LLM provider for RAG generation (rag.fallback.provider)."""
        return self._params["rag"]["fallback"]["provider"]

    @property
    def rag_fallback_model(self) -> str:
        """RAG generation fallback model, free tier (rag.fallback.model.free)."""
        return self._free("rag", "fallback", "model")

    @property
    def post_processing_provider(self) -> str:
        """Primary LLM provider for the relevance judge (post_processing.provider)."""
        return self._params["post_processing"]["provider"]

    @property
    def post_processing_model(self) -> str:
        """Post-processing judge model, free tier (post_processing.model.free)."""
        return self._free("post_processing", "model")

    @property
    def post_processing_temperature(self) -> float:
        """Post-processing temperature (post_processing.temperature)."""
        return self._params["post_processing"]["temperature"]

    @property
    def post_processing_max_tokens(self) -> int:
        """Post-processing max tokens (post_processing.max_tokens) — not tier-split."""
        return self._params["post_processing"]["max_tokens"]

    @property
    def post_processing_fallback_provider(self) -> str:
        """Fallback LLM provider for post-processing (fallback.provider)."""
        return self._params["post_processing"]["fallback"]["provider"]

    @property
    def post_processing_fallback_model(self) -> str:
        """Post-processing fallback model, free tier (fallback.model.free)."""
        return self._free("post_processing", "fallback", "model")

    @property
    def embeddings_provider(self) -> str:
        """Primary embeddings provider (embeddings.provider) — not tier-split."""
        return self._params["embeddings"]["provider"]

    @property
    def embeddings_model(self) -> str:
        """Primary embeddings model (embeddings.model) — not tier-split."""
        return self._params["embeddings"]["model"]

    @property
    def embeddings_fallback_provider(self) -> str:
        """Fallback embeddings provider (embeddings.fallback.provider)."""
        return self._params["embeddings"]["fallback"]["provider"]

    @property
    def embeddings_fallback_model(self) -> str:
        """Fallback embeddings model (embeddings.fallback.model) — not tier-split."""
        return self._params["embeddings"]["fallback"]["model"]


settings = Settings()
