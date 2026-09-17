"""Core retrieval orchestration for SurfMind RAG flows.
Provides synchronous and streaming pipelines for search.
Includes a mock streamer to test UI progress handling.
"""

import time
from typing import Any, AsyncGenerator, Dict, Generator, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.core import Document, SearchRequest, SearchResponse
from src.services.core_service.rag import HybridRAGService, LLMRag
from src.services.llm_service.llm_provider import LLMProvider
from src.services.post_processing_service.post_processing import PostProcessing
from src.utility.logger import AppLogger

logger = AppLogger.get_logger(__name__)


class CoreRetrieval:
    """Coordinate retrieval, LLM calls, parsing, and post-processing.
    Builds documents from user data and delegates retrieval to RAG services.
    """

    def __init__(self):
        """Initialize shared service dependencies for the RAG pipeline.
        Wires up LLM provider, post-processing, and retriever components.
        """
        self.llm_client = LLMProvider()
        self.post_processing = PostProcessing()
        self.rag = HybridRAGService()
        self.llm_rag = LLMRag()

    def _build_parent_documents(
        self, history: List[dict[str, str]], flag: str
    ) -> List[Document]:
        """Convert raw history items into parent Document objects.
        Maps fields to metadata used by retrieval and post-processing.
        Returns a list of parent-level documents for chunking.
        """
        docs: List[Document] = []
        for item in history:
            title = item.get("title", "")
            # Mirrors ingestion_service._default_heading_path exactly — must
            # match what's persisted in Postgres so pgvector hits for the
            # same section merge onto this same parent instead of duplicating.
            heading_path = item.get("heading_path")
            if not heading_path:
                heading_path = [] if flag == "bookmark" else ([title] if title else [])
            docs.append(
                Document(
                    page_content=item.get("content", ""),
                    metadata={
                        "source": item.get("url", ""),
                        "date": item.get("date", ""),
                        "title": title,
                        "domain": item.get("domain", ""),
                        "folder": item.get("folder", ""),
                        "type": flag,
                        "heading_path": heading_path,
                        "heading_level": item.get("heading_level"),
                        "section_index": item.get("section_index"),
                        "page_type": item.get("page_type"),
                    },
                )
            )

        return docs

    def _empty_response(self, message: str) -> SearchResponse:
        """Create a standardized empty SearchResponse with a message.
        Used when no history or no relevant data is found.
        """
        return SearchResponse(
            success=False,
            result=message,
            format=None,
            model=None,
            docs=[],
        )

    def _stream_event(self, step: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap streaming payloads in a consistent step envelope.
        Keeps the SSE payload format stable for UI consumption.
        Returns a JSON-serializable dictionary.
        """
        return {"step": step, "data": data}

    def _print_docs(self, label: str, docs: List) -> None:
        """Debug-print a bounded preview of retrieval/post-processing docs.

        Accepts either `Document` objects (retrieval output) or the plain
        dicts post-processing returns — both carry `content`/`metadata`.
        """
        summaries = []
        for doc in docs:
            content, metadata = (
                (doc.get("content", ""), doc.get("metadata", {}))
                if isinstance(doc, dict)
                else (doc.page_content, doc.metadata)
            )
            summaries.append(
                {
                    "source": metadata.get("source"),
                    "heading_path": metadata.get("heading_path"),
                    "preview": content[:150],
                }
            )
        logger.print(label, {"count": len(docs), "docs": summaries})

    async def invoke_rag(
        self,
        data: SearchRequest,
        history: List[dict],
        user_id: str,
        db: AsyncSession,
    ) -> SearchResponse:
        """Run the full RAG pipeline and return a final response.

        `user_id` is the resolved sync account id (not necessarily the raw
        browser id in `data.user_id`) — it's what scopes Postgres retrieval.
        Returns a SearchResponse ready for API consumption.
        """
        ques = data.query
        flag = data.flag
        parent_docs = self._build_parent_documents(history=history, flag=flag)
        if not parent_docs:
            logger.warning("No history data found")
            return self._empty_response("No history data found")

        # List of combined docs from bm25 and pgvector
        retrieved_parents = await self.rag.retrieve_parents(
            query=ques,
            parent_docs=parent_docs,
            user_id=user_id,
            flag=flag,
            db=db,
        )
        if not retrieved_parents:
            logger.warning("No relevant data found")
            return self._empty_response("No relevant data found")
        self._print_docs("retrieval output", retrieved_parents)

        top_doc = retrieved_parents[0]
        context = top_doc.page_content
        source = top_doc.metadata.get("source")
        date = top_doc.metadata.get("date")

        result, model = self.llm_rag.safe_invoke_llm_response(
            context=context, date=date, url=source, flag=flag
        )
        logger.print("final answer", {"model": model, "result": result})
        pchain = self.llm_rag.structure(flag=flag)
        finalOutput = pchain.invoke({"content": result})
        final_docs = self.post_processing.post_process(
            ques=ques, docs=retrieved_parents
        )
        self._print_docs("post-processing output", final_docs)
        if not final_docs:
            logger.warning("No relevant data found after post processing")
            return self._empty_response("No relevant data found")
        res = SearchResponse(
            success=True,
            result=result,
            format=finalOutput,
            model=model,
            docs=final_docs,
        )
        return res

    async def stream_rag(
        self,
        data: SearchRequest,
        history: List[dict[str, str]],
        user_id: str,
        db: AsyncSession,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream progress events for each major RAG pipeline step.

        `user_id` is the resolved sync account id used to scope Postgres
        retrieval. Enables SSE clients to show intermediate status updates.
        """
        ques = data.query
        flag = data.flag
        parent_docs = self._build_parent_documents(history=history, flag=flag)
        if not parent_docs:
            res = self._empty_response("No history data found")
            yield self._stream_event("final", res.dict())
            return

        retrieved_parents = await self.rag.retrieve_parents(
            query=ques,
            parent_docs=parent_docs,
            user_id=user_id,
            flag=flag,
            db=db,
        )
        yield self._stream_event(
            "retrieved_parents",
            {"count": len(retrieved_parents)},
        )
        if not retrieved_parents:
            res = self._empty_response("No relevant data found")
            yield self._stream_event("final", res.dict())
            return
        self._print_docs("retrieval output", retrieved_parents)

        validated_docs = self.post_processing.post_process(
            ques=ques, docs=retrieved_parents
        )
        self._print_docs("post-processing output", validated_docs)
        yield self._stream_event(
            "post_processing",
            {"validated_docs": len(validated_docs)},
        )
        if len(validated_docs) == 0:
            res = self._empty_response(message="No relevant data found")
            yield self._stream_event("final", res.dict())
            return

        top_doc: dict = validated_docs[0]
        context = top_doc.get("content", "")
        source = top_doc.get("metadata", {}).get("source", "")
        date = top_doc.get("metadata", {}).get("date", None)

        result, model = self.llm_rag.safe_invoke_llm_response(
            context=context, date=date, url=source, flag=flag
        )
        logger.print("final answer", {"model": model, "result": result})
        yield self._stream_event(
            "llm_response",
            {"text": result, "model": model},
        )

        pchain = self.llm_rag.structure(flag=flag)
        final_output = pchain.invoke({"content": result})
        yield self._stream_event(
            "output_parser",
            {"format": final_output},
        )

        # final_docs = self.post_processing.post_process(
        #     ques=ques, url=source, docs=retrieved_parents
        # )
        # yield self._stream_event(
        #     "post_processing",
        #     {"validated_docs": len(final_docs)},
        # )

        # if not final_docs:
        #     logger.warning("No relevant data found after post processing")
        #     res = self._empty_response("No relevant data found")
        #     yield self._stream_event("final", res.model_dump())
        #     return

        res = SearchResponse(
            success=True,
            result=result,
            format=final_output,
            model=model,
            docs=validated_docs,
        )
        yield self._stream_event("final", res.model_dump())

    async def stream_combined_rag(
        self,
        data: SearchRequest,
        history: List[dict],
        bookmarks: List[dict],
        user_id: str,
        db: AsyncSession,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream combined history+bookmark search progress via SSE.

        `user_id` is the resolved sync account id used to scope Postgres
        retrieval. Runs retrieval on each corpus so both sources are
        guaranteed representation (k results each), then interleaves them
        before post-processing.
        """
        ques = data.query
        history_docs = self._build_parent_documents(history=history, flag="history")
        bookmark_docs = self._build_parent_documents(history=bookmarks, flag="bookmark")

        if not history_docs and not bookmark_docs:
            res = self._empty_response("No data found for combined search")
            yield self._stream_event("final", res.dict())
            return

        async def _safe_retrieve(docs: List[Document], flag: str) -> List[Document]:
            if not docs:
                return []
            try:
                return await self.rag.retrieve_parents(
                    query=ques, parent_docs=docs, user_id=user_id, flag=flag, db=db
                )
            except Exception as exc:
                logger.warning("Retrieval failed for corpus: %s", exc)
                return []

        # Sequential, not concurrent: both calls share one AsyncSession, and
        # SQLAlchemy's AsyncSession isn't safe for concurrent use. Each call
        # is scoped to its own flag so a bookmark page can't surface via the
        # history-seeded call (or vice versa) — full history+bookmark
        # coverage comes from making both calls, not from either call being
        # unscoped.
        history_parents = await _safe_retrieve(history_docs, flag="history")
        bookmark_parents = await _safe_retrieve(bookmark_docs, flag="bookmark")

        total_retrieved = len(history_parents) + len(bookmark_parents)
        yield self._stream_event("retrieved_parents", {"count": total_retrieved})
        self._print_docs("retrieval output (history)", history_parents)
        self._print_docs("retrieval output (bookmarks)", bookmark_parents)

        if not history_parents and not bookmark_parents:
            res = self._empty_response("No relevant data found")
            yield self._stream_event("final", res.dict())
            return

        # Post-process each source independently and sequentially.
        # Bookmark content is sparse (title only), so judging it alongside
        # richer history results causes the LLM to unfairly drop bookmarks.
        # Separate evaluation gives each source a fair relevance check.
        # Sequential (not parallel) to avoid simultaneous LLM calls hitting
        # rate limits — each corpus is ≤3 docs so the latency cost is small.
        def _safe_post_process(docs):
            if not docs:
                return []
            try:
                return self.post_processing.post_process(ques=ques, docs=docs)
            except Exception as exc:
                logger.warning("Post-processing failed for corpus: %s", exc)
                return []

        validated_history = _safe_post_process(history_parents)
        validated_bookmarks = _safe_post_process(bookmark_parents)

        # Merge: history first, then bookmarks (Popup.js re-splits by metadata.type)
        validated_docs = validated_history + validated_bookmarks
        self._print_docs("post-processing output", validated_docs)
        yield self._stream_event(
            "post_processing", {"validated_docs": len(validated_docs)}
        )

        if not validated_docs:
            res = self._empty_response("No relevant data found after filtering")
            yield self._stream_event("final", res.dict())
            return

        top_doc: dict = validated_docs[0]
        context = top_doc.get("content", "")
        source = top_doc.get("metadata", {}).get("source", "")
        date = top_doc.get("metadata", {}).get("date", None)

        result, model = self.llm_rag.safe_invoke_llm_response(
            context=context, date=date, url=source, flag="combined"
        )
        logger.print("final answer", {"model": model, "result": result})
        yield self._stream_event("llm_response", {"text": result, "model": model})

        pchain = self.llm_rag.structure(flag="combined")
        final_output = pchain.invoke({"content": result})
        yield self._stream_event("output_parser", {"format": final_output})

        res = SearchResponse(
            success=True,
            result=result,
            format=final_output,
            model=model,
            docs=validated_docs,
        )
        yield self._stream_event("final", res.model_dump())

    def mock_stream_rag(
        self,
        data,
        history,
    ) -> Generator[Dict[str, Any], None, None]:
        """Mock streaming RAG for UI testing without LLM dependencies.
        Keeps latency between steps to mimic real execution timing.
        """

        ques = data.query
        flag = data.flag

        # ----------------------------
        # Step 1: Pretend we built docs
        # ----------------------------
        time.sleep(2)
        yield self._stream_event(
            "retrieved_parents",
            {"count": 3},
        )

        # ----------------------------
        # Step 2: Stream fake LLM answer
        # ----------------------------
        time.sleep(2)
        fake_answer = (
            "The Lyapunov exponent measures how sensitive a dynamical system "
            "is to initial conditions. A positive exponent indicates chaos."
        )

        yield self._stream_event(
            "llm_response",
            {
                "text": fake_answer,
                "model": "mock-llm",
            },
        )

        # ----------------------------
        # Step 3: Fake structured output
        # ----------------------------
        time.sleep(2)

        if flag == "history":
            fake_format = {
                "date": "2025-07-01",
                "url": "https://math.libretexts.org/Lyapunov_Exponent",
            }
        else:
            fake_format = {
                "url": "https://math.libretexts.org/Lyapunov_Exponent",
            }

        yield self._stream_event(
            "output_parser",
            {"format": fake_format},
        )

        # ----------------------------
        # Step 4: Fake post processing
        # ----------------------------
        time.sleep(2)

        fake_docs = [
            {
                "content": "9.3: Lyapunov Exponent - Mathematics LibreTexts",
                "metadata": {
                    "source": "https://math.libretexts.org/Bookshelves/Scientific_Computing_Simulations_and_Modeling/Introduction_to_the_Modeling_and_Analysis_of_Complex_Systems_(Sayama)/09%3A_Chaos/9.03%3A_Lyapunov_Exponent",
                    "date": None,
                    "title": "",
                    "type": flag,
                },
            },
        ]

        yield self._stream_event(
            "post_processing",
            {"validated_docs": len(fake_docs)},
        )
        time.sleep(2)
        # ----------------------------
        # Step 5: Final response
        # ----------------------------
        res = SearchResponse(
            success=True,
            result=fake_answer,
            format=fake_format,
            model="mock-llm",
            docs=fake_docs,
        )

        yield self._stream_event(
            "final",
            res.model_dump(),
        )


class Retrieval:
    """Factory for providing a CoreRetrieval instance to FastAPI."""

    @staticmethod
    def get_retrieval_service() -> CoreRetrieval:
        """Create a new CoreRetrieval instance for request handling.
        Keeps dependency injection explicit and testable.
        Separates construction from API controller code.
        """
        return CoreRetrieval()
