"""Fast mode: retrieval-only search, no LLM calls.

Pure helper functions used by `CoreRetrieval.stream_fast_search` — kept out
of `main.py`/`rag.py` since neither owns strictness-preset resolution or
thresholding logic. See `docs/task_and_plans/fast_mode.md`.
"""

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from src.utility.settings import settings


def resolve_preset(strictness: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Resolve a client-sent strictness name to its preset values.

    Returns `(resolved_name, {"threshold", "max_results"})`. An unknown or
    missing name falls back to the configured default preset rather than
    erroring — the client sends a name, never a raw number, so presets can
    be retuned without breaking anyone's saved setting.
    """
    default_name = settings.fast_mode_default_preset
    resolved_name = (
        strictness if strictness in settings.fast_mode_preset_names else default_name
    )
    return resolved_name, settings.fast_mode_preset(resolved_name)


def clamp_max_results(requested: Optional[int], preset_default: int) -> int:
    """Clamp a client-sent `max_results` to `1..fast_mode_max_results_cap`.

    Missing, non-numeric, or out-of-range values fall back to the preset's
    own default rather than erroring — same "never fail on bad input"
    stance as `resolve_preset`.
    """
    cap = settings.fast_mode_max_results_cap
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return preset_default
    if value < 1 or value > cap:
        return preset_default
    return value


def apply_threshold(
    parents: List[Document], preset: Dict[str, Any]
) -> List[Tuple[Document, float]]:
    """Filter+rank parents by embedding similarity against `preset`.

    Similarity is `1 - vector_distance` (pgvector cosine distance, lower =
    closer) — the one signal with a stable, absolute scale, unlike
    `_map_to_parents`' rank-fused score. A parent with no `vector_distance`
    (BM25-only — never appeared in pgvector's own top-k for this query) is
    dropped: there's nothing to verify a floor against, and Fast mode would
    rather show nothing than an unverified match ("start conservative").

    Two floors apply, matching `fast_mode.md` section 3 — the preset's own
    absolute threshold, AND a floor relative to this query's own top hit
    (`fast_mode_relative_cutoff`) so a weak top result doesn't drag in a
    long tail of similarly-weak ones. Returns every passing `(doc,
    similarity)` pair, sorted best-first — callers slice to `max_results`.
    """
    scored: List[Tuple[Document, float]] = []
    for doc in parents:
        distance = doc.metadata.get("vector_distance")
        if distance is None:
            continue
        scored.append((doc, 1.0 - distance))

    if not scored:
        return []

    scored.sort(key=lambda pair: pair[1], reverse=True)
    top_similarity = scored[0][1]
    floor = max(
        preset["threshold"], top_similarity * settings.fast_mode_relative_cutoff
    )
    return [pair for pair in scored if pair[1] >= floor]


def serialize_fast_result(
    doc: Document,
    similarity: float,
    requesting_browser_uuid: str,
    device_names: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    """Build one Fast-mode result dict (see `fast_mode.md` section 4).

    `source_device_name` mirrors `core_controller._annotate_source_browser`'s
    "different browser" check, inlined here since Fast results have no
    nested `metadata` the way Standard's `docs` do.
    """
    source_browser_uuid = doc.metadata.get("source_browser_uuid")
    is_other_browser = bool(source_browser_uuid) and (
        source_browser_uuid != requesting_browser_uuid
    )
    return {
        "url": doc.metadata.get("source"),
        "title": doc.metadata.get("title") or "",
        "type": doc.metadata.get("type"),
        "score": round(similarity, 4),
        "heading_path": doc.metadata.get("heading_path") or [],
        "snippet": doc.page_content[:300],
        "source_device_name": (
            device_names.get(source_browser_uuid) if is_other_browser else None
        ),
    }
