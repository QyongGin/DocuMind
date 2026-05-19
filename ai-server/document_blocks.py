from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from langchain_core.documents import Document


BOILERPLATE_MIN_REPEAT = 3
BOILERPLATE_MIN_LENGTH = 20


class BlockType(str, Enum):
    """문서 형식과 무관하게 청킹 전에 다룰 수 있는 블록 종류다."""

    HEADING = "heading"
    TABLE = "table"
    LIST = "list"
    TEXT = "text"
    DECORATIVE = "decorative"


@dataclass(frozen=True)
class DocumentBlock:
    """parser(파서)가 만든 텍스트를 청킹 전에 공통으로 표현하는 단위다."""

    block_type: BlockType
    text: str
    metadata: dict[str, Any]


@dataclass
class DocumentCleanupStats:
    """문서 정리 단계에서 무엇을 줄였는지 업로드 로그로 남기기 위한 통계다."""

    input_documents: int = 0
    output_documents: int = 0
    removed_empty_table_blocks: int = 0
    removed_boilerplate_lines: int = 0
    removed_empty_documents: int = 0

    def as_log_fields(self) -> dict[str, int]:
        """logger에 넣기 쉬운 dict 형태로 변환한다."""
        return {
            "input_documents": self.input_documents,
            "output_documents": self.output_documents,
            "removed_empty_table_blocks": self.removed_empty_table_blocks,
            "removed_boilerplate_lines": self.removed_boilerplate_lines,
            "removed_empty_documents": self.removed_empty_documents,
        }


def clean_documents_for_chunking(documents: Sequence[Document]) -> tuple[list[Document], DocumentCleanupStats]:
    """청킹 전에 형식 공통 노이즈를 제거한다.

    이 함수는 PDF, DOCX, PPTX, XLSX 모두 LangChain Document로 변환된 뒤에 동작한다.
    원본 문장이나 실제 표 행은 유지하고, 비어 있는 markdown table(마크다운 표)과
    여러 페이지에 반복되는 boilerplate(상용구) line만 줄인다.
    """

    stats = DocumentCleanupStats(input_documents=len(documents))
    without_empty_tables: list[Document] = []

    for document in documents:
        cleaned_text, removed_table_blocks = _remove_empty_table_blocks(document.page_content)
        stats.removed_empty_table_blocks += removed_table_blocks
        if not cleaned_text.strip():
            stats.removed_empty_documents += 1
            continue

        metadata = dict(document.metadata)
        if removed_table_blocks:
            metadata["cleanup_removed_empty_table_blocks"] = removed_table_blocks
        without_empty_tables.append(Document(page_content=cleaned_text, metadata=metadata))

    repeated_lines = _find_repeated_boilerplate_lines(without_empty_tables)
    if not repeated_lines:
        stats.output_documents = len(without_empty_tables)
        return without_empty_tables, stats

    cleaned_documents: list[Document] = []
    kept_repeated_lines: set[str] = set()
    for document in without_empty_tables:
        cleaned_text, removed_lines = _remove_repeated_boilerplate_lines(
            document.page_content,
            repeated_lines,
            kept_repeated_lines,
        )
        stats.removed_boilerplate_lines += removed_lines
        if not cleaned_text.strip():
            stats.removed_empty_documents += 1
            continue

        metadata = dict(document.metadata)
        if removed_lines:
            metadata["cleanup_removed_boilerplate_lines"] = removed_lines
        cleaned_documents.append(Document(page_content=cleaned_text, metadata=metadata))

    stats.output_documents = len(cleaned_documents)
    return cleaned_documents, stats


def split_document_blocks(text: str, metadata: dict[str, Any] | None = None) -> list[DocumentBlock]:
    """텍스트를 heading/table/list/text/decorative 블록으로 얕게 분류한다."""

    metadata = dict(metadata or {})
    blocks: list[DocumentBlock] = []
    current_lines: list[str] = []
    current_type: BlockType | None = None

    def flush() -> None:
        nonlocal current_lines, current_type
        if current_type is None or not current_lines:
            return
        block_text = "\n".join(current_lines).strip()
        if block_text:
            blocks.append(DocumentBlock(block_type=current_type, text=block_text, metadata=dict(metadata)))
        current_lines = []
        current_type = None

    for line in text.splitlines():
        block_type = _classify_line(line)
        if current_type is not None and block_type != current_type:
            flush()
        current_type = block_type
        current_lines.append(line)

    flush()
    return blocks


def _find_repeated_boilerplate_lines(documents: Sequence[Document]) -> set[str]:
    line_counts: Counter[str] = Counter()
    for document in documents:
        for line in document.page_content.splitlines():
            normalized = _normalize_line(line)
            if _is_boilerplate_candidate(normalized):
                line_counts[normalized] += 1

    return {
        line
        for line, count in line_counts.items()
        if count >= BOILERPLATE_MIN_REPEAT
    }


def _remove_repeated_boilerplate_lines(
    text: str,
    repeated_lines: set[str],
    kept_repeated_lines: set[str],
) -> tuple[str, int]:
    cleaned_lines: list[str] = []
    removed_count = 0

    for line in text.splitlines():
        normalized = _normalize_line(line)
        if normalized in repeated_lines:
            if normalized in kept_repeated_lines:
                removed_count += 1
                continue
            kept_repeated_lines.add(normalized)
        cleaned_lines.append(line)

    return _collapse_blank_lines(cleaned_lines), removed_count


def _remove_empty_table_blocks(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    removed_count = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        if not _is_markdown_table_line(line):
            cleaned_lines.append(line)
            index += 1
            continue

        table_block: list[str] = []
        while index < len(lines) and _is_markdown_table_line(lines[index]):
            table_block.append(lines[index])
            index += 1

        if _is_empty_table_block(table_block):
            removed_count += 1
            continue
        cleaned_lines.extend(table_block)

    return _collapse_blank_lines(cleaned_lines), removed_count


def _is_empty_table_block(lines: Sequence[str]) -> bool:
    if not lines:
        return False
    if not any(_is_table_separator(line) for line in lines):
        return False

    for line in lines:
        if _is_table_separator(line):
            continue
        cells = _table_cells(line)
        if any(cell for cell in cells):
            return False
    return True


def _classify_line(line: str) -> BlockType:
    normalized = _normalize_line(line)
    if not normalized:
        return BlockType.DECORATIVE
    if normalized.startswith("#"):
        return BlockType.HEADING
    if _is_markdown_table_line(normalized):
        return BlockType.TABLE
    if re.match(r"^[-*·]\s+", normalized) or re.match(r"^\d+[.)]\s+", normalized):
        return BlockType.LIST
    if _is_visual_or_layout_line(normalized):
        return BlockType.DECORATIVE
    return BlockType.TEXT


def _is_boilerplate_candidate(normalized_line: str) -> bool:
    if len(normalized_line) < BOILERPLATE_MIN_LENGTH:
        return False
    if normalized_line.startswith("#"):
        return False
    if _is_markdown_table_line(normalized_line):
        return False
    if _is_visual_or_layout_line(normalized_line):
        return False
    return True


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _collapse_blank_lines(lines: Sequence[str]) -> str:
    collapsed: list[str] = []
    blank_seen = False
    for line in lines:
        if line.strip():
            collapsed.append(line.rstrip())
            blank_seen = False
            continue
        if not blank_seen:
            collapsed.append("")
        blank_seen = True
    return "\n".join(collapsed).strip()


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _table_cells(line: str) -> list[str]:
    if not _is_markdown_table_line(line):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_visual_or_layout_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.fullmatch(r"[|:\-\s]+", stripped):
        return True
    if re.fullmatch(r"#+\s*\d{2,4}", stripped):
        return True
    if re.fullmatch(r"\d{1,4}", stripped):
        return True
    return False
