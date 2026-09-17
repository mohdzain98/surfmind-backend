"""
Hybrid RAG implementation for SurfMind

- Parent documents = heading-scoped sections of a page (url + heading_path)
- Child documents = sentence-grouped, token-bounded chunks within a section
- Hybrid retrieval = BM25 (in-app, per request) + pgvector (persisted embeddings)
- Explicit parent mapping, with a heading-path term-match boost
"""

import asyncio
import difflib
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import tiktoken
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.runnables import Runnable, RunnablePassthrough
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.core import Ans_bookmark, Ans_combined, Ans_history
from src.services.llm_service.llm_provider import LLMProvider
from src.services.llm_service.prompt_builder import Prompts
from src.utility.logger import AppLogger
from src.utility.provider import EmbeddingsProvider as ef
from src.utility.settings import settings

logger = AppLogger.get_logger(__name__)

_TOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")

# Common abbreviations that shouldn't be treated as sentence boundaries.
_ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "inc",
    "ltd",
    "co",
    "st",
    "u.s",
    "u.k",
}


def _split_sentences(text_block: str) -> List[str]:
    """Lightweight regex sentence splitter with a common-abbreviation guard.

    Splits on `.`/`!`/`?` followed by whitespace, then re-merges a split
    that landed right after a known abbreviation (e.g. "Dr.", "e.g.") back
    onto the next piece rather than treating it as a sentence boundary.
    """
    raw = re.split(r"(?<=[.!?])\s+", text_block.strip())
    sentences: List[str] = []
    buffer = ""
    for piece in raw:
        buffer = f"{buffer} {piece}".strip() if buffer else piece
        words = buffer.split()
        last_word = re.sub(r"[.!?]+$", "", words[-1]).lower() if words else ""
        if last_word in _ABBREVIATIONS:
            continue
        sentences.append(buffer)
        buffer = ""
    if buffer:
        sentences.append(buffer)
    return [s for s in sentences if s]


def _chunk_section(section_text: str, max_tokens: int = 300) -> List[str]:
    """Group a section's sentences into chunks up to a token budget.

    Never splits mid-sentence — each chunk is a run of whole sentences
    whose combined token count stays under `max_tokens`.
    """
    sentences = _split_sentences(section_text)
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0
    for sentence in sentences:
        token_count = len(_TOKEN_ENCODING.encode(sentence))
        if current_tokens + token_count > max_tokens and current:
            chunks.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += token_count
    if current:
        chunks.append(" ".join(current))
    return chunks


class HybridRAGService:
    """Hybrid retrieval using BM25 and pgvector for parent selection.
    Splits parent documents into chunks for BM25, merges with persisted
    pgvector similarity hits scoped to the requesting user.
    """

    def __init__(
        self,
        max_chunk_tokens: int = 300,
        bm25_k: int = 3,
        vector_k: int = 3,
    ):
        """Initialize chunking, retriever settings, and embeddings.
        Uses the settings-configured provider (config/params.yml) with
        automatic fallback to the settings-configured fallback provider.
        """
        self.llm_provider = LLMProvider()
        self.max_chunk_tokens = max_chunk_tokens
        self.bm25_k = bm25_k
        self.vector_k = vector_k
        self.embeddings = ef.get_default_embeddings()

    def _build_child_documents(
        self, parent_docs: List[Document]
    ) -> Tuple[List[Document], List[Document]]:
        """
        Split parent (section-level) documents into sentence-grouped chunks.
        Each child keeps reference to its parent via parent_id.
        """
        child_docs: List[Document] = []
        for parent_id, doc in enumerate(parent_docs):
            chunks = _chunk_section(doc.page_content, max_tokens=self.max_chunk_tokens)

            for chunk in chunks:
                child_docs.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            **doc.metadata,
                            "parent_id": parent_id,
                        },
                    )
                )

        if not child_docs:
            logger.error("No child documents created")
            raise ValueError("No child documents created from input data")

        return child_docs, parent_docs

    def _build_vocabulary(self, child_docs) -> Set[str]:
        """Build a vocabulary set from child document text.
        Uses simple alphanumeric token extraction for matching.
        """
        vocab = set()
        for doc in child_docs:
            tokens = re.findall(r"[a-z0-9]+", doc.page_content.lower())
            vocab.update(tokens)
        return vocab

    def simple_tokenizer(self, text: str) -> List[str]:
        """
        Lightweight tokenizer for BM25.
        - lowercase
        - removes punctuation
        - splits on whitespace
        """
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return text.split()

    def expand_query_typo_tolerant(
        self,
        query: str,
        vocabulary: set[str],
        cutoff: float = 0.8,
    ) -> str:
        """
        Expands query with closest vocabulary matches.
        """
        expanded_terms = []
        tokens = query.lower().split()

        for token in tokens:
            expanded_terms.append(token)

            matches = difflib.get_close_matches(
                token,
                vocabulary,
                n=1,
                cutoff=cutoff,
            )
            if matches and matches[0] != token:
                expanded_terms.append(matches[0])

        return " ".join(expanded_terms)

    def _bm25_is_weak(self, bm25_hits: list[Document], query: str) -> bool:
        """Check if BM25 hits lack clear query token matches.
        Returns True when keyword signal appears weak.
        """
        query_tokens = set(query.lower().split())

        for doc in bm25_hits:
            text = doc.page_content.lower()
            if any(tok in text for tok in query_tokens):
                return False
        return True

    def _build_bm25_retriever(self, child_docs: List[Document]) -> BM25Retriever:
        """Create a BM25 retriever with a custom tokenizer.
        Applies the configured k to control result count.
        """
        bm25 = BM25Retriever.from_documents(
            child_docs, preprocess_func=self.simple_tokenizer
        )
        bm25.k = self.bm25_k
        return bm25

    async def _run_pgvector(
        self, query: str, user_id: str, flag: str, db: AsyncSession
    ) -> List[dict]:
        """Rank this user's `flag`-scoped pages by their single best-matching section.

        `DISTINCT ON (p.id)` picks each page's nearest section, structurally
        guaranteeing at most one hit per page — the inner query's rows land
        in `page_id` order though, not relevance order, so the outer query
        re-sorts by distance before `LIMIT :k` to actually return the k
        best-matching *pages*, not an arbitrary k of them.

        Scoped by `flag` (`history` or `bookmark`) so a history search
        can't surface bookmark pages and vice versa — combined search gets
        full history+bookmark coverage by calling this twice, once per
        flag, not by leaving it unscoped here.
        """
        query_vector = await self.embeddings.aembed_query(query)
        # Bound as a pgvector text literal + explicit cast — avoids needing
        # asyncpg codec registration just to bind a raw SQL query.
        embedding_literal = "[" + ",".join(str(v) for v in query_vector) + "]"
        result = await db.execute(
            text("""
                SELECT * FROM (
                    SELECT DISTINCT ON (p.id)
                        p.url, p.title, p.domain, p.folder, p.flag, p.page_type,
                        ps.heading_path, ps.heading_level, ps.section_index,
                        ps.content, ps.date,
                        e.embedding <=> CAST(:query_embedding AS vector) AS distance
                    FROM section_embeddings e
                    JOIN page_sections ps ON ps.id = e.section_id
                    JOIN pages p ON p.id = ps.page_id
                    WHERE p.user_id = :user_id AND p.flag = :flag
                    ORDER BY p.id, e.embedding <=> CAST(:query_embedding AS vector)
                ) ranked
                ORDER BY distance
                LIMIT :k
                """),
            {
                # pages.user_id is a real Integer FK now (was a loose String
                # column on the old history_entries table).
                "user_id": int(user_id),
                "flag": flag,
                "query_embedding": embedding_literal,
                "k": self.vector_k,
            },
        )
        return [dict(row._mapping) for row in result]

    def _merge_vector_hits(
        self, parents: List[Document], vector_rows: List[dict]
    ) -> Tuple[List[Document], List[dict]]:
        """Fold pgvector hits outside the request's parent_docs into `parents`.

        pgvector covers a user's full persisted history, not just what's
        Redis-cached for this request, so a hit may need a brand-new pid
        instead of matching an existing one. Matched by `(url, heading_path)`,
        not bare `url` — a URL can have several section rows now, and
        matching on URL alone would silently collapse distinct sections
        onto the same pid. Order is preserved so rank-based scoring in
        `_map_to_parents` still reflects similarity order.
        """

        def _key(source: Optional[str], heading_path: Optional[List[str]]) -> tuple:
            return source, tuple(heading_path or [])

        source_to_pid = {
            _key(doc.metadata.get("source"), doc.metadata.get("heading_path")): pid
            for pid, doc in enumerate(parents)
        }
        hits_with_pid: List[dict] = []
        for row in vector_rows:
            key = _key(row["url"], row.get("heading_path"))
            pid = source_to_pid.get(key)
            if pid is None:
                parents.append(
                    Document(
                        page_content=row["content"],
                        metadata={
                            "source": row["url"],
                            "date": row["date"],
                            "title": row["title"] or "",
                            "domain": row.get("domain") or "",
                            "folder": row.get("folder") or "",
                            "type": row["flag"],
                            "heading_path": row.get("heading_path") or [],
                            "heading_level": row.get("heading_level"),
                            "section_index": row.get("section_index"),
                            "page_type": row.get("page_type"),
                        },
                    )
                )
                pid = len(parents) - 1
                source_to_pid[key] = pid
            hits_with_pid.append({**row, "parent_id": pid})
        return parents, hits_with_pid

    async def retrieve_parents(
        self,
        query: str,
        parent_docs: List[Document],
        user_id: str,
        flag: str,
        db: AsyncSession,
    ) -> List[Document]:
        """
        Main hybrid retrieval entrypoint.
        Returns parent-level documents, ranked by combined BM25 + pgvector score.
        `flag` scopes both signals to one corpus (history or bookmark) —
        callers wanting combined coverage call this twice, once per flag.
        """
        # Step 1: build child docs (BM25 only — pgvector reads persisted rows)
        child_docs, parents = self._build_child_documents(parent_docs)

        # Step 1.1: Build vocab once per request and expand query
        vocabulary = self._build_vocabulary(child_docs)
        expanded_query = self.expand_query_typo_tolerant(query, vocabulary)

        def _run_bm25() -> List[Document]:
            bm25 = self._build_bm25_retriever(child_docs)
            return bm25.invoke(expanded_query)

        # Step 2 & 3: BM25 (sync, off the event loop) and pgvector concurrently
        bm25_hits, vector_rows = await asyncio.gather(
            asyncio.to_thread(_run_bm25),
            self._run_pgvector(query=query, user_id=user_id, flag=flag, db=db),
        )

        # Step 4: extend parents with vector-only hits, then merge + map back
        parents, vector_hits = self._merge_vector_hits(parents, vector_rows)
        return self._map_to_parents(
            query=query,
            bm25_hits=bm25_hits,
            vector_hits=vector_hits,
            parents=parents,
        )

    def _map_to_parents(
        self,
        query: str,
        bm25_hits: List[Document],
        vector_hits: List[dict],
        parents: List[Document],
    ) -> List[Document]:
        """
        Map retrieved child docs back to parents with proper ranking.
        Only parents that appear in bm25_hits or vector_hits are returned.
        """

        scores: Dict[int, float] = defaultdict(float)

        bm25_weak = self._bm25_is_weak(bm25_hits, query)

        # pgvector hits (semantic signal – stronger when BM25 is weak)
        for rank, hit in enumerate(vector_hits):
            pid = hit.get("parent_id")
            if pid is not None:
                scores[pid] += 3.0 / (rank + 1)

        # BM25 hits (keyword signal)
        for rank, doc in enumerate(bm25_hits):
            pid = doc.metadata.get("parent_id")
            if pid is not None:
                scores[pid] += (1.0 if bm25_weak else 2.5) / (rank + 1)

        if not scores:
            return []

        # Heading-path term boost: a query term matching the section's own
        # heading is a stronger relevance signal than a body-text match.
        # Only boosts pids already scored above — never introduces new ones.
        query_tokens = set(query.lower().split())
        for pid in list(scores.keys()):
            heading_path = parents[pid].metadata.get("heading_path") or []
            heading_text = " ".join(heading_path).lower()
            if heading_text and any(tok in heading_text for tok in query_tokens):
                scores[pid] += 2.0

        # Sort parents by score DESC
        ranked_parent_ids = sorted(
            scores.keys(),
            key=lambda pid: scores[pid],
            reverse=True,
        )

        # Page diversity: keep only the highest-scored section per page (by
        # url), even though pgvector and BM25 hits are already merged here.
        # pgvector is page-diverse by construction (_run_pgvector's
        # DISTINCT ON), but BM25's chunk hits have no page-awareness and can
        # surface several sections of the same rich page — deduping the
        # final ranking here covers both signals without touching BM25.
        seen_sources = set()
        diverse_parent_ids = []
        for pid in ranked_parent_ids:
            source = parents[pid].metadata.get("source")
            if source in seen_sources:
                continue
            seen_sources.add(source)
            diverse_parent_ids.append(pid)

        return [parents[pid] for pid in diverse_parent_ids]


class LLMRag:
    """LLM prompt chaining and structured parsing helpers.
    Handles history and bookmark response variants.
    """

    def __init__(self):
        """Initialize prompts, providers, and the base LLM.
        Keeps shared dependencies ready for chained calls.
        """
        self.rag = HybridRAGService()
        self.prompts = Prompts()
        self.llm_provider = LLMProvider()
        self.base_llm = self.llm_provider.get_rag_llm()

    def _llm_response(self, llm, flag: str = "history") -> Runnable:
        """Build the response chain for the specified flag.
        Returns a runnable that produces plain text output.
        """
        if flag == "history":
            prompt = self.prompts.history_prompt()
            chain = (
                {
                    "context": RunnablePassthrough(),
                    "url": RunnablePassthrough(),
                    "date": RunnablePassthrough(),
                }
                | prompt
                | llm
                | StrOutputParser()
            )
        elif flag == "bookmark":
            prompt = self.prompts.bookmark_prompt()
            chain = (
                {"context": RunnablePassthrough(), "url": RunnablePassthrough()}
                | prompt
                | llm
                | StrOutputParser()
            )
        elif flag == "combined":
            prompt = self.prompts.combined_prompt()
            chain = (
                {
                    "context": RunnablePassthrough(),
                    "url": RunnablePassthrough(),
                    "date": RunnablePassthrough(),
                }
                | prompt
                | llm
                | StrOutputParser()
            )
        else:
            logger.error("unknown flag")
            raise ValueError(f"Unknown flag '{flag}'")
        return chain

    def structure(self, flag: str = "history") -> Runnable:
        """Build a structured parsing chain for the given flag.
        Uses a retrying model and a JSON output parser.
        """
        if flag == "history":
            parser = JsonOutputParser(pydantic_object=Ans_history)
        elif flag == "bookmark":
            parser = JsonOutputParser(pydantic_object=Ans_bookmark)
        elif flag == "combined":
            parser = JsonOutputParser(pydantic_object=Ans_combined)
        else:
            raise ValueError(f"Unknown flag '{flag}'")
        promptParser = self.prompts.parser_prompt(parser, flag)
        model_with_retry = self.base_llm.with_retry(
            stop_after_attempt=3,
            wait_exponential_jitter=True,
        )
        pchain = promptParser | model_with_retry | parser
        return pchain

    def _invoke_chain(
        self, context: str, date: Optional[str], url: str, flag: str, chain: Runnable
    ) -> str:
        """Invoke a chain with the correct input mapping.
        Includes date for history/combined and omits it for bookmarks.
        """
        if flag in ("history", "combined"):
            return chain.invoke({"context": context, "date": date, "url": url})
        return chain.invoke({"context": context, "url": url})

    def safe_invoke_llm_response(
        self, context: str, date: Optional[str], url: str, flag: str = "history"
    ) -> Tuple[Any, str]:
        """Invoke the LLM response chain with fallback.
        Returns the response text and model identifier used.
        """
        try:
            chain = self._llm_response(llm=self.base_llm, flag=flag)
            result = self._invoke_chain(
                context=context, date=date, url=url, flag=flag, chain=chain
            )
            return result, settings.rag_provider
        except Exception as exc:
            logger.warning(
                "Primary LLM failed, falling back to %s: %s",
                settings.rag_fallback_provider,
                exc,
            )
            try:
                llm_fallback = self.llm_provider.get_rag_fallback_llm()
                chain = self._llm_response(llm=llm_fallback, flag=flag)
                result = self._invoke_chain(
                    context=context, date=date, url=url, flag=flag, chain=chain
                )
                return result, settings.rag_fallback_provider
            except Exception as e:
                logger.error("Both LLM failed")
                raise RuntimeError("All LLM providers failed") from e
