"""LLM client registry for SurfMind.

Builds the generic "gpt"/"gemini" clients used by ingestion's pro-tier
section-summary path, plus use-case-specific clients (RAG generation,
post-processing judge) configured from `config/params.yml` via `settings` —
model, provider, temperature, and max_tokens all vary by use case there.
"""

from typing import Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from src.utility.logger import AppLogger
from src.utility.provider import SecretsProvider
from src.utility.settings import settings

logger = AppLogger.get_logger(__name__)


class LLMProvider:
    """
    Central registry for all LLM clients.
    """

    def __init__(self):
        """Initialize and register supported LLM clients.
        Configures rate limiting and API keys for each provider.
        """
        rate_limiter = InMemoryRateLimiter(
            requests_per_second=1, check_every_n_seconds=0.1, max_bucket_size=5
        )
        self._models: Dict[str, BaseChatModel] = {
            "gpt": ChatOpenAI(
                model="gpt-4.1-mini",
                temperature=0.2,
                max_tokens=500,
                rate_limiter=rate_limiter,
                api_key=SecretsProvider.get_openai_api_key(),
            ),
            "gemini": ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.2,
                rate_limiter=rate_limiter,
                api_key=SecretsProvider.get_gemini_api_key(),
            ),
        }

        self.rag_llm = self._build_chat_model(
            settings.rag_provider,
            settings.rag_model,
            settings.rag_temperature,
            settings.rag_max_tokens,
            rate_limiter,
        )
        self.rag_fallback_llm = self._build_chat_model(
            settings.rag_fallback_provider,
            settings.rag_fallback_model,
            settings.rag_temperature,
            settings.rag_max_tokens,
            rate_limiter,
        )
        self.post_processing_llm = self._build_chat_model(
            settings.post_processing_provider,
            settings.post_processing_model,
            settings.post_processing_temperature,
            settings.post_processing_max_tokens,
            rate_limiter,
        )
        self.post_processing_fallback_llm = self._build_chat_model(
            settings.post_processing_fallback_provider,
            settings.post_processing_fallback_model,
            settings.post_processing_temperature,
            settings.post_processing_max_tokens,
            rate_limiter,
        )

    @staticmethod
    def _build_chat_model(
        provider: str,
        model: str,
        temperature: float,
        max_tokens: int,
        rate_limiter: InMemoryRateLimiter,
    ) -> BaseChatModel:
        """Construct a chat client for `provider` ("openai" or "gemini")."""
        if provider == "openai":
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                rate_limiter=rate_limiter,
                api_key=SecretsProvider.get_openai_api_key(),
            )
        if provider == "gemini":
            return ChatGoogleGenerativeAI(
                model=model,
                temperature=temperature,
                rate_limiter=rate_limiter,
                api_key=SecretsProvider.get_gemini_api_key(),
            )
        raise ValueError(f"Unsupported LLM provider: {provider}")

    def get(self, name: str) -> BaseChatModel:
        """
        Get LLM by name.
        """
        if name not in self._models:
            logger.error(f"LLM not found")
            raise ValueError(
                f"LLM '{name}' not found. Available: {list(self._models.keys())}"
            )
        return self._models[name]

    def all(self) -> Dict[str, BaseChatModel]:
        """
        Return all registered LLMs.
        """
        return self._models

    def get_rag_llm(self) -> BaseChatModel:
        """Return the settings-configured primary RAG generation model."""
        return self.rag_llm

    def get_rag_fallback_llm(self) -> BaseChatModel:
        """Return the settings-configured fallback RAG generation model."""
        return self.rag_fallback_llm

    def get_post_processing_llm(self) -> BaseChatModel:
        """Return the settings-configured primary post-processing judge model."""
        return self.post_processing_llm

    def get_post_processing_fallback_llm(self) -> BaseChatModel:
        """Return the settings-configured fallback post-processing judge model."""
        return self.post_processing_fallback_llm
