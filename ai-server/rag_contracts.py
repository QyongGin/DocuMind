"""Typed RAG data contracts for the next structure-preserving pipeline.

This module is intentionally not wired into ``main.py`` yet.  It defines the
small, JSON-serializable contracts that future parser, retrieval, prompt, and
source-citation code can share without overloading LangChain ``Document``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class PageSpan:
    """A page range in a source document."""

    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class TextSpan:
    """A character range within a source block."""

    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class ParsedBlock:
    """The smallest parser-produced document block."""

    block_id: str
    document_id: str
    document_format: str
    block_type: str
    text: str
    page: int | None = None
    bbox: BBox | None = None
    reading_order: int | None = None
    parser_confidence: float | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class SectionNode:
    """A parent-child document section that gives blocks stable context."""

    section_id: str
    document_id: str
    title: str
    level: int
    parent_id: str | None = None
    path: tuple[str, ...] = ()
    page_span: PageSpan | None = None
    block_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceBlock:
    """An immutable raw source span used for citations and audits."""

    source_block_id: str
    document_id: str
    raw_text: str
    page_span: PageSpan | None = None
    block_ids: tuple[str, ...] = ()
    bbox_span: tuple[BBox, ...] = ()
    section_id: str | None = None


@dataclass(frozen=True)
class SourceReference:
    """A lookup pointer from retrieval candidates back to source raw text."""

    source_block_id: str
    document_id: str
    source_collection: str
    lookup_id: str
    lookup_strategy: str
    runtime_connection: str = "trace_only"
    available_in_current_runtime: bool = True
    metadata_keys: tuple[str, ...] = ()
    future_metadata_keys: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalChunk:
    """A text unit optimized for embedding and BM25 retrieval."""

    retrieval_chunk_id: str
    document_id: str
    retrieval_text: str
    source_block_ids: tuple[str, ...] = ()
    section_ids: tuple[str, ...] = ()
    strategy: str = "raw"
    chunk_role: str = "raw"


@dataclass(frozen=True)
class TableFact:
    """A typed table evidence unit connected to its original source block."""

    fact_id: str
    fact_type: str
    table_id: str
    row_label: str
    column_label: str
    value: str
    source_block_id: str
    value_type: str = "text"
    unit: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    row_header_path: tuple[str, ...] = ()
    column_path: tuple[str, ...] = ()
    header_path: tuple[str, ...] = ()
    caption: str | None = None
    legend: str | None = None
    note: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class QueryIntent:
    """A typed query-understanding result that can replace scattered heuristics."""

    intent_id: str
    query: str
    intent: str | None
    subject_terms: tuple[str, ...] = ()
    primary_terms: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()
    intent_terms: tuple[str, ...] = ()
    extraction_method: str = "rule_based"
    vocabulary_source: str = "INTENT_QUERY_TERMS"
    runtime_connection: str = "trace_only"
    confidence: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    """A unified retrieval candidate after vector, BM25, and fact lookup."""

    candidate_id: str
    retrieval_chunk_id: str
    scores: dict[str, float] = field(default_factory=dict)
    methods: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    source_block_ids: tuple[str, ...] = ()
    diagnostics: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectedContextItem:
    """One evidence item selected for final LLM context construction."""

    candidate_id: str
    prompt_text: str
    fact_ids: tuple[str, ...] = ()
    source_block_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectedContext:
    """The final evidence contract that can be serialized into a prompt."""

    context_id: str
    items: tuple[SelectedContextItem, ...] = ()
    prompt_text: str = ""
    supporting_fact_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class SourceCitation:
    """A user-visible citation derived from SourceBlock, not retrieval text."""

    citation_id: str
    document_id: str
    source: str
    page_label: str
    source_block_id: str
    excerpt: str
    span: TextSpan | None = None
    confidence: float | None = None


def contract_to_dict(contract: object) -> dict[str, JsonValue]:
    """Convert one contract dataclass into a JSON-serializable dictionary."""
    converted = _to_json_value(contract)
    if not isinstance(converted, dict):
        raise TypeError(f"Expected dataclass contract, got {type(contract).__name__}")
    return converted


def _to_json_value(value: Any) -> JsonValue:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            contract_field.name: _to_json_value(getattr(value, contract_field.name))
            for contract_field in fields(value)
        }
    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported JSON contract value: {type(value).__name__}")
