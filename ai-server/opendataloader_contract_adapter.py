"""Adapter from OpenDataLoader JSON elements to DocuMind RAG contracts.

This module is a side-effect free smoke adapter.  It does not write to
ChromaDB, call endpoints, or change the runtime upload path.  Its job is to
prove that OpenDataLoader JSON can be normalized into the existing
ParsedBlock, SectionNode, SourceBlock, and TableFact contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
from rag_contracts import (
    JsonValue,
    PageSpan,
    ParsedBlock,
    SectionNode,
    SourceBlock,
    TableFact,
)


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
    # 다음 쪽으로 넘길 상태: 쪽 끝의 제목 경로와, 쪽이 표로 끝나면 그 표의 이름(이어지는 표가 이어받는다)
    last_heading_path: tuple[str, ...] = ()
    last_table_caption: str | None = None


@dataclass(frozen=True)
class _ElementCandidate:
    element: Mapping[str, Any]
    element_type: str
    text: str
    metadata: dict[str, Any]
    confidence: float
    fallback_reasons: tuple[str, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()
    merged_columns: frozenset[int] = frozenset()


def adapt_opendataloader_json_page(
    page_content: str | Mapping[str, Any],
    *,
    document_id: str | int,
    source: str,
    document_format: str = "pdf",
    block_index_offset: int = 0,
    initial_heading_path: Sequence[str] = (),
    previous_table_caption: str | None = None,
) -> OpenDataLoaderAdapterResult:
    """Convert one OpenDataLoader JSON page into RAG contract candidates.

    ``initial_heading_path``와 ``previous_table_caption``은 앞 쪽 결과의 ``last_heading_path``,
    ``last_table_caption``을 넘겨받아, 제목이 없는 쪽의 표와 쪽을 넘어 이어지는 표도 표 이름을 갖게 한다.
    """
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
    heading_path: list[str] = list(initial_heading_path)
    linked_caption_by_content_id = _linked_caption_by_content_id(candidates)
    last_table_caption: str | None = None

    start_index = max(0, block_index_offset) + 1
    for block_index, candidate in enumerate(candidates, start=start_index):
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
            existing_section = section_by_id.get(section_node.section_id)
            section_by_id[section_node.section_id] = (
                _merge_section_nodes(existing_section, section_node)
                if existing_section is not None
                else section_node
            )

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
            position = block_index - start_index
            table_caption = _table_caption_for_candidate(
                candidate,
                heading_path,
                linked_caption_by_content_id,
                preceding_caption=_preceding_short_line_caption(candidates, position),
                continued_caption=previous_table_caption if _is_first_content_on_page(candidates, position) else None,
            )
            last_table_caption = table_caption
            table_facts.extend(
                _table_facts_from_rows(
                    candidate.table_rows,
                    merged_columns=candidate.merged_columns,
                    document_id=document_id,
                    table_index=block_index,
                    source_block_id=source_block.source_block_id,
                    caption=table_caption,
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
        last_heading_path=tuple(heading_path),
        last_table_caption=last_table_caption if candidates and candidates[-1].element_type == "table" else None,
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
                merged_columns=_vertically_merged_columns(element) if element_type == "table" else frozenset(),
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
        if element_type == "list":
            # 목록은 항목 글로만 읽으므로, 항목 아래에 든 표는 따로 꺼내 표 사실을 만들게 한다(#264)
            yield from _tables_in_list(element)
        if element_type in _SUBTREE_STOP_ELEMENT_TYPES:
            continue
        if nested:
            yield from _iter_elements(nested)


_LIST_ITEM_CAPTION_KEY = "_documind_list_item_caption"


def _tables_in_list(list_element: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """목록 항목 아래(안쪽 목록 포함)에 든 표를 항목 제목과 함께 꺼낸다. 표 칸 안의 표는 꺼내지 않는다."""
    items = list_element.get("list items") or list_element.get("items") or []
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return
    for item in items:
        if not isinstance(item, Mapping):
            continue
        title = _clean_text(str(item.get("content") or "").replace("\x00", " "))
        yield from _tables_under(_nested_text_children(item), title)


def _tables_under(elements: Iterable[Mapping[str, Any]], title: str) -> Iterable[Mapping[str, Any]]:
    for element in elements:
        element_type = _normalize_element_type(element.get("type"))
        if element_type == "table":
            yield {**element, _LIST_ITEM_CAPTION_KEY: title} if title else element
        elif element_type == "list":
            yield from _tables_in_list(element)
        else:
            yield from _tables_under(_nested_text_children(element), title)


def _merge_section_nodes(existing: SectionNode, incoming: SectionNode) -> SectionNode:
    return replace(
        existing,
        page_span=_merge_page_spans(existing.page_span, incoming.page_span),
        block_ids=_append_unique(existing.block_ids, incoming.block_ids),
    )


def _merge_page_spans(left: PageSpan | None, right: PageSpan | None) -> PageSpan | None:
    if left is None:
        return right
    if right is None:
        return left

    starts = [value for value in (left.start, right.start) if value is not None]
    ends = [value for value in (left.end, right.end) if value is not None]
    return PageSpan(
        start=min(starts) if starts else None,
        end=max(ends) if ends else None,
    )


def _append_unique(left: Sequence[str], right: Sequence[str]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in (*left, *right):
        if value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return tuple(merged)


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
            # PDF 글자 층의 빈 문자(\x00)가 칸 글 끝이나 공백 옆에 섞여 나와, 칸 값·열 이름·행 이름의 재료인 칸 글에서 지운다
            cell_texts = tuple(
                _clean_text(slots.get(index, "").replace("\x00", " "))
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
        ("linked content id", "opendataloader_linked_content_id"),
        ("linked_content_id", "opendataloader_linked_content_id"),
        ("linked content ids", "opendataloader_linked_content_ids"),
        ("linked_content_ids", "opendataloader_linked_content_ids"),
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


def _linked_caption_by_content_id(
    candidates: Sequence[_ElementCandidate],
) -> dict[str, str]:
    caption_by_content_id: dict[str, str] = {}
    for candidate in candidates:
        if candidate.element_type != "caption":
            continue
        for linked_content_id in _linked_content_ids(candidate.element):
            caption_by_content_id.setdefault(linked_content_id, candidate.text)
    return caption_by_content_id


def _table_caption_for_candidate(
    candidate: _ElementCandidate,
    heading_path: Sequence[str],
    linked_caption_by_content_id: Mapping[str, str],
    *,
    preceding_caption: str | None = None,
    continued_caption: str | None = None,
) -> str | None:
    # 순서: PDF 도구가 표에 이어 준 캡션 → 표를 품은 목록 항목의 제목 → 표 바로 앞의 짧은 제목 줄
    #       → 앞 쪽에서 이어지는 표의 이름 → 제목 경로
    # PDF 빈 문자(\x00)만 든 후보는 정리하면 빈 글이 되므로 건너뛰고 다음 순위로 넘어간다
    for content_id in _element_ids(candidate.element):
        caption = _caption_text(linked_caption_by_content_id.get(content_id))
        if caption:
            return caption
    list_item_caption = candidate.element.get(_LIST_ITEM_CAPTION_KEY)
    if isinstance(list_item_caption, str) and _is_caption_like_line(list_item_caption):
        caption = _caption_text(list_item_caption)
        if caption:
            return caption
    heading_caption = _caption_text(_table_caption(heading_path))
    if heading_caption and not _is_table_name_shape(heading_caption):
        # 제목 경로 끝이 문장이나 기호뿐인 줄이면 표 이름으로 쓰지 않는다
        heading_caption = None
    for option in (preceding_caption, continued_caption, heading_caption):
        caption = _caption_text(option)
        if caption:
            return caption
    return None


def _caption_text(value: str | None) -> str | None:
    cleaned = _clean_text(str(value or "").replace("\x00", " "))
    return cleaned or None


_CAPTION_LOOKBACK = 2
_CAPTION_MAX_CHARS = 80


def _preceding_short_line_caption(candidates: Sequence[_ElementCandidate], position: int) -> str | None:
    # 마크다운 길(main._extract_table_caption)과 같은 규칙: 표 바로 앞 몇 요소에서 마지막 짧은 줄을 표 이름으로 쓴다.
    # 80자 이하, 주석(※)이나 날짜가 둘 이상 든 줄은 빼고, 다른 표를 만나면 멈춘다.
    for index in range(position - 1, max(position - 1 - _CAPTION_LOOKBACK, -1), -1):
        previous = candidates[index]
        if previous.element_type == "table":
            return None
        lines = [_clean_text(line) for line in previous.text.splitlines() if _clean_text(line)]
        if not lines:
            continue
        # PDF 글자 층의 빈 문자(\x00)가 낱말 사이에 끼어 나오는 경우가 있어 표 이름에서는 지운다
        line = _clean_text(lines[-1].replace("\x00", " ")).lstrip("- ").strip()
        if _is_caption_like_line(line):
            return line
        return None
    return None


def _is_caption_like_line(line: str) -> bool:
    return (
        bool(line)
        and len(line) <= _CAPTION_MAX_CHARS
        and not line.startswith("※")
        and not line.endswith(">")
        and len(re.findall(r"\d{4}\.\d", line)) < 2
        and _is_table_name_shape(line)
    )


# 표 이름이 될 수 없는 줄 모양: 단위 표시 「(단위: 명)」, 기준 시점 「’25년 4월 기준」, 구분 줄 「- 아 래 -」, 문장 「…합니다.」
_UNIT_LINE = re.compile(r"[(（\[［].*단위.*[)）\]］]")
_BASIS_LINE = re.compile(r"[(（\[［]?\s*[’‘'`]?[\d\s.,/~·년월일-]+기준\s*[)）\]］]?")
_MARKER_LINE = re.compile(r"[-–—\s]*(아\s*래|다\s*음)[-–—\s]*")
_SENTENCE_END = re.compile(r"(니다|다\.)$")


def _is_table_name_shape(line: str) -> bool:
    """줄 모양만 보고 표 이름이 될 수 있는지 가린다(낱말 내용은 보지 않는다)."""
    text = line.strip()
    if _UNIT_LINE.fullmatch(text) or _BASIS_LINE.fullmatch(text) or _MARKER_LINE.fullmatch(text):
        return False
    if _SENTENCE_END.search(text):
        return False
    # 로마 숫자, 번호, 기호만 있는 줄(「IV」, 「5.」, 「❍」)은 이름 글자가 없다
    words = re.findall(r"[가-힣]+|[A-Za-z]+", text)
    return any(not re.fullmatch(r"[IVXLivxl]+", word) for word in words)


def _is_first_content_on_page(candidates: Sequence[_ElementCandidate], position: int) -> bool:
    return all(candidate.element_type == "table" for candidate in candidates[:position])


def _element_ids(element: Mapping[str, Any]) -> tuple[str, ...]:
    return _id_values(element, _ELEMENT_ID_KEYS)


def _linked_content_ids(element: Mapping[str, Any]) -> tuple[str, ...]:
    return _id_values(element, _LINKED_CONTENT_ID_KEYS)


def _id_values(element: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key not in element:
            continue
        for value in _iter_id_values(element[key]):
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
    return tuple(values)


def _iter_id_values(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key in _ELEMENT_ID_KEYS:
            if key in value:
                yield from _iter_id_values(value[key])
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_id_values(item)
        return
    cleaned = _clean_text(value)
    if cleaned:
        yield cleaned


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
        if title:
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
    # PDF 빈 문자(\x00)는 공백으로 바꾼다. 정리해서 빈 글이 되는 제목(글자 층에 제목 글이 없는 PDF)도
    # 새 절이 시작됐다는 뜻이라, 앞 제목을 끝내고 그 자리를 빈 글로 둔다(지난 제목이 다음 표의 이름이 되지 않게)
    title = _clean_text(str(title or "").replace("\x00", " "))
    path = list(current_path[: max(level - 1, 0)])
    path.append(title)
    return path[:6]


def _table_facts_from_rows(
    rows: Sequence[Sequence[str]],
    *,
    merged_columns: frozenset[int] = frozenset(),
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
    label_column, group_columns = _row_label_layout(data_rows, merged_columns)
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

        row_label = _row_label(row, label_column) or f"row {row_offset + 1}"
        for column_index, value in enumerate(row):
            if column_index == label_column:
                continue
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
            # 가로로 합친 칸은 묶음 열과 행 이름 열에 같은 글로 채워져(예: 「미참여」 한 칸) 경로에 거듭 들어가므로 한 번만 둔다
            row_header_path = tuple(
                dict.fromkeys(
                    part
                    for part in (current_row_group, *_row_group_path(row, group_columns), row_label)
                    if part
                )
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


_SERIAL_MAX = 999
_SERIAL_MIN_ROWS = 3


def _row_label_layout(
    data_rows: Sequence[Sequence[str]],
    merged_columns: frozenset[int] = frozenset(),
) -> tuple[int, tuple[int, ...]]:
    """행 이름으로 쓸 열과, 그 왼쪽의 묶음 열을 고른다. 고를 수 없으면 첫 열(0, ())이다.

    왼쪽부터 보며 연번 열(첫 열이 1씩 늘어나는 세 자리 이하 정수)과 묶음 열(본문에서 세로로 합친 칸이 있고 여러 행이
    같은 값인 글 열, 예: 계열, 학부)은 건너뛰고, 칸 대부분이 숫자가 아닌 글이고 그 글이 대부분 서로 다른 첫 열을 행 이름으로 쓴다.
    연번이나 묶음 열을 건너뛴 뒤의 숫자 열(호실 등)도 건너뛴다. 건너뛴 묶음 열의 값은 행 경로로 남긴다.
    첫 열이 연번이 아닌 숫자 열이면 첫 열을 그대로 쓴다(연도, 띄엄띄엄한 번호 등).
    """
    width = max((len(row) for row in data_rows), default=0)
    groups: list[int] = []
    skipped_leading = False
    for column in range(width):
        values = [_clean_text(row[column]) for row in data_rows if column < len(row)]
        texts = [value for value in values if _is_fact_value(value) and not _table_cell_has_compact_value(value)]
        if len(texts) >= 0.5 * len(data_rows):
            # 행 이름은 행을 가려야 한다: 그 글이 대부분 서로 다르면 행 이름, 여러 행이 같으면 묶음 열
            if len(set(texts)) >= 0.8 * len(texts):
                return column, tuple(groups)
            if column in merged_columns:
                groups.append(column)
                continue
            if skipped_leading or groups:
                # 연번이나 묶음 열을 건너뛴 뒤라면 값이 겹치는 글 열(관리소속 등)도 건너뛴다. 경로에는 넣지 않는다
                continue
            # 첫 열부터 합친 칸이 아닌데 값이 겹치는 글 열(참여 여부 같은 상태 열)이면 묶음으로 보지 않고 멈춘다
            break
        if column == 0 and _is_serial_column(values):
            skipped_leading = True
            continue
        if skipped_leading or groups:
            # 연번이나 묶음 열을 건너뛴 뒤에는 호실 같은 숫자 열도 건너뛰고 이름 열을 찾는다
            continue
        break
    return 0, ()


def _vertically_merged_columns(element: Mapping[str, Any]) -> frozenset[int]:
    """둘째 행부터 세로로 합친 칸(row span ≥ 2)이 있는 열 번호(0부터). 첫 행의 합친 칸은 머리글일 수 있어 뺀다."""
    columns: set[int] = set()
    rows = element.get("rows") or []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return frozenset()
    for row_position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        row_number = _positive_int_from_mapping(row, _ROW_NUMBER_KEYS, default=row_position + 1)
        if row_number <= 1:
            continue
        for cell in row.get("cells") or []:
            if not isinstance(cell, Mapping):
                continue
            if _positive_int_from_mapping(cell, _ROW_SPAN_KEYS, default=1) < 2:
                continue
            start = _zero_based_column_index(cell, fallback=0)
            span = _positive_int_from_mapping(cell, _COLUMN_SPAN_KEYS, default=1)
            columns.update(range(start, start + span))
    return frozenset(columns)


def _is_serial_column(values: Sequence[str]) -> bool:
    numbers_text = [value for value in values if value]
    if len(numbers_text) < _SERIAL_MIN_ROWS or not all(re.fullmatch(r"\d{1,3}", value) for value in numbers_text):
        return False
    numbers = [int(value) for value in numbers_text]
    steps = sum(1 for a, b in zip(numbers, numbers[1:]) if b == a + 1)
    return numbers[-1] <= _SERIAL_MAX and steps >= 0.8 * (len(numbers) - 1)


def _row_group_path(row: Sequence[str], group_columns: Sequence[int]) -> tuple[str, ...]:
    path: list[str] = []
    for column in group_columns:
        value = _clean_text(row[column]) if column < len(row) else ""
        # 「―」처럼 글자가 없는 칸은 경로에 넣지 않는다
        if value and re.search(r"\w", value) and (not path or path[-1] != value):
            path.append(value)
    return tuple(path)


def _row_label(row: Sequence[str], label_column: int) -> str:
    if label_column < len(row) and row[label_column]:
        return row[label_column]
    return row[0] if row and row[0] else ""


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


_CONTRACT_ELEMENT_TYPES = {
    "heading",
    "paragraph",
    "table",
    "list",
    "caption",
    "formula",
}
_CONTAINER_ONLY_ELEMENT_TYPES = {"text_block"}
_SUBTREE_STOP_ELEMENT_TYPES = {
    "table",
    "list",
    "header",
    "footer",
    "page_header",
    "page_footer",
}
_ELEMENT_TYPE_ALIASES = {
    "text_block": "paragraph",
    "list_item": "paragraph",
}
_ELEMENT_ID_KEYS = (
    "id",
    "content id",
    "content_id",
    "element id",
    "element_id",
)
_LINKED_CONTENT_ID_KEYS = (
    "linked content id",
    "linked_content_id",
    "linked content ids",
    "linked_content_ids",
    "linked content",
    "linked_content",
    "linked id",
    "linked_id",
    "linked element id",
    "linked_element_id",
)
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
