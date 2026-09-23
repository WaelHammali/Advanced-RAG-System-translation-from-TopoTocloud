"""Static types for the RAG boundary, not runtime architecture schemas."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

JSONObject = dict[str, Any]


class KnowledgeRecord(TypedDict):
    rule_id: str
    source: str
    heading: str
    text: str
    mode: str
    phase: str


class Retriever(Protocol):
    """Allow callers to inject retrieval without coupling to a concrete backend."""

    def retrieve(self, architecture: JSONObject) -> list[KnowledgeRecord]: ...
