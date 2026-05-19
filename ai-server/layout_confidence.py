from __future__ import annotations

from collections import Counter
from typing import Any, Protocol


MIN_TEXT_BBOX_COVERAGE_FOR_SPLIT = 0.6
MIN_STABLE_PARALLEL_ROWS_FOR_SPLIT = 2
MAX_SPLIT_COLUMN_COUNT = 4
NON_TEXT_LAYOUT_TYPES = {"image", "figure", "table", "parse_error"}
TABLE_LAYOUT_TYPES = {"table", "table row", "table cell", "cell", "thead", "tbody"}
MIN_PARENT_SIGNAL_COVERAGE = 0.6
MIN_PARENT_STABILITY_RATIO = 0.67


class LayoutConfidenceBlock(Protocol):
    """confidence 계산에 필요한 LayoutBlock의 최소 interface(인터페이스)다."""

    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None


def is_text_bbox_split_candidate(block: LayoutConfidenceBlock) -> bool:
    """텍스트와 bbox를 모두 가진 block이 split(분리) 후보인지 확인한다."""
    return bool(
        block.text
        and block.bbox is not None
        and block.block_type.lower() not in NON_TEXT_LAYOUT_TYPES
    )


def classify_parallel_row_role(candidate: dict[str, Any]) -> str:
    """병렬 row 후보의 역할을 구조 신호만으로 보수적으로 분류한다."""
    types = [str(value).lower() for value in candidate.get("types") or []]
    texts = [str(value).strip() for value in candidate.get("texts") or [] if str(value).strip()]
    distinct_columns = int(candidate.get("distinct_columns") or 0)
    if not texts:
        return "unknown"
    if _has_table_signal(candidate, types):
        return "table_like"

    lengths = [len(text) for text in texts]
    average_length = sum(lengths) / len(lengths)
    if distinct_columns >= 4 and average_length <= 35:
        return "icon_like"
    if distinct_columns >= 3 and _mostly_short_cell_texts(texts):
        return "table_like"
    if max(lengths) <= 35 and average_length <= 25:
        return "label_like"
    if max(lengths) >= 45 or average_length >= 35:
        return "body"
    return "unknown"


def assess_parallel_layout_confidence(
    page_blocks: list[LayoutConfidenceBlock],
    row_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """페이지를 좌우 layout으로 나누어도 되는지 보수적인 진단 정보를 만든다."""
    text_blocks = [block for block in page_blocks if block.text]
    text_bbox_blocks = [block for block in text_blocks if block.bbox is not None]
    text_bbox_coverage = round(len(text_bbox_blocks) / len(text_blocks), 4) if text_blocks else 0.0
    role_counts = Counter(_candidate_role(candidate) for candidate in row_candidates)
    split_ready_candidates = [
        candidate for candidate in row_candidates if _is_split_ready_row_candidate(candidate)
    ]
    parent_summary = _parent_stability_summary(split_ready_candidates)
    dominant_column_count, stable_parallel_rows = _dominant_split_column_count(split_ready_candidates)
    reasons = _parallel_confidence_reasons(
        text_bbox_coverage,
        split_ready_candidates,
        dominant_column_count,
        stable_parallel_rows,
        parent_summary,
    )
    blockers = _parallel_confidence_blockers(
        text_blocks,
        text_bbox_coverage,
        split_ready_candidates,
        dominant_column_count,
        stable_parallel_rows,
        parent_summary,
    )
    score = _parallel_confidence_score(reasons, blockers)
    eligible_for_split = (
        score >= 80
        and not blockers
        and stable_parallel_rows >= MIN_STABLE_PARALLEL_ROWS_FOR_SPLIT
        and dominant_column_count is not None
    )

    return {
        "eligible_for_split": eligible_for_split,
        "level": _confidence_level(score, eligible_for_split),
        "score": score,
        "candidate_rows": len(row_candidates),
        "split_ready_rows": len(split_ready_candidates),
        "body_ready_rows": sum(1 for candidate in split_ready_candidates if _candidate_role(candidate) == "body"),
        "table_like_candidate_rows": role_counts.get("table_like", 0),
        "icon_like_candidate_rows": role_counts.get("icon_like", 0),
        "table_ancestor_candidate_rows": sum(1 for candidate in row_candidates if candidate.get("has_table_ancestor")),
        "stable_parallel_rows": stable_parallel_rows,
        "dominant_column_count": dominant_column_count,
        "parent_region": parent_summary,
        "text_bbox_coverage": text_bbox_coverage,
        "role_counts": dict(role_counts.most_common()),
        "reasons": reasons,
        "blockers": blockers,
    }


def _candidate_role(candidate: dict[str, Any]) -> str:
    return str(candidate.get("role") or classify_parallel_row_role(candidate))


def _is_split_ready_row_candidate(candidate: dict[str, Any]) -> bool:
    distinct_columns = int(candidate.get("distinct_columns") or 0)
    if distinct_columns < 2 or distinct_columns > MAX_SPLIT_COLUMN_COUNT:
        return False
    if candidate.get("has_table_ancestor"):
        return False
    if _candidate_role(candidate) != "body":
        return False
    texts = [str(value).strip() for value in candidate.get("texts") or []]
    return len(texts) >= distinct_columns and all(texts)


def _dominant_split_column_count(candidates: list[dict[str, Any]]) -> tuple[int | None, int]:
    column_counts: list[int] = []
    for candidate in candidates:
        column_count = int(candidate.get("distinct_columns") or 0)
        if 2 <= column_count <= MAX_SPLIT_COLUMN_COUNT:
            column_counts.append(column_count)
    if not column_counts:
        return None, 0
    dominant_column_count, stable_rows = Counter(column_counts).most_common(1)[0]
    return dominant_column_count, stable_rows


def _parallel_confidence_reasons(
    text_bbox_coverage: float,
    split_ready_candidates: list[dict[str, Any]],
    dominant_column_count: int | None,
    stable_parallel_rows: int,
    parent_summary: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if text_bbox_coverage >= MIN_TEXT_BBOX_COVERAGE_FOR_SPLIT:
        reasons.append("text_bbox_coverage_sufficient")
    if split_ready_candidates:
        reasons.append("body_parallel_rows_present")
    if stable_parallel_rows >= MIN_STABLE_PARALLEL_ROWS_FOR_SPLIT:
        reasons.append("stable_parallel_rows_present")
    if dominant_column_count is not None:
        reasons.append(f"dominant_column_count:{dominant_column_count}")
    if parent_summary.get("level") == "high":
        reasons.append("parent_region_stable")
    elif parent_summary.get("level") == "unknown":
        reasons.append("parent_region_unknown")
    return reasons


def _parallel_confidence_blockers(
    text_blocks: list[LayoutConfidenceBlock],
    text_bbox_coverage: float,
    split_ready_candidates: list[dict[str, Any]],
    dominant_column_count: int | None,
    stable_parallel_rows: int,
    parent_summary: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not text_blocks:
        blockers.append("no_text_blocks")
    if text_bbox_coverage < MIN_TEXT_BBOX_COVERAGE_FOR_SPLIT:
        blockers.append("text_bbox_coverage_low")
    if not split_ready_candidates:
        blockers.append("no_body_parallel_rows")
    if stable_parallel_rows < MIN_STABLE_PARALLEL_ROWS_FOR_SPLIT:
        blockers.append("stable_parallel_rows_insufficient")
    if dominant_column_count is None:
        blockers.append("dominant_column_count_missing")
    if parent_summary.get("level") == "low":
        blockers.append("parent_region_fragmented")
    return blockers


def _parallel_confidence_score(reasons: list[str], blockers: list[str]) -> int:
    score = 0
    if "text_bbox_coverage_sufficient" in reasons:
        score += 30
    if "body_parallel_rows_present" in reasons:
        score += 25
    if "stable_parallel_rows_present" in reasons:
        score += 30
    if any(reason.startswith("dominant_column_count:") for reason in reasons):
        score += 15
    return max(0, score - (len(blockers) * 20))


def _confidence_level(score: int, eligible_for_split: bool) -> str:
    if eligible_for_split and score >= 90:
        return "high"
    if eligible_for_split:
        return "medium"
    if score >= 50:
        return "low"
    return "none"


def _mostly_short_cell_texts(texts: list[str]) -> bool:
    if not texts:
        return False
    short_text_count = sum(1 for text in texts if len(text) <= 24)
    numeric_or_symbol_count = sum(1 for text in texts if _is_numeric_or_symbol_heavy(text))
    return short_text_count / len(texts) >= 0.7 or numeric_or_symbol_count / len(texts) >= 0.5


def _is_numeric_or_symbol_heavy(text: str) -> bool:
    if not text:
        return False
    numeric_or_symbol = sum(1 for char in text if char.isdigit() or not char.isalnum())
    return numeric_or_symbol / len(text) >= 0.45


def _has_table_signal(candidate: dict[str, Any], types: list[str]) -> bool:
    ancestor_types = [str(value).lower() for value in candidate.get("ancestor_types") or []]
    if candidate.get("has_table_ancestor"):
        return True
    return any(_is_table_type(value) for value in types + ancestor_types)


def _is_table_type(value: str) -> bool:
    return value in TABLE_LAYOUT_TYPES or "table" in value


def _parent_stability_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "level": "none",
            "dominant_parent_group": None,
            "signal_coverage": 0.0,
            "stability_ratio": 0.0,
        }

    parent_groups = [str(candidate.get("parent_group")) for candidate in candidates if candidate.get("parent_group")]
    signal_coverage = round(len(parent_groups) / len(candidates), 4)
    if not parent_groups:
        return {
            "level": "unknown",
            "dominant_parent_group": None,
            "signal_coverage": signal_coverage,
            "stability_ratio": 0.0,
        }

    dominant_parent_group, dominant_count = Counter(parent_groups).most_common(1)[0]
    stability_ratio = round(dominant_count / len(parent_groups), 4)
    if _is_root_level_parent_group(dominant_parent_group):
        level = "unknown"
    elif signal_coverage < MIN_PARENT_SIGNAL_COVERAGE:
        level = "unknown"
    elif stability_ratio >= MIN_PARENT_STABILITY_RATIO:
        level = "high"
    else:
        level = "low"

    return {
        "level": level,
        "dominant_parent_group": dominant_parent_group,
        "signal_coverage": signal_coverage,
        "stability_ratio": stability_ratio,
    }


def _is_root_level_parent_group(parent_group: str) -> bool:
    return "." not in parent_group
