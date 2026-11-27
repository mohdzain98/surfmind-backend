# Copyright (c) 2025 Mohd Zain. SurfMind Backend.
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE).
# Commercial use requires a separate license: https://surfmind.docschat.in/contact

"""Detects queries that ask SurfMind to *do* something with a page.

SurfMind only finds pages in a user's history/bookmarks — it can't
summarize, bullet-point, rewrite, or explain "this page". A user who asks
for that still gets plain search results, which reads as SurfMind not
understanding them; flagging the query lets the response carry a notice.

Jev's yes/no `Noul` primitive is the primary judge (fast, cheap, returns a
probability we threshold). If Jev fails, the post-processing LLM answers
the same question as a fallback. If both fail, the query is treated as a
plain search — a missing notice is harmless, a failed search is not.
"""

from typing import Any, Dict, Optional, Tuple

from typesafe_sdk import AsyncTypeSafeClient, Noul

from src.services.llm_service.llm_provider import LLMProvider
from src.utility.logger import AppLogger
from src.utility.settings import settings
from src.utility.token_usage_callback import TokenUsageCallback

logger = AppLogger.get_logger(__name__)

_QUESTION = (
    "This query was typed into a search box that only FINDS pages in the "
    "user's own browsing history and bookmarks. It cannot see the page the "
    "user has open, and cannot summarize, explain, rewrite, bullet-point, "
    "translate, or generate anything. Is the user asking the tool to DO "
    "something with page content, rather than asking it to find a page or "
    "look something up?"
)
_CRITERIA = {
    "true": (
        "The user wants an action performed on content: summarize, explain "
        "what a page says, make bullet points or notes, rewrite, translate, "
        "compare, or write something — including any reference to 'this "
        "page' / 'this article' they have open."
    ),
    "false": (
        "The user wants to find or look something up: a topic, site, product, "
        "keywords, or a factual question like 'what is X' or 'X pricing'."
    ),
}
_FALLBACK_PROMPT = (
    f"{_QUESTION}\n\n"
    f"YES means: {_CRITERIA['true']}\n"
    f"NO means: {_CRITERIA['false']}\n\n"
    'Query: "{query}"\n\n'
    "Answer with exactly one word: YES or NO."
)

UsageDict = Optional[Dict[str, Any]]


class TaskRequestDetector:
    """Answers "is this query a task request?" — Jev first, LLM fallback."""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def detect(self, query: str) -> Tuple[bool, UsageDict]:
        """Return `(is_task_request, usage_dict)`; never raises."""
        try:
            return await self._detect_via_jev(query)
        except Exception as exc:
            logger.warning("Jev task detection failed, falling back to LLM: %s", exc)
        try:
            return await self._detect_via_llm(query)
        except Exception as exc:
            logger.warning("Task detection fallback failed, assuming search: %s", exc)
            return False, None

    async def _detect_via_jev(self, query: str) -> Tuple[bool, UsageDict]:
        async with AsyncTypeSafeClient() as client:
            response = await client.system_one(
                state={"query": query},
                model=settings.task_detection_jev_model,
                questions={
                    "task_request": Noul(instructions=_QUESTION, criteria=_CRITERIA)
                },
            )
        probability = response.answers["task_request"].noul
        is_task = probability >= settings.task_detection_threshold
        logger.print(
            "jev task detection",
            {
                "query": query,
                "probability": probability,
                "threshold": settings.task_detection_threshold,
                "task_request": is_task,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            },
        )
        return is_task, {
            "provider": "jev",
            "model": settings.task_detection_jev_model,
            "input_tokens": response.usage.input_tokens or 0,
            "output_tokens": response.usage.output_tokens or 0,
        }

    async def _detect_via_llm(self, query: str) -> Tuple[bool, UsageDict]:
        callback = TokenUsageCallback()
        llm = self.llm_provider.get_post_processing_llm()
        response = await llm.ainvoke(
            _FALLBACK_PROMPT.replace("{query}", query),
            config={"callbacks": [callback]},
        )
        answer = str(response.content).strip().upper()
        is_task = answer.startswith("YES")
        logger.print(
            "llm task detection (fallback)",
            {"query": query, "answer": answer, "task_request": is_task},
        )
        return is_task, {
            "provider": settings.post_processing_provider,
            "model": settings.post_processing_model,
            "input_tokens": callback.total_input_tokens,
            "output_tokens": callback.total_output_tokens,
        }
