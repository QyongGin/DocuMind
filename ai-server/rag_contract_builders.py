"""Small builders that adapt current chunk data into RAG contracts.

The functions in this module are deliberately side-effect free.  They do not
write to ChromaDB and they do not change the existing query pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rag_contracts import BBox, JsonValue, PageSpan, ParsedBlock, SourceBlock


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
