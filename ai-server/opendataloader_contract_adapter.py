"""Adapter from OpenDataLoader JSON elements to DocuMind RAG contracts.

This module is a side-effect free smoke adapter.  It does not write to
ChromaDB, call endpoints, or change the runtime upload path.  Its job is to
prove that OpenDataLoader JSON can be normalized into the existing
ParsedBlock, SectionNode, SourceBlock, and TableFact contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from rag_contract_builders import (
    build_parsed_block,
    build_section_node,
    build_source_block,
    build_table_cell_fact,
    infer_table_value_type,
)
from rag_contracts import JsonValue, ParsedBlock, SectionNode, SourceBlock, TableFact


@dataclass(frozen=True)
class OpenDataLoaderAdapterDiagnostic:
    """A non-fatal adapter warning or fallback note for audit output."""

    code: str
    block_id: str | None = None
    element_type: str | None = None
    message: str = ""
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenDataLoaderAdapterResult:
    """Contract candidates produced from one OpenDataLoader JSON page."""

    parsed_blocks: tuple[ParsedBlock, ...]
    section_nodes: tuple[SectionNode, ...]
    source_blocks: tuple[SourceBlock, ...]
    table_facts: tuple[TableFact, ...]
    diagnostics: tuple[OpenDataLoaderAdapterDiagnostic, ...] = ()


@dataclass(frozen=True)
class _ElementCandidate:
    element: Mapping[str, Any]
    element_type: str
    text: str
    metadata: dict[str, Any]
    confidence: float
    fallback_reasons: tuple[str, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()


def adapt_opendataloader_json_page(
    page_content: str | Mapping[str, Any],
    *,
    document_id: str | int,
    source: str,
    document_format: str = "pdf",
) -> OpenDataLoaderAdapterResult:
    """Convert one OpenDataLoader JSON page into RAG contract candidates."""
    page_data = _load_page_data(page_content)
    page_number = _coerce_int(page_data.get("page number")) or _coerce_int(
        page_data.get("page")
    )
    candidates = _collect_element_candidates(page_data)
    diagnostics: list[OpenDataLoaderAdapterDiagnostic] = []
    parsed_blocks: list[ParsedBlock] = []
    source_blocks: list[SourceBlock] = []
    section_by_id: dict[str, SectionNode] = {}
    table_facts: list[TableFact] = []
    heading_path: list[str] = []

    for block_index, candidate in enumerate(candidates, start=1):
        level = _heading_level(candidate.element)
        if candidate.element_type == "heading" and level is not None:
            heading_path = _updated_heading_path(heading_path, level, candidate.text)

        metadata = _metadata_for_candidate(
            candidate,
            page_number=page_number,
            source=source,
            heading_path=heading_path,
        )
        parsed_block = build_parsed_block(
            document_id=document_id,
            document_format=document_format,
            text=candidate.text,
            block_index=block_index,
            metadata=metadata,
            block_type=candidate.element_type,
            parser_confidence=candidate.confidence,
        )
        parsed_blocks.append(parsed_block)

        section_node = build_section_node(parsed_block)
        if section_node is not None:
            section_by_id.setdefault(section_node.section_id, section_node)

        source_block = build_source_block(
            parsed_block,
            source_index=block_index,
            section_id=section_node.section_id if section_node else None,
        )
        source_blocks.append(source_block)

        if candidate.fallback_reasons:
            diagnostics.append(
                OpenDataLoaderAdapterDiagnostic(
                    code="fallback_required",
                    block_id=parsed_block.block_id,
                    element_type=candidate.element_type,
                    message="OpenDataLoader JSON preserved text but scope is not safe enough to split automatically.",
                    metadata={"reasons": list(candidate.fallback_reasons)},
                )
            )

        if candidate.element_type == "table":
            table_facts.extend(
                _table_facts_from_rows(
                    candidate.table_rows,
                    document_id=document_id,
                    table_index=block_index,
                    source_block_id=source_block.source_block_id,
                    caption=_table_caption(heading_path),
                    header_path=heading_path,
                    diagnostics=diagnostics,
                    block_id=parsed_block.block_id,
                )
            )

    return OpenDataLoaderAdapterResult(
        parsed_blocks=tuple(parsed_blocks),
        section_nodes=tuple(section_by_id.values()),
        source_blocks=tuple(source_blocks),
        table_facts=tuple(table_facts),
        diagnostics=tuple(diagnostics),
    )


def render_table_facts_as_evidence_text(
    table_facts: Sequence[TableFact],
    *,
    max_facts: int = 12,
) -> str:
    """Render TableFact candidates as compact Korean evidence for an LLM prompt."""
    selected_facts = tuple(table_facts[: max(0, max_facts)])
    if not selected_facts:
        return ""

    lines: list[str] = ["[표 근거]"]
    current_table_key: tuple[str, str | None] | None = None
    for fact in selected_facts:
        table_key = (fact.table_id, fact.caption)
        if table_key != current_table_key:
            current_table_key = table_key
            caption = _clean_text(fact.caption or _last_text(fact.header_path) or fact.table_id)
            lines.append(f"표 제목: {caption}")

        row_label = " > ".join(fact.row_header_path) if fact.row_header_path else fact.row_label
        column_label = " > ".join(fact.column_path) if fact.column_path else fact.column_label
        lines.append(
            f"- 행: {_clean_text(row_label)} / 열: {_clean_text(column_label)} / 값: {_clean_text(fact.value)}"
        )

    if len(table_facts) > len(selected_facts):
        lines.append(f"- 추가 표 근거 {len(table_facts) - len(selected_facts)}개는 생략했습니다.")
    return "\n".join(lines)


def _load_page_data(page_content: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(page_content, Mapping):
        return page_content
    decoded = json.loads(page_content)
    if not isinstance(decoded, Mapping):
        raise ValueError("OpenDataLoader JSON page must decode to an object")
    return decoded


def _collect_element_candidates(page_data: Mapping[str, Any]) -> tuple[_ElementCandidate, ...]:
    candidates: list[_ElementCandidate] = []
    for element in _iter_child_elements(page_data):
        element_type = _normalize_element_type(element.get("type"))
        if element_type not in _CONTRACT_ELEMENT_TYPES:
            continue

        table_rows = _table_rows(element) if element_type == "table" else ()
        text = _render_table_text(table_rows) if element_type == "table" else _element_text(element)
        if not text:
            continue

        fallback_reasons = _fallback_reasons(element, text, table_rows)
        candidates.append(
            _ElementCandidate(
                element=element,
                element_type=element_type,
                text=text,
                metadata=_base_element_metadata(element),
                confidence=_confidence(element, text, fallback_reasons),
                fallback_reasons=fallback_reasons,
                table_rows=table_rows,
            )
        )
    return tuple(candidates)


def _iter_child_elements(page_data: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    kids = page_data.get("kids") or page_data.get("children") or []
    if isinstance(kids, Sequence) and not isinstance(kids, (str, bytes)):
        yield from _iter_elements(kids)


def _iter_elements(elements: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        element_type = _normalize_element_type(element.get("type"))
        nested = _nested_text_children(element)
        if not _is_container_only_element(element, nested):
            yield element
        if element_type in {"table", "list"}:
            continue
        if nested:
            yield from _iter_elements(nested)


def _normalize_element_type(value: Any) -> str:
    normalized = _raw_element_type(value)
    return _ELEMENT_TYPE_ALIASES.get(normalized, normalized)


def _raw_element_type(value: Any) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().lower())


def _is_container_only_element(
    element: Mapping[str, Any],
    nested: Sequence[Mapping[str, Any]],
) -> bool:
    return bool(
        nested
        and _raw_element_type(element.get("type")) in _CONTAINER_ONLY_ELEMENT_TYPES
    )


def _element_text(element: Mapping[str, Any]) -> str:
    direct = _clean_text(element.get("content") or element.get("text") or "")
    if direct:
        nested_parts = [_element_text(child) for child in _nested_text_children(element)]
        return _join_text_parts([direct, *nested_parts])
    if _normalize_element_type(element.get("type")) == "list":
        return _join_text_parts(_list_item_texts(element))
    return _join_text_parts(_element_text(child) for child in _nested_text_children(element))


def _nested_text_children(element: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    nested = element.get("kids") or element.get("children") or []
    if not isinstance(nested, Sequence) or isinstance(nested, (str, bytes)):
        return ()
    return tuple(child for child in nested if isinstance(child, Mapping))


def _list_item_texts(element: Mapping[str, Any]) -> tuple[str, ...]:
    items = element.get("list items") or element.get("items") or []
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return ()
    texts: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            text = _element_text(item)
            if text:
                texts.append(text)
    return tuple(texts)


def _table_rows(element: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    rows = element.get("rows") or []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    resolved_rows: list[tuple[str, ...]] = []
    row_span_carry: dict[int, dict[int, str]] = {}
    for row_position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        row_number = _positive_int_from_mapping(
            row,
            _ROW_NUMBER_KEYS,
            default=row_position + 1,
        )
        slots: dict[int, str] = dict(row_span_carry.pop(row_number, {}))
        cells = row.get("cells") or []
        if not isinstance(cells, Sequence) or isinstance(cells, (str, bytes)):
            continue
        next_column_index = 0
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            fallback_column_index = _next_available_column_index(
                slots,
                next_column_index,
            )
            column_index = _zero_based_column_index(cell, fallback=fallback_column_index)
            column_span = _positive_int_from_mapping(cell, _COLUMN_SPAN_KEYS, default=1)
            row_span = _positive_int_from_mapping(cell, _ROW_SPAN_KEYS, default=1)
            cell_text = _element_text(cell)

            for span_offset in range(column_span):
                resolved_column_index = column_index + span_offset
                slots[resolved_column_index] = cell_text
                for row_offset in range(1, row_span):
                    carry_row_number = row_number + row_offset
                    row_span_carry.setdefault(carry_row_number, {})[
                        resolved_column_index
                    ] = cell_text

            next_column_index = max(next_column_index, column_index + column_span)

        if slots:
            width = max(slots) + 1
            cell_texts = tuple(
                _clean_text(slots.get(index, ""))
                for index in range(width)
            )
            if any(cell_texts):
                resolved_rows.append(cell_texts)
    return tuple(resolved_rows)


def _render_table_text(rows: Sequence[Sequence[str]]) -> str:
    return "\n".join(" | ".join(_clean_text(cell) for cell in row) for row in rows)


def _base_element_metadata(element: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "parser_name": "opendataloader_pdf",
        "opendataloader_type": _normalize_element_type(element.get("type")),
    }
    for source_key, target_key in (
        ("id", "opendataloader_element_id"),
        ("level", "opendataloader_level"),
        ("heading level", "opendataloader_heading_level"),
        ("numbering style", "opendataloader_numbering_style"),
        ("number of rows", "opendataloader_number_of_rows"),
        ("number of columns", "opendataloader_number_of_columns"),
        ("number of list items", "opendataloader_number_of_list_items"),
    ):
        if source_key in element:
            metadata[target_key] = element[source_key]
    page = _coerce_int(element.get("page number") or element.get("page"))
    if page is not None:
        metadata["page"] = page
        metadata["page_start"] = page
        metadata["page_end"] = page
    bbox = _bbox(element)
    if bbox is not None:
        metadata["bbox"] = list(bbox)
    return metadata


def _metadata_for_candidate(
    candidate: _ElementCandidate,
    *,
    page_number: int | None,
    source: str,
    heading_path: Sequence[str],
) -> dict[str, Any]:
    metadata = dict(candidate.metadata)
    metadata["source"] = source
    metadata["block_type"] = candidate.element_type
    if page_number is not None:
        metadata.setdefault("page", page_number)
        metadata.setdefault("page_start", page_number)
        metadata.setdefault("page_end", page_number)
    for index, title in enumerate(heading_path[:6], start=1):
        metadata[f"Header {index}"] = title
    if candidate.fallback_reasons:
        metadata["adapter_fallback_reasons"] = list(candidate.fallback_reasons)
    return metadata


def _heading_level(element: Mapping[str, Any]) -> int | None:
    explicit = _coerce_int(element.get("heading level"))
    if explicit is not None and explicit > 0:
        return min(explicit, 6)
    level = str(element.get("level") or "").strip().lower()
    if level in _NAMED_HEADING_LEVELS:
        return _NAMED_HEADING_LEVELS[level]
    parsed = _coerce_int(level)
    if parsed is not None and parsed > 0:
        return min(parsed, 6)
    return None


def _updated_heading_path(current_path: Sequence[str], level: int, title: str) -> list[str]:
    path = list(current_path[: max(level - 1, 0)])
    path.append(title)
    return path[:6]


def _table_facts_from_rows(
    rows: Sequence[Sequence[str]],
    *,
    document_id: str | int,
    table_index: int,
    source_block_id: str,
    caption: str | None,
    header_path: Sequence[str],
    diagnostics: list[OpenDataLoaderAdapterDiagnostic],
    block_id: str,
) -> tuple[TableFact, ...]:
    normalized_rows = tuple(
        tuple(_clean_text(cell) for cell in row)
        for row in rows
        if any(_clean_text(cell) for cell in row)
    )
    if len(normalized_rows) < 2:
        diagnostics.append(
            OpenDataLoaderAdapterDiagnostic(
                code="table_fact_skipped",
                block_id=block_id,
                element_type="table",
                message="Table did not have both a header row and a data row.",
            )
        )
        return ()

    header_row_count = _table_header_row_count(normalized_rows)
    header_rows = normalized_rows[:header_row_count]
    data_rows = normalized_rows[header_row_count:]
    column_paths = _table_column_paths(header_rows)
    facts: list[TableFact] = []
    current_row_group: str | None = None
    for row_offset, row in enumerate(data_rows, start=header_row_count):
        if _is_table_group_row(row):
            current_row_group = next((cell for cell in row if cell), None)
            diagnostics.append(
                OpenDataLoaderAdapterDiagnostic(
                    code="table_group_row_detected",
                    block_id=block_id,
                    element_type="table",
                    message="A table row with one label-like cell was kept as row_header_path context.",
                    metadata={"row_index": row_offset, "label": current_row_group or ""},
                )
            )
            continue

        row_label = row[0] if row and row[0] else f"row {row_offset + 1}"
        for column_index, value in enumerate(row[1:], start=1):
            if not _is_fact_value(value):
                continue
            skip_reason = _table_fact_value_skip_reason(value)
            if skip_reason:
                diagnostics.append(
                    OpenDataLoaderAdapterDiagnostic(
                        code="table_fact_value_skipped",
                        block_id=block_id,
                        element_type="table",
                        message="A table cell was not converted to TableFact because it is unsafe as a compact fact value.",
                        metadata={
                            "row_index": row_offset,
                            "column_index": column_index,
                            "reason": skip_reason,
                        },
                    )
                )
                continue
            column_path = (
                column_paths[column_index]
                if column_index < len(column_paths)
                else (f"column {column_index + 1}",)
            )
            column_label = " > ".join(column_path)
            row_header_path = (
                (current_row_group, row_label)
                if current_row_group
                else (row_label,)
            )
            facts.append(
                build_table_cell_fact(
                    document_id=document_id,
                    table_index=table_index,
                    row_index=row_offset,
                    column_index=column_index,
                    row_label=row_label,
                    column_label=column_label,
                    value=value,
                    source_block_id=source_block_id,
                    caption=caption,
                    row_header_path=row_header_path,
                    column_path=column_path,
                    header_path=tuple(header_path),
                    confidence=0.85,
                )
            )
    return tuple(facts)


def _is_fact_value(value: str) -> bool:
    cleaned = _clean_text(value)
    return bool(cleaned and cleaned not in _EMPTY_TABLE_VALUES)


def _table_header_row_count(rows: Sequence[Sequence[str]]) -> int:
    header_count = 1
    for row in rows[1:3]:
        previous_row = rows[header_count - 1]
        if _row_looks_like_header_extension(row, previous_row):
            header_count += 1
        else:
            break
    return header_count


def _row_looks_like_header_extension(
    row: Sequence[str],
    previous_row: Sequence[str] | None = None,
) -> bool:
    cells = [_clean_text(cell) for cell in row]
    non_empty = [cell for cell in cells if cell]
    if not non_empty:
        return False
    if cells and cells[0]:
        previous_first = _clean_text(previous_row[0]) if previous_row else ""
        if cells[0] != previous_first:
            return False
    return not any(_table_cell_has_compact_value(cell) for cell in non_empty)


def _table_column_paths(header_rows: Sequence[Sequence[str]]) -> tuple[tuple[str, ...], ...]:
    column_count = max((len(row) for row in header_rows), default=0)
    column_paths: list[tuple[str, ...]] = []
    for column_index in range(column_count):
        parts: list[str] = []
        for row in header_rows:
            cell = _clean_text(row[column_index] if column_index < len(row) else "")
            if cell and cell not in parts:
                parts.append(cell)
        column_paths.append(tuple(parts) if parts else (f"column {column_index + 1}",))
    return tuple(column_paths)


def _is_table_group_row(row: Sequence[str]) -> bool:
    cells = [_clean_text(cell) for cell in row]
    non_empty = [cell for cell in cells if cell]
    if len(non_empty) != 1:
        return False
    return not _table_cell_has_compact_value(non_empty[0])


def _table_fact_value_skip_reason(value: str) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned or cleaned in _EMPTY_TABLE_VALUES:
        return "empty_value"
    if len(cleaned) > _MAX_COMPACT_TEXT_FACT_CHARS and not _table_cell_has_compact_value(cleaned):
        return "overlong_text_value"
    return None


def _table_cell_has_compact_value(value: str) -> bool:
    value_type, _ = infer_table_value_type(_clean_text(value))
    return value_type in {"money", "count", "date", "number"}


def _table_caption(heading_path: Sequence[str]) -> str | None:
    return heading_path[-1] if heading_path else None


def _fallback_reasons(
    element: Mapping[str, Any],
    text: str,
    table_rows: Sequence[Sequence[str]],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if _has_adjacent_repeated_phrase(text):
        reasons.append("possible_parallel_content_merge")
    if _has_adjacent_repeated_label_suffix(text):
        reasons.append("possible_parallel_label_merge")
    if _normalize_element_type(element.get("type")) == "table" and not table_rows:
        reasons.append("table_without_rows")
    return tuple(reasons)


def _has_adjacent_repeated_phrase(text: str) -> bool:
    words = _clean_text(text).split()
    if len(words) < 2:
        return False
    max_width = min(4, len(words) // 2)
    for width in range(1, max_width + 1):
        for index in range(0, len(words) - (2 * width) + 1):
            if words[index : index + width] == words[index + width : index + (2 * width)]:
                return True
    return False


def _has_adjacent_repeated_label_suffix(text: str) -> bool:
    words = [
        re.sub(r"^[^\w가-힣]+|[^\w가-힣]+$", "", word)
        for word in _clean_text(text).split()
    ]
    words = [word for word in words if len(word) >= 4]
    for left, right in zip(words, words[1:]):
        if left == right:
            continue
        if left[-2:] == right[-2:]:
            return True
    return False


def _confidence(
    element: Mapping[str, Any],
    text: str,
    fallback_reasons: Sequence[str],
) -> float:
    if fallback_reasons:
        return 0.55
    if _bbox(element) is not None and text:
        return 0.9
    if text:
        return 0.75
    return 0.4


def _bbox(element: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    bbox = element.get("bounding box") or element.get("bbox")
    if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes)) or len(bbox) != 4:
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


def _positive_int_from_mapping(
    values: Mapping[str, Any],
    keys: Sequence[str],
    *,
    default: int,
) -> int:
    for key in keys:
        if key not in values:
            continue
        parsed = _coerce_int(values[key])
        if parsed is not None and parsed > 0:
            return parsed
    return default


def _zero_based_column_index(values: Mapping[str, Any], *, fallback: int) -> int:
    parsed = None
    for key in _COLUMN_NUMBER_KEYS:
        if key in values:
            parsed = _coerce_int(values[key])
            break
    if parsed is None:
        return fallback
    if parsed <= 0:
        return 0
    return parsed - 1


def _next_available_column_index(slots: Mapping[int, str], start: int) -> int:
    candidate = max(0, start)
    while candidate in slots:
        candidate += 1
    return candidate


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("<br>", " ")).strip()


def _join_text_parts(parts: Iterable[str]) -> str:
    return "\n".join(part for part in (_clean_text(part) for part in parts) if part)


def _last_text(values: Sequence[str]) -> str:
    for value in reversed(values):
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


_CONTRACT_ELEMENT_TYPES = {"heading", "paragraph", "table", "list"}
_CONTAINER_ONLY_ELEMENT_TYPES = {"text_block"}
_ELEMENT_TYPE_ALIASES = {
    "text_block": "paragraph",
    "list_item": "paragraph",
}
_NAMED_HEADING_LEVELS = {
    "doctitle": 1,
    "title": 1,
    "subtitle": 2,
}
_EMPTY_TABLE_VALUES = {"-", "–", "—", "ㆍ", ".", ""}
_MAX_COMPACT_TEXT_FACT_CHARS = 80
_ROW_NUMBER_KEYS = ("row number", "row_number", "row")
_COLUMN_NUMBER_KEYS = ("column number", "column_number", "col number", "col_number")
_ROW_SPAN_KEYS = ("row span", "row_span", "rowspan")
_COLUMN_SPAN_KEYS = ("column span", "column_span", "col span", "col_span", "colspan")
