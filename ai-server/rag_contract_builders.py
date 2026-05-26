"""Small builders that adapt current chunk data into RAG contracts.

The functions in this module are deliberately side-effect free.  They do not
write to ChromaDB and they do not change the existing query pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha1
import re
from typing import Any, Sequence

from rag_contracts import (
    BBox,
    JsonValue,
    PageSpan,
    ParsedBlock,
    RetrievalChunk,
    SectionNode,
    SourceCitation,
    SourceBlock,
    SourceReference,
    TextSpan,
)


def build_parsed_block(
    *,
    document_id: str | int,
    document_format: str,
    text: str,
    block_index: int,
    metadata: Mapping[str, Any] | None = None,
    block_type: str | None = None,
    parser_confidence: float | None = None,
) -> ParsedBlock:
    """Create a ParsedBlock from current parser/chunk text and metadata."""
    safe_metadata = sanitize_metadata(metadata or {})
    page_span = page_span_from_metadata(safe_metadata)
    page = page_span.start if page_span else _coerce_int(safe_metadata.get("page"))
    resolved_block_type = block_type or str(safe_metadata.get("block_type") or "text")

    return ParsedBlock(
        block_id=_contract_id(document_id, "block", block_index),
        document_id=str(document_id),
        document_format=document_format,
        block_type=resolved_block_type,
        text=text,
        page=page,
        bbox=_bbox_from_metadata(safe_metadata),
        reading_order=block_index,
        parser_confidence=parser_confidence,
        metadata=safe_metadata,
    )


def build_source_block(
    parsed_block: ParsedBlock,
    *,
    source_index: int | None = None,
    section_id: str | None = None,
) -> SourceBlock:
    """Create an immutable SourceBlock from one ParsedBlock."""
    page_span = page_span_from_metadata(parsed_block.metadata)
    if page_span is None and parsed_block.page is not None:
        page_span = PageSpan(parsed_block.page, parsed_block.page)
    bbox_span = (parsed_block.bbox,) if parsed_block.bbox is not None else ()
    index = parsed_block.reading_order if source_index is None else source_index

    return SourceBlock(
        source_block_id=_contract_id(parsed_block.document_id, "source", index or 0),
        document_id=parsed_block.document_id,
        raw_text=parsed_block.text,
        page_span=page_span,
        block_ids=(parsed_block.block_id,),
        bbox_span=bbox_span,
        section_id=section_id,
    )


def build_source_citation(
    source_block: SourceBlock,
    *,
    source: str,
    excerpt_chars: int = 200,
) -> SourceCitation:
    """Create a user-visible citation from SourceBlock raw text."""
    excerpt, span = _source_excerpt(source_block.raw_text, excerpt_chars)
    return SourceCitation(
        citation_id=f"{source_block.source_block_id}:citation",
        document_id=source_block.document_id,
        source=source,
        page_label=_page_label_from_span(source_block.page_span),
        source_block_id=source_block.source_block_id,
        excerpt=excerpt,
        span=span,
    )


def build_source_reference(
    source_block: SourceBlock,
    *,
    lookup_id: str,
    source_collection: str = "documents",
    lookup_strategy: str = "current_chunk_id",
    runtime_connection: str = "trace_only",
    available_in_current_runtime: bool = True,
    metadata_keys: Sequence[str] = (),
    future_metadata_keys: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> SourceReference:
    """Create a lookup reference from a retrieval candidate to source raw text."""
    return SourceReference(
        source_block_id=source_block.source_block_id,
        document_id=source_block.document_id,
        source_collection=source_collection,
        lookup_id=lookup_id,
        lookup_strategy=lookup_strategy,
        runtime_connection=runtime_connection,
        available_in_current_runtime=available_in_current_runtime,
        metadata_keys=tuple(metadata_keys),
        future_metadata_keys=tuple(future_metadata_keys),
        notes=tuple(notes),
    )


def build_retrieval_chunk(
    parsed_block: ParsedBlock,
    source_block: SourceBlock,
    section_node: SectionNode | None = None,
    *,
    retrieval_index: int | None = None,
) -> RetrievalChunk:
    """Create a RetrievalChunk preview without changing stored index text."""
    section_path = section_node.path if section_node else ()
    trusted_section = bool(section_node and section_path_quality(section_path) == "ok")
    retrieval_text = _compose_retrieval_text(
        section_path if trusted_section else (),
        parsed_block.text,
    )
    index = parsed_block.reading_order if retrieval_index is None else retrieval_index

    return RetrievalChunk(
        retrieval_chunk_id=_contract_id(parsed_block.document_id, "retrieval", index or 0),
        document_id=parsed_block.document_id,
        retrieval_text=retrieval_text,
        source_block_ids=(source_block.source_block_id,),
        section_ids=(section_node.section_id,) if section_node and trusted_section else (),
        strategy="section_prefixed_raw" if trusted_section else "raw",
        chunk_role=str(parsed_block.metadata.get("chunk_role") or "raw"),
    )


def build_section_node(parsed_block: ParsedBlock) -> SectionNode | None:
    """Create a SectionNode from Header 1..6 metadata when a path exists."""
    path = header_path_from_metadata(parsed_block.metadata)
    if not path:
        return None

    parent_path = path[:-1]
    return SectionNode(
        section_id=_section_id(parsed_block.document_id, path),
        document_id=parsed_block.document_id,
        title=path[-1],
        level=len(path),
        parent_id=_section_id(parsed_block.document_id, parent_path) if parent_path else None,
        path=path,
        page_span=page_span_from_metadata(parsed_block.metadata),
        block_ids=(parsed_block.block_id,),
    )


def page_span_from_metadata(metadata: Mapping[str, Any]) -> PageSpan | None:
    """Read page_start/page_end/page metadata into a PageSpan."""
    page_start = _coerce_int(metadata.get("page_start"))
    page_end = _coerce_int(metadata.get("page_end"))
    page = _coerce_int(metadata.get("page"))

    start = page_start if page_start is not None else page
    end = page_end if page_end is not None else start
    if start is None:
        return None
    return PageSpan(start=start, end=end)


def header_path_from_metadata(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    """Return Header 1..6 metadata as an ordered path."""
    path: list[str] = []
    for level in range(1, 7):
        value = str(metadata.get(f"Header {level}") or "").strip()
        if value:
            path.append(value)
    return tuple(path)


def section_path_quality(path: Sequence[str]) -> str:
    """Return whether a section path looks usable for trace diagnostics."""
    warnings = section_path_warnings(path)
    if "missing_section_path" in warnings:
        return "missing"
    return "suspect" if warnings else "ok"


def section_path_warnings(path: Sequence[str]) -> tuple[str, ...]:
    """Return generic warnings for section paths that look like table values."""
    if not path:
        return ("missing_section_path",)

    warnings: set[str] = set()
    for component in path:
        normalized = re.sub(r"\s+", " ", str(component or "").strip())
        if not normalized:
            warnings.add("empty_section_component")
            continue
        if _TABLE_VALUE_LIKE_SECTION_PATTERN.fullmatch(normalized):
            warnings.add("numeric_value_section_component")
        if "|" in normalized or "<br" in normalized.lower():
            warnings.add("table_markup_section_component")
        if len(normalized) > 80:
            warnings.add("overlong_section_component")
    return tuple(sorted(warnings))


def section_path_component_is_suspect(component: object) -> bool:
    """Return True when one section component should not be trusted as a heading."""
    warnings = set(section_path_warnings((str(component or "").strip(),)))
    return bool(warnings & _SECTION_PATH_COMPONENT_BLOCKING_WARNINGS)


def sanitize_metadata(metadata: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Keep only JSON-safe metadata values for contract serialization."""
    safe: dict[str, JsonValue] = {}
    for key, value in metadata.items():
        safe_value = _to_safe_json_value(value)
        if safe_value is not _UNSUPPORTED:
            safe[str(key)] = safe_value
    return safe


def _contract_id(document_id: str | int, kind: str, index: int) -> str:
    return f"doc-{document_id}:{kind}-{index:06d}"


def _section_id(document_id: str | int, path: tuple[str, ...]) -> str:
    path_digest = sha1("\x1f".join(path).encode("utf-8")).hexdigest()[:12]
    return f"doc-{document_id}:section-{path_digest}"


def _compose_retrieval_text(section_path: Sequence[str], raw_text: str) -> str:
    sections = [
        str(component).strip()
        for component in section_path
        if str(component).strip()
    ]
    text_parts = []
    if sections:
        text_parts.append(" > ".join(sections))
    if raw_text.strip():
        text_parts.append(raw_text.strip())
    return "\n".join(text_parts)


def _page_label_from_span(page_span: PageSpan | None) -> str:
    if page_span is None or page_span.start is None:
        return ""
    if page_span.end is None or page_span.end == page_span.start:
        return f"page {page_span.start}"
    return f"pages {page_span.start}-{page_span.end}"


def _source_excerpt(raw_text: str, max_chars: int) -> tuple[str, TextSpan | None]:
    stripped = str(raw_text or "").strip()
    if not stripped:
        return "", None

    limit = max(0, int(max_chars))
    excerpt_body = stripped[:limit].rstrip() if limit else ""
    excerpt = excerpt_body if len(stripped) <= limit else f"{excerpt_body}..."
    start = str(raw_text).find(excerpt_body) if excerpt_body else 0
    if start < 0:
        start = 0
    return excerpt, TextSpan(start=start, end=start + len(excerpt_body))


def _bbox_from_metadata(metadata: Mapping[str, Any]) -> BBox | None:
    bbox = metadata.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return tuple(float(value) for value in bbox)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _Unsupported:
    pass


_UNSUPPORTED = _Unsupported()

_NUMERIC_SECTION_VALUE_UNITS = (
    "명",
    "점",
    "일",
    "개",
    "건",
    "회",
    "차",
    "%",
    "학점",
    "시간",
    "쪽",
    "페이지",
)
_NUMERIC_SECTION_UNIT_PATTERN = "|".join(
    re.escape(unit) for unit in _NUMERIC_SECTION_VALUE_UNITS
)
# Korean currency values often combine a magnitude word with "원": 만원, 억원, 조원.
_KOREAN_CURRENCY_UNIT_PATTERN = r"(?:[십백천만억조경]+)?원"
_TABLE_VALUE_LIKE_SECTION_PATTERN = re.compile(
    rf"^[\d\s,./~:·ㆍ+-]+"
    rf"(?:{_KOREAN_CURRENCY_UNIT_PATTERN}|{_NUMERIC_SECTION_UNIT_PATTERN})?$"
)
_SECTION_PATH_COMPONENT_BLOCKING_WARNINGS = {
    "numeric_value_section_component",
    "table_markup_section_component",
}


def _to_safe_json_value(value: Any) -> JsonValue | _Unsupported:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        items: list[JsonValue] = []
        for item in value:
            safe_item = _to_safe_json_value(item)
            if safe_item is _UNSUPPORTED:
                return _UNSUPPORTED
            items.append(safe_item)
        return items
    if isinstance(value, Mapping):
        safe_dict: dict[str, JsonValue] = {}
        for key, item in value.items():
            safe_item = _to_safe_json_value(item)
            if safe_item is _UNSUPPORTED:
                return _UNSUPPORTED
            safe_dict[str(key)] = safe_item
        return safe_dict
    return _UNSUPPORTED
