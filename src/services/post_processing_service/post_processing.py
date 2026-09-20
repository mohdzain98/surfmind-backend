"""Post-processing for filtering and ranking retrieved documents.
Work as LLM as a Judge to remove unrequired outputs from final response
"""

import ast
from typing import Any, Dict, List, Tuple

from langchain_core.prompts import PromptTemplate

from src.models.core import Document
from src.services.llm_service.llm_provider import LLMProvider
from src.utility.logger import AppLogger
from src.utility.settings import settings
from src.utility.token_usage_callback import TokenUsageCallback
from src.utility.utils import Utility

logger = AppLogger.get_logger(__name__)


class PostProcessing:
    """
    Post-process retrieved documents using LLM relevance checks.
    """

    def __init__(self):
        """Initialize providers and utility helpers for post-processing."""
        self.llm_provider = LLMProvider()
        self.utility = Utility()

    def clean_docs(self, url, docs):
        """Deduplicate documents while keeping the primary source.
        Returns a filtered list suitable for prompt building.
        """
        cleaned_docs = []
        cleaned_docs.append(docs[0])  # Keep the main document
        for doc in docs:
            if doc.metadata["source"] != url:
                cleaned_docs.append(doc)
        return cleaned_docs

    def join_docs(self, docs):
        """Build a prompt-ready representation of documents.
        Returns joined strings, document list, and index map.
        """

        doc_strings = []
        document_list = []
        seen_sources = set()
        doc_number = 1

        index_map = {}

        for doc in docs:
            source = doc.metadata.get("source")

            if source in seen_sources:
                continue
            seen_sources.add(source)

            content = doc.page_content[:300].replace("\n", " ")
            title = doc.metadata.get("title", "")
            title = title.strip() if title and title.strip() else content

            # Store mapping
            index_map[doc_number] = len(document_list)

            # 🔥 Add source & title
            block = (
                f"{doc_number}. "
                f'Title: "{title}"\n'
                f"Source: {source}\n"
                f'Content: "{content}"'
            )

            doc_strings.append(block)
            document_list.append({"content": content, "metadata": doc.metadata})
            doc_number += 1

        joined_docs = "\n\n".join(doc_strings)

        return joined_docs, document_list, index_map

    def post_process(
        self, ques: str, docs: List[Document]
    ) -> Tuple[list[dict[str, Any]], Dict[str, Any]]:
        """Filter documents by LLM-assessed relevance.

        Returns the filtered document list and a
        `{"provider", "model", "input_tokens", "output_tokens"}` usage dict
        for `LLMUsage` recording (best-effort, see `TokenUsageCallback`).
        """
        llm_primary = self.llm_provider.get_post_processing_llm()
        llm_fallback = self.llm_provider.get_post_processing_fallback_llm()
        top_doc = docs[0]
        source = top_doc.metadata.get("source")
        cleaned_docs = self.clean_docs(source, docs)
        joined_docs, whole_doc, index_map = self.join_docs(cleaned_docs)
        prompts = self.utility.load_prompts()
        relevant_prompt = prompts["prompt"]["relevance"]
        relevance_prompt = PromptTemplate(
            input_variables=["query", "content_blocks"], template=relevant_prompt
        )
        try:
            callback = TokenUsageCallback()
            ans = llm_primary.invoke(
                relevance_prompt.invoke({"query": ques, "content_blocks": joined_docs}),
                config={"callbacks": [callback]},
            )
            usage = {
                "provider": settings.post_processing_provider,
                "model": settings.post_processing_model,
                "input_tokens": callback.total_input_tokens,
                "output_tokens": callback.total_output_tokens,
            }
        except Exception as e:
            logger.warning(f"Primary LLM failed in post-processing, reason: {e}")
            callback = TokenUsageCallback()
            ans = llm_fallback.invoke(
                relevance_prompt.invoke({"query": ques, "content_blocks": joined_docs}),
                config={"callbacks": [callback]},
            )
            usage = {
                "provider": settings.post_processing_fallback_provider,
                "model": settings.post_processing_fallback_model,
                "input_tokens": callback.total_input_tokens,
                "output_tokens": callback.total_output_tokens,
            }
        try:
            irrelevant_indices = ast.literal_eval(ans.content.strip())
            if not isinstance(irrelevant_indices, list):
                irrelevant_indices = []
        except Exception:
            logger.error(f"Failed to parse LLM output: {ans.content}")
            irrelevant_indices = []
        filtered_docs = whole_doc  # Start with all documents
        if irrelevant_indices:
            irrelevant_indices = [
                index_map[i] for i in irrelevant_indices if i in index_map
            ]
            filtered_docs = [
                doc
                for idx, doc in enumerate(whole_doc)
                if idx not in irrelevant_indices
            ]
        return filtered_docs, usage
