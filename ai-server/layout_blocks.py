from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

from layout_confidence import (
    assess_parallel_layout_confidence,
    classify_parallel_row_role,
    is_text_bbox_split_candidate,
)


LAYOUT_SCHEMA_VERSION = 2
OPENDATALOADER_LAYOUT_MODE = "opendataloader_json"
OPENDATALOADER_LAYOUT_CHUNKING_MODE = "opendataloader_json_chunking"
OPENDATALOADER_LAYOUT_MODES = {
    OPENDATALOADER_LAYOUT_MODE,
    OPENDATALOADER_LAYOUT_CHUNKING_MODE,
}
OPENDATALOADER_PARSER_NAME = "opendataloader-pdf"
DEFAULT_LAYOUT_ROW_TOLERANCE = 12.0
DEFAULT_LAYOUT_CHUNK_PREVIEW_CHARS = 1200


@dataclass(frozen=True)
class RawLayoutBlock:
    """parser(파서) JSON에서 직접 읽은 원본 block(블록)이다."""

    page: int | None
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None
    depth: int
    raw_element_id: str
    fallback_reason: str | None = None
    parent_element_id: str | None = None
    ancestor_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayoutBlock:
    """청킹과 진단에서 공통으로 사용할 layout-aware block(레이아웃 인식 블록)이다."""

    page: int | None
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None
    normalized_bbox: tuple[float, float, float, float] | None
    page_width: float | None
    page_height: float | None
    depth: int
    raw_element_id: str
    text_hash: str
    parser_version: str
    confidence_reasons: tuple[str, ...]
    fallback_reason: str | None
    parent_element_id: str | None = None
    ancestor_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayoutExtractionStats:
    """layout 추출 결과를 로그와 sidecar에 남기기 위한 통계다."""

    parser_name: str
    parser_version: str
    pages: int
    total_blocks: int
    text_blocks: int
    bbox_blocks: int
    bbox_coverage: float
    parse_errors: int


@dataclass(frozen=True)
class LayoutExtractionResult:
    """layout block 목록과 추출 통계를 묶은 결과다."""

    blocks: list[LayoutBlock]
    stats: LayoutExtractionStats


@dataclass(frozen=True)
class LayoutSidecarResult:
    """layout sidecar(보조 저장 파일) 저장 결과다."""

    status: str
    store_key: str | None
    path: str | None
    block_count: int
    bbox_coverage: float
    fallback_reason: str | None


@dataclass(frozen=True)
class ParallelLayoutChunk:
    """병렬 layout(레이아웃) 페이지에서 만든 보조 검색 chunk(청크)다."""

    page: int | str
    text: str
    column_count: int
    confidence_score: int
    confidence_level: str
    row_count: int


def load_opendataloader_documents(pdf_path: Path, output_format: str, pages: str | None = None) -> list[Any]:
    """OpenDataLoader PDF loader를 지정 format으로 실행한다."""
    from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader

    loader_kwargs: dict[str, Any] = {
        "file_path": str(pdf_path),
        "format": output_format,
        "split_pages": True,
        "quiet": True,
    }
    if pages:
        loader_kwargs["pages"] = pages
    return OpenDataLoaderPDFLoader(**loader_kwargs).load()


def extract_opendataloader_layout(pdf_path: Path, pages: str | None = None) -> LayoutExtractionResult:
    """OpenDataLoader JSON 출력으로 LayoutBlock 목록을 만든다."""
    json_docs = load_opendataloader_documents(pdf_path, "json", pages)
    return parse_opendataloader_json_documents(json_docs)


def parse_opendataloader_json_documents(json_docs: list[Any]) -> LayoutExtractionResult:
    """OpenDataLoader JSON Document 목록을 공통 LayoutBlock schema로 변환한다."""
    parser_version = _opendataloader_parser_version()
    raw_blocks: list[RawLayoutBlock] = []

    for document_index, doc in enumerate(json_docs):
        page = _coerce_page(getattr(doc, "metadata", {}) or {})
        try:
            payload = json.loads(getattr(doc, "page_content", "") or "")
        except json.JSONDecodeError:
            raw_blocks.append(RawLayoutBlock(
                page=page,
                block_type="parse_error",
                text=(getattr(doc, "page_content", "") or "")[:200],
                bbox=None,
                depth=0,
                raw_element_id=f"document:{document_index}",
                fallback_reason="json_decode_error",
                parent_element_id=None,
                ancestor_types=(),
            ))
            continue

        raw_blocks.extend(_walk_layout_node(payload, page, (document_index,)))

    page_dimensions = _estimate_page_dimensions(raw_blocks)
    blocks = [
        _build_layout_block(raw_block, page_dimensions.get(raw_block.page), parser_version)
        for raw_block in raw_blocks
    ]
    stats = _build_layout_stats(blocks, parser_version)
    return LayoutExtractionResult(blocks=blocks, stats=stats)


def build_layout_summary(
    blocks: list[LayoutBlock],
    markdown_summaries: dict[int | str, dict[str, Any]],
    row_tolerance: float,
    preview_chars: int,
) -> dict[str, Any]:
    """markdown 요약과 layout block을 합쳐 페이지별 진단 요약을 만든다."""
    blocks_by_page: dict[int | str, list[LayoutBlock]] = defaultdict(list)
    for block in blocks:
        page = block.page if block.page is not None else "unknown"
        blocks_by_page[page].append(block)

    pages = sorted(set(markdown_summaries) | set(blocks_by_page), key=lambda item: str(item))
    page_summaries: list[dict[str, Any]] = []
    for page in pages:
        page_blocks = blocks_by_page.get(page, [])
        blocks_with_bbox = [block for block in page_blocks if block.bbox is not None]
        parallel_row_candidates = find_parallel_row_candidates(
            page_blocks,
            row_tolerance,
            preview_chars,
        )
        confidence = assess_parallel_layout_confidence(page_blocks, parallel_row_candidates)
        page_summaries.append({
            "page": page,
            "markdown": markdown_summaries.get(page, {}),
            "json": {
                "blocks": len(page_blocks),
                "text_blocks": sum(1 for block in page_blocks if block.text),
                "bbox_blocks": len(blocks_with_bbox),
                "types": dict(Counter(block.block_type for block in page_blocks).most_common()),
                "estimated_column_count": estimate_layout_column_count(page_blocks, parallel_row_candidates),
                "parallel_row_candidates": parallel_row_candidates,
                "parallel_layout_confidence": confidence,
            },
        })

    return {
        "pages": page_summaries,
        "totals": {
            "markdown_pages": len(markdown_summaries),
            "json_blocks": len(blocks),
            "json_text_blocks": sum(1 for block in blocks if block.text),
            "json_bbox_blocks": sum(1 for block in blocks if block.bbox is not None),
            "json_types": dict(Counter(block.block_type for block in blocks).most_common()),
            "split_ready_pages": _split_ready_page_count(page_summaries),
            "split_ready_rows": _split_ready_row_count(page_summaries),
            "body_ready_rows": _confidence_metric_sum(page_summaries, "body_ready_rows"),
            "table_like_candidate_rows": _confidence_metric_sum(page_summaries, "table_like_candidate_rows"),
            "icon_like_candidate_rows": _confidence_metric_sum(page_summaries, "icon_like_candidate_rows"),
            "table_ancestor_candidate_rows": _confidence_metric_sum(page_summaries, "table_ancestor_candidate_rows"),
            "parent_region_low_pages": _parent_region_level_count(page_summaries, "low"),
        },
    }


def validate_layout_expectations(report: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    """layout golden case 기대 조건을 검사한다."""
    checks: list[dict[str, Any]] = []
    totals = report.get("totals") or {}
    page_summaries = report.get("pages") or []
    parallel_row_count = _parallel_row_candidate_count(page_summaries)

    if "min_json_bbox_blocks" in expectations:
        actual = int(totals.get("json_bbox_blocks") or 0)
        expected = int(expectations["min_json_bbox_blocks"])
        checks.append({
            "name": "min_json_bbox_blocks",
            "expected": expected,
            "actual": actual,
            "passed": actual >= expected,
        })

    if "min_parallel_row_candidates" in expectations:
        actual = parallel_row_count
        expected = int(expectations["min_parallel_row_candidates"])
        checks.append({
            "name": "min_parallel_row_candidates",
            "expected": expected,
            "actual": actual,
            "passed": actual >= expected,
        })

    if "max_parallel_row_candidates" in expectations:
        actual = parallel_row_count
        expected = int(expectations["max_parallel_row_candidates"])
        checks.append({
            "name": "max_parallel_row_candidates",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "expected_layout_column_count" in expectations:
        actual_values = [
            int((page.get("json") or {}).get("estimated_column_count") or 0)
            for page in page_summaries
        ]
        expected = int(expectations["expected_layout_column_count"])
        checks.append({
            "name": "expected_layout_column_count",
            "expected": expected,
            "actual": actual_values,
            "passed": expected in actual_values,
        })

    if "min_json_type_counts" in expectations:
        json_types = totals.get("json_types") or {}
        for block_type, expected_value in expectations["min_json_type_counts"].items():
            actual = int(json_types.get(block_type) or 0)
            expected = int(expected_value)
            checks.append({
                "name": f"min_json_type_count:{block_type}",
                "expected": expected,
                "actual": actual,
                "passed": actual >= expected,
            })

    if "min_split_ready_pages" in expectations:
        actual = int(totals.get("split_ready_pages") or 0)
        expected = int(expectations["min_split_ready_pages"])
        checks.append({
            "name": "min_split_ready_pages",
            "expected": expected,
            "actual": actual,
            "passed": actual >= expected,
        })

    if "max_split_ready_pages" in expectations:
        actual = int(totals.get("split_ready_pages") or 0)
        expected = int(expectations["max_split_ready_pages"])
        checks.append({
            "name": "max_split_ready_pages",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "min_split_ready_rows" in expectations:
        actual = int(totals.get("split_ready_rows") or 0)
        expected = int(expectations["min_split_ready_rows"])
        checks.append({
            "name": "min_split_ready_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual >= expected,
        })

    if "max_split_ready_rows" in expectations:
        actual = int(totals.get("split_ready_rows") or 0)
        expected = int(expectations["max_split_ready_rows"])
        checks.append({
            "name": "max_split_ready_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "min_body_ready_rows" in expectations:
        actual = int(totals.get("body_ready_rows") or 0)
        expected = int(expectations["min_body_ready_rows"])
        checks.append({
            "name": "min_body_ready_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual >= expected,
        })

    if "max_body_ready_rows" in expectations:
        actual = int(totals.get("body_ready_rows") or 0)
        expected = int(expectations["max_body_ready_rows"])
        checks.append({
            "name": "max_body_ready_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "max_table_like_candidate_rows" in expectations:
        actual = int(totals.get("table_like_candidate_rows") or 0)
        expected = int(expectations["max_table_like_candidate_rows"])
        checks.append({
            "name": "max_table_like_candidate_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "max_table_ancestor_candidate_rows" in expectations:
        actual = int(totals.get("table_ancestor_candidate_rows") or 0)
        expected = int(expectations["max_table_ancestor_candidate_rows"])
        checks.append({
            "name": "max_table_ancestor_candidate_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "max_parent_region_low_pages" in expectations:
        actual = int(totals.get("parent_region_low_pages") or 0)
        expected = int(expectations["max_parent_region_low_pages"])
        checks.append({
            "name": "max_parent_region_low_pages",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    if "max_icon_like_candidate_rows" in expectations:
        actual = int(totals.get("icon_like_candidate_rows") or 0)
        expected = int(expectations["max_icon_like_candidate_rows"])
        checks.append({
            "name": "max_icon_like_candidate_rows",
            "expected": expected,
            "actual": actual,
            "passed": actual <= expected,
        })

    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def _parallel_row_candidate_count(page_summaries: list[dict[str, Any]]) -> int:
    return sum(
        len((page.get("json") or {}).get("parallel_row_candidates") or [])
        for page in page_summaries
    )


def _split_ready_page_count(page_summaries: list[dict[str, Any]]) -> int:
    return sum(
        1
        for page in page_summaries
        if ((page.get("json") or {}).get("parallel_layout_confidence") or {}).get("eligible_for_split")
    )


def _split_ready_row_count(page_summaries: list[dict[str, Any]]) -> int:
    return sum(
        int(((page.get("json") or {}).get("parallel_layout_confidence") or {}).get("split_ready_rows") or 0)
        for page in page_summaries
    )


def _confidence_metric_sum(page_summaries: list[dict[str, Any]], metric_name: str) -> int:
    return sum(
        int(((page.get("json") or {}).get("parallel_layout_confidence") or {}).get(metric_name) or 0)
        for page in page_summaries
    )


def _parent_region_level_count(page_summaries: list[dict[str, Any]], level: str) -> int:
    return sum(
        1
        for page in page_summaries
        if (((page.get("json") or {}).get("parallel_layout_confidence") or {}).get("parent_region") or {}).get("level") == level
    )


def skipped_layout_sidecar(reason: str) -> LayoutSidecarResult:
    """layout 처리를 건너뛴 결과를 만든다."""
    return LayoutSidecarResult(
        status="skipped",
        store_key=None,
        path=None,
        block_count=0,
        bbox_coverage=0.0,
        fallback_reason=reason,
    )


def errored_layout_sidecar(reason: str) -> LayoutSidecarResult:
    """layout 처리 실패 결과를 만든다."""
    return LayoutSidecarResult(
        status="error",
        store_key=None,
        path=None,
        block_count=0,
        bbox_coverage=0.0,
        fallback_reason=reason,
    )


def store_layout_sidecar(
    result: LayoutExtractionResult,
    store_dir: Path,
    document_id: int,
    source: str,
    layout_mode: str,
) -> LayoutSidecarResult:
    """추출한 layout block을 문서별 sidecar JSON 파일로 저장한다."""
    store_dir.mkdir(parents=True, exist_ok=True)
    store_key = f"documents/{document_id}.layout.json"
    output_path = store_dir / store_key
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": LAYOUT_SCHEMA_VERSION,
        "document_id": str(document_id),
        "source": source,
        "layout_mode": layout_mode,
        "stats": asdict(result.stats),
        "blocks": [asdict(block) for block in result.blocks],
    }
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(output_path)

    return LayoutSidecarResult(
        status="stored",
        store_key=store_key,
        path=str(output_path),
        block_count=result.stats.total_blocks,
        bbox_coverage=result.stats.bbox_coverage,
        fallback_reason=None,
    )


def remove_layout_sidecar(store_dir: Path, document_id: int) -> int:
    """문서 삭제 시 layout sidecar 파일도 함께 제거한다."""
    removed_count = 0
    for path in (store_dir / "documents").glob(f"{document_id}.layout.json*"):
        if path.is_file():
            path.unlink()
            removed_count += 1
    return removed_count


def build_parallel_layout_chunks(
    blocks: list[LayoutBlock],
    row_tolerance: float = DEFAULT_LAYOUT_ROW_TOLERANCE,
    preview_chars: int = DEFAULT_LAYOUT_CHUNK_PREVIEW_CHARS,
) -> list[ParallelLayoutChunk]:
    """split-ready page(분리 가능 페이지)를 병렬 구조 보조 chunk로 변환한다."""
    chunks: list[ParallelLayoutChunk] = []
    blocks_by_page: dict[int | str, list[LayoutBlock]] = defaultdict(list)
    for block in blocks:
        page = block.page if block.page is not None else "unknown"
        blocks_by_page[page].append(block)

    for page, page_blocks in sorted(blocks_by_page.items(), key=lambda item: str(item[0])):
        row_candidates = find_parallel_row_candidates(page_blocks, row_tolerance, preview_chars)
        confidence = assess_parallel_layout_confidence(page_blocks, row_candidates)
        if not confidence.get("eligible_for_split"):
            continue

        column_count = int(confidence.get("dominant_column_count") or 0)
        split_rows = _split_ready_body_rows(row_candidates, column_count)
        if column_count < 2 or not split_rows:
            continue

        text = _format_parallel_layout_chunk(page, page_blocks, split_rows, column_count, confidence)
        if not text:
            continue

        chunks.append(ParallelLayoutChunk(
            page=page,
            text=text,
            column_count=column_count,
            confidence_score=int(confidence.get("score") or 0),
            confidence_level=str(confidence.get("level") or "none"),
            row_count=len(split_rows),
        ))
    return chunks


def _split_ready_body_rows(row_candidates: list[dict[str, Any]], column_count: int) -> list[dict[str, Any]]:
    rows = []
    for candidate in row_candidates:
        if str(candidate.get("role")) != "body":
            continue
        if candidate.get("has_table_ancestor"):
            continue
        if int(candidate.get("distinct_columns") or 0) != column_count:
            continue
        if len(candidate.get("texts") or []) < column_count:
            continue
        rows.append(candidate)
    return sorted(rows, key=lambda item: float(item.get("normalized_y_center") or 0), reverse=True)


def _format_parallel_layout_chunk(
    page: int | str,
    page_blocks: list[LayoutBlock],
    split_rows: list[dict[str, Any]],
    column_count: int,
    confidence: dict[str, Any],
) -> str:
    column_lines: list[list[str]] = [[] for _ in range(column_count)]
    for row in split_rows:
        label = _label_for_parallel_row(page_blocks, row) or "본문"
        label = _collapse_repeated_phrase(label)
        for column_index, value in enumerate((row.get("texts") or [])[:column_count]):
            cleaned_value = _clean_layout_chunk_text(str(value))
            if cleaned_value:
                column_lines[column_index].append(f"- {label}: {cleaned_value}")

    if not any(column_lines):
        return ""

    lines = [
        "레이아웃 병렬 청크",
        f"페이지: {page}",
        f"열 수: {column_count}",
        f"layout_confidence: {confidence.get('level')} ({confidence.get('score')})",
    ]
    common_titles = _common_top_texts(page_blocks, split_rows)
    if common_titles:
        lines.append("공통 상단 텍스트:")
        lines.extend(f"- {_clean_layout_chunk_text(title)}" for title in common_titles)

    for index, values in enumerate(column_lines, start=1):
        if not values:
            continue
        lines.append(f"열 {index}:")
        lines.extend(values)
    return "\n".join(lines)


def _common_top_texts(page_blocks: list[LayoutBlock], split_rows: list[dict[str, Any]], limit: int = 3) -> list[str]:
    top_row_y = max(float(row.get("normalized_y_center") or 0) for row in split_rows)
    headings: list[tuple[float, str]] = []
    for block in page_blocks:
        if block.block_type.lower() != "heading" or not block.text or block.normalized_bbox is None:
            continue
        row_center = _layout_row_center(block)
        if row_center is None or row_center <= top_row_y:
            continue
        if _looks_like_page_footer(block):
            continue
        headings.append((row_center, block.text))

    headings.sort(key=lambda item: item[0], reverse=True)
    result: list[str] = []
    for _, text in headings:
        cleaned = _clean_layout_chunk_text(text)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _label_for_parallel_row(page_blocks: list[LayoutBlock], row: dict[str, Any]) -> str:
    row_y = row.get("normalized_y_center")
    if row_y is None:
        return ""
    row_y_float = float(row_y)
    candidates: list[tuple[float, str]] = []
    for block in page_blocks:
        if not _is_parallel_row_label_candidate(block):
            continue
        center_y = _layout_row_center(block)
        if center_y is None or center_y <= row_y_float:
            continue
        distance = center_y - row_y_float
        if distance <= 0.015 or distance > 0.08:
            continue
        candidates.append((distance, block.text))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], len(item[1])))
    return _clean_layout_chunk_text(candidates[0][1])


def _is_parallel_row_label_candidate(block: LayoutBlock) -> bool:
    if not block.text or block.normalized_bbox is None:
        return False
    if block.block_type.lower() in {"image", "figure", "table"}:
        return False
    if _has_table_ancestor(block) or _looks_like_page_footer(block):
        return False
    x1, _, x2, _ = block.normalized_bbox
    width = abs(x2 - x1)
    if width < 0.3:
        return False
    text = _clean_layout_chunk_text(block.text)
    return bool(text and len(text) <= 120)


def _looks_like_page_footer(block: LayoutBlock) -> bool:
    if block.normalized_bbox is None:
        return False
    _, y1, _, y2 = block.normalized_bbox
    if max(y1, y2) > 0.1:
        return False
    return bool(re.search(r"\d{1,4}", block.text or ""))


def _clean_layout_chunk_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _collapse_repeated_phrase(text: str) -> str:
    tokens = text.split()
    if len(tokens) >= 2 and len(tokens) % 2 == 0:
        midpoint = len(tokens) // 2
        if tokens[:midpoint] == tokens[midpoint:]:
            return " ".join(tokens[:midpoint])
    return text


def bbox_center(block: LayoutBlock) -> tuple[float, float] | None:
    """block bbox 중심 좌표를 반환한다."""
    if block.bbox is None:
        return None
    x1, y1, x2, y2 = block.bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def find_parallel_row_candidates(
    page_blocks: list[LayoutBlock],
    tolerance: float,
    preview_chars: int,
) -> list[dict[str, Any]]:
    """같은 y 좌표대에 있고 x 범위가 분리된 block 후보를 찾는다."""
    rows: dict[int, list[LayoutBlock]] = defaultdict(list)
    for block in page_blocks:
        key = _row_key(block, tolerance)
        if key is None or not block.text:
            continue
        rows[key].append(block)

    candidates: list[dict[str, Any]] = []
    for row_blocks in rows.values():
        if len(row_blocks) < 2:
            continue
        sorted_blocks = sorted(row_blocks, key=lambda item: (_layout_x_range(item) or (0.0, 0.0))[0])
        x_ranges = [_x_range(block) for block in sorted_blocks]
        layout_x_ranges = [_layout_x_range(block) for block in sorted_blocks]
        distinct_columns = 1
        last_right = layout_x_ranges[0][1] if layout_x_ranges and layout_x_ranges[0] else 0.0
        for current in layout_x_ranges[1:]:
            if current is None:
                continue
            if current[0] > last_right:
                distinct_columns += 1
            last_right = max(last_right, current[1])
        if distinct_columns < 2:
            continue

        row_texts = [block.text for block in sorted_blocks]
        row_types = [block.block_type for block in sorted_blocks]
        row_parent_ids = [block.parent_element_id for block in sorted_blocks if block.parent_element_id]
        row_ancestor_types = sorted({ancestor for block in sorted_blocks for ancestor in block.ancestor_types})
        has_table_ancestor = any(_has_table_ancestor(block) for block in sorted_blocks)
        y_values = [
            bbox_center(block)[1]
            for block in sorted_blocks
            if bbox_center(block) is not None
        ]
        role_input = {
            "distinct_columns": distinct_columns,
            "types": row_types,
            "texts": row_texts,
            "has_table_ancestor": has_table_ancestor,
            "ancestor_types": row_ancestor_types,
        }
        candidates.append({
            "y_center": round(sum(y_values) / len(y_values), 2) if y_values else None,
            "normalized_y_center": _normalized_row_center(sorted_blocks),
            "block_count": len(sorted_blocks),
            "distinct_columns": distinct_columns,
            "types": row_types,
            "role": classify_parallel_row_role(role_input),
            "parent_ids": row_parent_ids,
            "parent_group": _common_parent_group(row_parent_ids),
            "ancestor_types": row_ancestor_types,
            "has_table_ancestor": has_table_ancestor,
            "x_ranges": [
                [round(value, 2) for value in x_range]
                for x_range in x_ranges
                if x_range is not None
            ],
            "normalized_x_ranges": [
                [round(value, 4) for value in normalized_x_range]
                for normalized_x_range in [_normalized_x_range(block) for block in sorted_blocks]
                if normalized_x_range is not None
            ],
            "texts": [block.text[:preview_chars] for block in sorted_blocks],
        })

    return sorted(candidates, key=lambda item: (item["y_center"] is None, item["y_center"]))[:20]


def estimate_layout_column_count(page_blocks: list[LayoutBlock], row_candidates: list[dict[str, Any]]) -> int:
    """행 후보를 우선 사용해 페이지 column(열) 수를 보수적으로 추정한다."""
    row_column_counts = [
        int(candidate["distinct_columns"])
        for candidate in row_candidates
        if 1 < int(candidate["distinct_columns"]) <= 4
    ]
    if row_column_counts:
        return Counter(row_column_counts).most_common(1)[0][0]
    return _estimate_column_count(page_blocks)


def _opendataloader_parser_version() -> str:
    try:
        return metadata.version(OPENDATALOADER_PARSER_NAME)
    except metadata.PackageNotFoundError:
        return "unknown"


def _coerce_page(metadata_value: dict[str, Any]) -> int | None:
    raw_page = metadata_value.get("page") or metadata_value.get("page_number")
    if raw_page is None:
        return None
    try:
        return int(raw_page)
    except (TypeError, ValueError):
        return None


def _walk_layout_node(
    node: Any,
    page: int | None,
    path: tuple[int, ...],
    depth: int = 0,
    parent_element_id: str | None = None,
    ancestor_types: tuple[str, ...] = (),
) -> list[RawLayoutBlock]:
    blocks: list[RawLayoutBlock] = []
    if isinstance(node, list):
        for index, item in enumerate(node):
            blocks.extend(_walk_layout_node(item, page, path + (index,), depth, parent_element_id, ancestor_types))
        return blocks

    if not isinstance(node, dict):
        return blocks

    block_type = str(node.get("type") or node.get("tag") or "unknown")
    current_element_id = ".".join(str(item) for item in path)
    text = _text_from_node(node)
    bbox = _bbox_from_node(node)
    if text or bbox is not None:
        blocks.append(RawLayoutBlock(
            page=page,
            block_type=block_type,
            text=text,
            bbox=bbox,
            depth=depth,
            raw_element_id=current_element_id,
            fallback_reason=None if bbox is not None else "bbox_missing",
            parent_element_id=parent_element_id,
            ancestor_types=ancestor_types,
        ))

    for index, child in enumerate(_children_from_node(node)):
        blocks.extend(_walk_layout_node(
            child,
            page,
            path + (index,),
            depth + 1,
            current_element_id,
            ancestor_types + (block_type.lower(),),
        ))
    return blocks


def _text_from_node(node: dict[str, Any]) -> str:
    for key in ("content", "text"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value).strip()
    return ""


def _children_from_node(node: dict[str, Any]) -> Iterable[Any]:
    for key in ("kids", "children", "elements"):
        value = node.get(key)
        if isinstance(value, list):
            yield from value


def _bbox_from_node(node: dict[str, Any]) -> tuple[float, float, float, float] | None:
    for key in ("bounding box", "bbox", "box"):
        bbox = _parse_bbox(node.get(key))
        if bbox is not None:
            return bbox
    return None


def _parse_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _estimate_page_dimensions(raw_blocks: list[RawLayoutBlock]) -> dict[int | None, tuple[float, float]]:
    grouped: dict[int | None, list[tuple[float, float, float, float]]] = defaultdict(list)
    for block in raw_blocks:
        if block.bbox is not None:
            grouped[block.page].append(block.bbox)

    dimensions: dict[int | None, tuple[float, float]] = {}
    for page, bboxes in grouped.items():
        max_x = max(max(x1, x2) for x1, _, x2, _ in bboxes)
        max_y = max(max(y1, y2) for _, y1, _, y2 in bboxes)
        if max_x > 0 and max_y > 0:
            dimensions[page] = (max_x, max_y)
    return dimensions


def _build_layout_block(
    raw_block: RawLayoutBlock,
    page_dimension: tuple[float, float] | None,
    parser_version: str,
) -> LayoutBlock:
    page_width = page_dimension[0] if page_dimension else None
    page_height = page_dimension[1] if page_dimension else None
    normalized_bbox = _normalize_bbox(raw_block.bbox, page_width, page_height)
    confidence_reasons: list[str] = []
    if raw_block.bbox is not None:
        confidence_reasons.append("bbox_present")
    if raw_block.text:
        confidence_reasons.append("text_present")
    if normalized_bbox is not None:
        confidence_reasons.append("normalized_bbox_present")
    if is_text_bbox_split_candidate(raw_block):
        confidence_reasons.append("text_bbox_split_candidate")

    fallback_reason = raw_block.fallback_reason
    if raw_block.bbox is not None and normalized_bbox is None:
        fallback_reason = "page_dimension_missing"

    return LayoutBlock(
        page=raw_block.page,
        block_type=raw_block.block_type,
        text=raw_block.text,
        bbox=raw_block.bbox,
        normalized_bbox=normalized_bbox,
        page_width=page_width,
        page_height=page_height,
        depth=raw_block.depth,
        raw_element_id=raw_block.raw_element_id,
        text_hash=_text_hash(raw_block.text),
        parser_version=parser_version,
        confidence_reasons=tuple(confidence_reasons),
        fallback_reason=fallback_reason,
        parent_element_id=raw_block.parent_element_id,
        ancestor_types=raw_block.ancestor_types,
    )


def _normalize_bbox(
    bbox: tuple[float, float, float, float] | None,
    page_width: float | None,
    page_height: float | None,
) -> tuple[float, float, float, float] | None:
    if bbox is None or not page_width or not page_height:
        return None
    x1, y1, x2, y2 = bbox
    return (
        round(x1 / page_width, 6),
        round(y1 / page_height, 6),
        round(x2 / page_width, 6),
        round(y2 / page_height, 6),
    )


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


def _build_layout_stats(blocks: list[LayoutBlock], parser_version: str) -> LayoutExtractionStats:
    page_values = {block.page for block in blocks if block.page is not None}
    total_blocks = len(blocks)
    bbox_blocks = sum(1 for block in blocks if block.bbox is not None)
    return LayoutExtractionStats(
        parser_name=OPENDATALOADER_PARSER_NAME,
        parser_version=parser_version,
        pages=len(page_values),
        total_blocks=total_blocks,
        text_blocks=sum(1 for block in blocks if block.text),
        bbox_blocks=bbox_blocks,
        bbox_coverage=round(bbox_blocks / total_blocks, 4) if total_blocks else 0.0,
        parse_errors=sum(1 for block in blocks if block.block_type == "parse_error"),
    )


def _x_range(block: LayoutBlock) -> tuple[float, float] | None:
    if block.bbox is None:
        return None
    x1, _, x2, _ = block.bbox
    return (min(x1, x2), max(x1, x2))


def _normalized_x_range(block: LayoutBlock) -> tuple[float, float] | None:
    if block.normalized_bbox is None:
        return None
    x1, _, x2, _ = block.normalized_bbox
    return (min(x1, x2), max(x1, x2))


def _layout_x_range(block: LayoutBlock) -> tuple[float, float] | None:
    return _normalized_x_range(block) or _x_range(block)


def _row_key(block: LayoutBlock, tolerance: float) -> int | None:
    center_y = _layout_row_center(block)
    if center_y is None:
        return None
    row_tolerance = _layout_row_tolerance(block, tolerance)
    if row_tolerance <= 0:
        return None
    return round(center_y / row_tolerance)


def _layout_row_center(block: LayoutBlock) -> float | None:
    if block.normalized_bbox is not None:
        _, y1, _, y2 = block.normalized_bbox
        return (y1 + y2) / 2
    center = bbox_center(block)
    return center[1] if center is not None else None


def _normalized_row_center(blocks: list[LayoutBlock]) -> float | None:
    centers = [_layout_row_center(block) for block in blocks if block.normalized_bbox is not None]
    if not centers:
        return None
    return round(sum(centers) / len(centers), 4)


def _layout_row_tolerance(block: LayoutBlock, tolerance: float) -> float:
    if block.normalized_bbox is not None:
        if tolerance < 1:
            return tolerance
        if block.page_height and block.page_height > 0:
            return tolerance / block.page_height
    return tolerance


def _has_table_ancestor(block: LayoutBlock) -> bool:
    return any("table" in ancestor for ancestor in block.ancestor_types)


def _common_parent_group(parent_ids: list[str]) -> str | None:
    if not parent_ids:
        return None
    split_ids = [parent_id.split(".") for parent_id in parent_ids]
    common_parts: list[str] = []
    for parts in zip(*split_ids):
        if len(set(parts)) != 1:
            break
        common_parts.append(parts[0])
    if common_parts:
        return ".".join(common_parts)
    return Counter(parent_ids).most_common(1)[0][0]


def _estimate_column_count(page_blocks: list[LayoutBlock]) -> int:
    ranges = [_x_range(block) for block in page_blocks if block.text and block.bbox is not None]
    ranges = [value for value in ranges if value is not None]
    if len(ranges) < 2:
        return len(ranges)

    centers = sorted((x1 + x2) / 2 for x1, x2 in ranges)
    page_width = max(x2 for _, x2 in ranges) - min(x1 for x1, _ in ranges)
    if page_width <= 0:
        return 1

    clusters = 1
    previous = centers[0]
    for center in centers[1:]:
        if center - previous > page_width * 0.18:
            clusters += 1
        previous = center
    return clusters
