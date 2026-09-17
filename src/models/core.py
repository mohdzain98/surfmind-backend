"""Core request/response and data models for the API.
Defines Pydantic schemas used across controllers and services.
"""

from typing import Any, List, Optional

from pydantic import AliasChoices, BaseModel, Field, model_validator


class Document:
    """Lightweight document container used by retrieval services.
    Stores page content and metadata for downstream processing.
    """

    def __init__(self, page_content, metadata):
        """Create a document with content and metadata.
        Keeps data minimal for retrieval and post-processing steps.
        """
        self.page_content = page_content
        self.metadata = metadata

    def __repr__(self):
        """Return a readable debug representation of the document.
        Helps trace content and metadata during development.
        """
        return f"Document(page_content={self.page_content}, metadata={self.metadata})"


class Ans_history(BaseModel):
    """Structured output schema for history responses.
    Captures the date and URL extracted from content.
    """

    date: str = Field(description="The date of the context")
    url: str = Field(description="the url of the context")


class Ans_bookmark(BaseModel):
    """Structured output schema for bookmark responses.
    Captures the URL extracted from content.
    """

    url: str = Field(description="the url of the context")


class Ans_combined(BaseModel):
    """Structured output schema for combined history+bookmark responses.
    Captures the URL, optional date, and source type.
    """

    url: str = Field(description="the url of the context")
    date: Optional[str] = Field(
        default=None, description="the date of the context if available"
    )
    source_type: str = Field(description="the source type: history or bookmark")


class HistoryItem(BaseModel):
    """Schema for a single history record in client payloads.

    Represents one heading-scoped section of a page (not necessarily the
    whole page) once the frontend ships section extraction. The heading
    fields are optional and unset by today's client — ingestion falls back
    to treating the item as a whole-page single section.
    """

    url: str
    content: str
    date: str | int | None = None
    domain: str = None
    folder: str = None
    title: str = None
    heading_path: List[str] | None = None
    heading_level: int | None = None
    section_index: int | None = None


def _flatten_nested_sections(raw_items: Any) -> Any:
    """Expand one-item-per-bookmark payloads into one item per section.

    A bookmark item's `content` can arrive as a list of per-heading section
    dicts (`{content, heading_path, heading_level, section_index}`) sharing
    one outer `url`/`title`/`folder`/`domain`/`date`, instead of the flat
    one-item-per-section shape `HistoryItem` expects. Splitting it here, at
    the request boundary, means `HistoryItem.content` can stay a plain
    `str` and every downstream consumer (ingestion, retrieval) keeps
    working with the same flat per-section list it always has. Items whose
    `content` is already a string pass through unchanged.
    """
    if not isinstance(raw_items, list):
        return raw_items
    flattened = []
    for raw in raw_items:
        content = raw.get("content") if isinstance(raw, dict) else None
        if isinstance(content, list):
            shared = {k: v for k, v in raw.items() if k != "content"}
            for section in content:
                flattened.append({**shared, **section})
        else:
            flattened.append(raw)
    return flattened


class DataRequest(BaseModel):
    """Request schema for saving user data to cache.
    Includes user identity, flag type, and history items.
    For flag="combined", bookmarks field carries the bookmark items.
    """

    user_id: str = Field(validation_alias=AliasChoices("browser_uuid", "userId"))
    flag: str = Field(default="history")
    data: List[HistoryItem]
    bookmarks: List[HistoryItem] = []

    @model_validator(mode="before")
    @classmethod
    def _flatten_bookmark_sections(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        for field_name in ("data", "bookmarks"):
            if field_name in values:
                values[field_name] = _flatten_nested_sections(values[field_name])
        return values


class SearchRequest(BaseModel):
    """Request schema for initiating a search query.
    Includes user identity, query text, and content flag.
    """

    user_id: str = Field(validation_alias=AliasChoices("browser_uuid", "userId"))
    query: str
    flag: str


class SearchResponse(BaseModel):
    """Response schema for search results.
    Includes raw result text, structured output, and matched docs.
    """

    success: bool
    result: str
    format: dict | None = None
    model: str | None = None
    docs: list


class RecentSearchesRequest(BaseModel):
    """Request schema for fetching an account's recent searches.

    POST with the id in the body, not GET with a query param — same
    reasoning as SyncStatusRequest: MV3 service workers don't reliably
    send an Origin header on GET requests, breaking nginx's
    Origin-allowlist check upstream.
    """

    browser_uuid: str = Field(validation_alias=AliasChoices("browser_uuid", "userId"))
    limit: int = 5


class GenerateCodeRequest(BaseModel):
    """Request schema for issuing a cross-browser sync pairing code."""

    browser_uuid: str = Field(
        validation_alias=AliasChoices("browser_uuid", "browserUuid")
    )


class RedeemCodeRequest(BaseModel):
    """Request schema for redeeming a sync pairing code."""

    browser_uuid: str = Field(
        validation_alias=AliasChoices("browser_uuid", "browserUuid")
    )
    code: str


class UnlinkRequest(BaseModel):
    """Request schema for unlinking a browser back to its own solo account."""

    browser_uuid: str = Field(
        validation_alias=AliasChoices("browser_uuid", "browserUuid")
    )


class SyncStatusRequest(BaseModel):
    """Request schema for checking a browser's sync/link status.

    POST with the id in the body, not GET with a query param — MV3 service
    workers don't reliably send an Origin header on GET requests, which
    breaks nginx's Origin-allowlist check upstream. POST requests carry
    Origin consistently across browser contexts.
    """

    browser_uuid: str = Field(
        validation_alias=AliasChoices("browser_uuid", "browserUuid")
    )
