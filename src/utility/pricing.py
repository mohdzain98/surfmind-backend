"""Per-model $ pricing for cost estimation in the admin API.

Manually maintained — no live pricing API exists. Source: OpenAI
(developers.openai.com/api/docs/pricing) and Google
(ai.google.dev/gemini-api/docs/pricing), checked 2026-09-20. A stale entry
just means the estimate drifts from reality, not that anything breaks —
update the table when a provider changes prices.
"""

from typing import Optional

# (provider, model) -> {"input": $/1M tokens, "output": $/1M tokens}.
# Embedding models have no output-token cost (0.0).
PRICING_PER_MILLION_TOKENS: dict[tuple[str, str], dict[str, float]] = {
    ("openai", "gpt-4o-mini"): {"input": 0.15, "output": 0.60},
    ("openai", "gpt-4.1-mini"): {"input": 0.40, "output": 1.60},
    ("openai", "text-embedding-3-small"): {"input": 0.02, "output": 0.0},
    ("gemini", "gemini-2.5-flash-lite"): {"input": 0.10, "output": 0.40},
    # gemini-embedding-001 isn't on Google's current pricing page (possibly
    # superseded) — using gemini-embedding-2's rate as the closest known
    # approximation, not an exact figure for this specific model.
    ("gemini", "gemini-embedding-001"): {"input": 0.20, "output": 0.0},
}


def estimate_cost_usd(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> Optional[float]:
    """Return estimated $ cost, or `None` if this (provider, model) isn't priced.

    `None` (not `0.0`) for an unknown pair — callers should surface unpriced
    rows explicitly rather than let them silently vanish into a total.
    """
    rates = PRICING_PER_MILLION_TOKENS.get((provider, model))
    if rates is None:
        return None
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
