"""Token usage callback — per-`.invoke()` accumulator.

A fresh `TokenUsageCallback` is created around each LLM `.invoke()` call
(`rag.py::safe_invoke_llm_response`, `post_processing.py::post_process`) and
read immediately after — LangChain fires callback hooks synchronously inline
for a sync handler, so `.total_input_tokens`/`.total_output_tokens` are
populated by the time `.invoke()` returns. No cross-call accumulation, no
session/context plumbing: each search's usage is recorded as its own
`LLMUsage` row by the caller in `core_service/main.py`.
"""

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)


class TokenUsageCallback(BaseCallbackHandler):
    """Extracts input/output token counts from a single LLM call."""

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        try:
            input_tokens, output_tokens = self._extract_tokens(response)
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
        except Exception as exc:
            logger.warning(
                "TokenUsageCallback accumulation failed", extra={"error": str(exc)}
            )

    def _extract_tokens(self, response: LLMResult) -> tuple[int, int]:
        # ── 1. LangChain standard (OpenAI / most providers) ──────────────────
        if response.llm_output:
            usage = response.llm_output.get("token_usage") or response.llm_output.get(
                "usage"
            )
            if usage:
                input_tokens = (
                    usage.get("prompt_tokens")  # OpenAI
                    or usage.get("input_tokens")  # Claude
                    or usage.get("prompt_token_count")  # Gemini old SDK
                    or 0
                )
                output_tokens = (
                    usage.get("completion_tokens")  # OpenAI
                    or usage.get("output_tokens")  # Claude
                    or usage.get("candidates_token_count")  # Gemini old SDK
                    or 0
                )
                return int(input_tokens), int(output_tokens)

        # ── 2. generation_info fallback (Gemini new SDK) ─────────────────────
        if response.generations:
            gen = response.generations[0][0]
            info = getattr(gen, "generation_info", {}) or {}
            if info:
                i = int(info.get("input_tokens") or info.get("prompt_token_count") or 0)
                o = int(
                    info.get("output_tokens") or info.get("candidates_token_count") or 0
                )
                if i or o:
                    return i, o

        # ── 3. usage_metadata on message (Claude / newer LangChain) ──────────
        if response.generations:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None)
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                return int(usage.get("input_tokens", 0)), int(
                    usage.get("output_tokens", 0)
                )

        return 0, 0
