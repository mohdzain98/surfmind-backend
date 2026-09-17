"""Classifies pages into a user's category set.

Tries Jev (TypeSafe AI's System One `Choice` primitive) first — fast,
cheap, and structurally can't return a category outside the provided set,
unlike a general LLM prompt. Falls back to the existing Gemini path on any
failure, since Jev is very new and hasn't earned unconditional trust yet.
"""

from typing import TypedDict

from typesafe_sdk import AsyncTypeSafeClient, Choice

from src.services.llm_service.llm_provider import LLMProvider
from src.utility.logger import AppLogger
from src.utility.settings import settings

logger = AppLogger.get_logger(__name__)


class ClassificationResult(TypedDict):
    category_name: str | None
    confidence: float | None
    provider: str


class PageClassifier:
    """Classifies one page's content into one of the user's live categories."""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def classify(
        self, page_content: str, categories: list[dict]
    ) -> ClassificationResult:
        """Return the best-matching category name for `page_content`.

        `categories`: `[{"name": ..., "description": ...}, ...]` — the
        user's live category set, pulled fresh by the caller each run so
        edits/deletes are respected without any retraining step.
        """
        criteria = {cat["name"]: cat["description"] for cat in categories}

        try:
            choice, confidence = await self._classify_via_jev(page_content, criteria)
            return {
                "category_name": choice,
                "confidence": confidence,
                "provider": "jev",
            }
        except Exception as exc:
            logger.warning("Jev classification failed, falling back to Gemini: %s", exc)
            choice = await self._classify_via_gemini(page_content, criteria)
            return {
                "category_name": choice,
                "confidence": None,
                "provider": "gemini_fallback",
            }

    async def _classify_via_jev(
        self, page_content: str, criteria: dict[str, str]
    ) -> tuple[str, float | None]:
        async with AsyncTypeSafeClient() as client:
            response = await client.system_one(
                state=page_content,
                model=settings.classification_jev_model,
                questions={
                    "category": Choice(
                        instructions=(
                            "Classify this browsing history/bookmark page into "
                            "the category it best fits."
                        ),
                        criteria=criteria,
                    )
                },
            )
        answer = response.answers["category"]
        return answer.choice, answer.confidence

    async def _classify_via_gemini(
        self, page_content: str, criteria: dict[str, str]
    ) -> str | None:
        """Prompt-based fallback — not structurally constrained like Jev, so
        the caller must validate the returned name is one of `criteria`'s
        keys; an unrecognized name is treated as unclassified, not a valid
        (possibly hallucinated) category.
        """
        category_list = "\n".join(
            f"- {name}: {desc}" for name, desc in criteria.items()
        )
        prompt = (
            "Classify the following page into exactly one category.\n"
            f"Categories:\n{category_list}\n\n"
            f"Page content: {page_content}\n\n"
            "Respond with only the category name, exactly as listed above."
        )
        llm = self.llm_provider.get_classification_fallback_llm()
        response = await llm.ainvoke(prompt)
        choice = response.content.strip()
        return choice if choice in criteria else None
