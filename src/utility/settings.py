"""Central configuration: environment variables plus `config/params.<env>.yml`.

`Settings` is the single entry point for all tunable config in this app —
secrets/connection info from `.env` (via pydantic-settings), and dev/prod
params from `config/params.dev.yml` or `config/params.prod.yml` (selected by
`environment`, never both). Nothing else in the codebase should read these
files directly; import the module-level `settings` singleton instead.
"""

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Literal

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved directly (not via src.utility.path_finder.Finder) to avoid a
# circular import: path_finder -> logger -> settings.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Read from pyproject.toml (the single source of truth for this) rather
# than duplicating the number here — bump it in one place, this always
# matches. Independent of DATA_SCHEMA_VERSION below: this is a general
# release version, that's a narrow "may your cached data be stale" signal.
with open(_BACKEND_ROOT / "pyproject.toml", "rb") as _f:
    APP_VERSION: str = tomllib.load(_f)["project"]["version"]

# Bump this ONLY when a backend change means previously-synced client data
# could now be silently stale/missing from search — e.g. this value's
# introduction, marking the move from Redis-only caching to persisted
# Postgres/pgvector storage (anything synced before that point was never
# written to Postgres and needs a full resync to become searchable again).
# The extension compares this against the last version it successfully
# synced against (exposed via /health and /v1/sync/status) and marks its
# local data dirty on a mismatch, forcing exactly one full resync — not a
# literal semantic version, just a monotonically increasing marker.
DATA_SCHEMA_VERSION = 1


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
    admin_jwt_secret: str = Field(default="", validation_alias="ADMIN_JWT_SECRET")
    # nginx runs as a separate process outside this app — its own log files
    # on disk are the only source for them (unlike app_logs, which captures
    # this app's own logging). Standard Debian/Ubuntu paths by default;
    # overridable since prod/staging paths could differ.
    nginx_error_log_path: str = Field(
        default="/var/log/nginx/error.log", validation_alias="NGINX_ERROR_LOG_PATH"
    )
    nginx_access_log_path: str = Field(
        default="/var/log/nginx/access.log", validation_alias="NGINX_ACCESS_LOG_PATH"
    )
    # Comma-separated systemd unit names to health-check (see `systemd_services`
    # below). "surfmind" is this app's own unit name per the actual prod
    # journalctl output seen this session — configurable since staging's
    # differs ("surfmind-staging").
    systemd_service_names: str = Field(
        default="nginx,surfmind", validation_alias="SYSTEMD_SERVICE_NAMES"
    )

    @property
    def systemd_services(self) -> list[str]:
        """Parsed `systemd_service_names`, blank entries dropped."""
        return [
            name.strip()
            for name in self.systemd_service_names.split(",")
            if name.strip()
        ]

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
    def admin_token_expiry_minutes(self) -> int:
        """Admin JWT TTL in minutes (admin.token_expiry_minutes)."""
        return self._params["admin"]["token_expiry_minutes"]

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
