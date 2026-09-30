"""Question-aware selection helpers for typed TableFact candidates.

This module is intentionally side-effect free. It does not call ChromaDB,
change retrieval ranking, or mutate prompts. Its job is to decide whether typed
table facts can be narrowed to the rows that a question actually asks about.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Iterable, Sequence

from rag_contracts import TableFact


@dataclass(frozen=True)
class TableFactSelection:
    """One selected table fact with row/column match diagnostics."""

    fact: TableFact
    score: int
    reasons: tuple[str, ...] = ()
    matched_row_terms: tuple[str, ...] = ()
    matched_column_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableFactSelectionDiagnostic:
    """A non-fatal selector note for audit and smoke output."""

    code: str
    message: str
    details: dict[str, str | int | list[str]] | None = None


@dataclass(frozen=True)
class TableFactSelectionResult:
    """The selected table facts and selector-level diagnostics."""

    selections: tuple[TableFactSelection, ...]
    comparison_mode: bool
    target_row_labels: tuple[str, ...] = ()
    diagnostics: tuple[TableFactSelectionDiagnostic, ...] = ()
    normalized_question: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class TableFactEvidencePreview:
    """Preview of whether selected facts are safe prompt candidates."""

    prompt_candidate_ready: bool
    evidence_text: str
    reasons: tuple[str, ...] = ()
    diagnostics: tuple[TableFactSelectionDiagnostic, ...] = ()
    truncated: bool = False


def select_table_facts_for_question(
    question: str,
    table_facts: Sequence[TableFact],
    *,
    max_facts: int = 12,
) -> TableFactSelectionResult:
    """Select TableFact rows that are most relevant to a question."""
    normalized_question = _normalize_text(question)
    comparison_mode = _is_comparison_question(normalized_question)
    scored = tuple(
        selection
        for fact in table_facts
        if (selection := _score_table_fact(fact, normalized_question)).score > 0
    )

    target_row_labels = _target_row_labels(scored, comparison_mode)
    diagnostics: list[TableFactSelectionDiagnostic] = []
    selected = scored
    if comparison_mode and not target_row_labels:
        selected = ()
        matched_rows = _matched_row_labels(scored)
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="comparison_target_rows_unresolved",
                message="비교 질문에서 명확한 비교 대상 행을 두 개 이상 찾지 못했습니다.",
                details={"matched_row_labels": list(matched_rows)},
            )
        )
    elif target_row_labels:
        selected = tuple(
            selection
            for selection in scored
            if _row_identity(selection.fact) in target_row_labels
        )
        excluded_count = len(scored) - len(selected)
        if excluded_count:
            diagnostics.append(
                TableFactSelectionDiagnostic(
                    code="non_target_rows_excluded",
                    message="질문에서 명확한 대상 행이 잡혀 대상이 아닌 행을 제외했습니다.",
                    details={
                        "excluded_count": excluded_count,
                        "target_row_labels": list(target_row_labels),
                    },
                )
            )

    column_scoped = tuple(selection for selection in selected if selection.matched_column_terms)
    if column_scoped:
        question_scoped_contexts = _question_scoped_shared_context_selections(
            selected,
            normalized_question,
        )
        next_selected = _unique_selections(
            [*column_scoped, *question_scoped_contexts]
        )
        excluded_count = len(selected) - len(next_selected)
        selected = next_selected
        if excluded_count:
            diagnostics.append(
                TableFactSelectionDiagnostic(
                    code="non_target_columns_excluded",
                    message="질문에서 명확한 대상 열이 잡혀 대상이 아닌 열을 제외했습니다.",
                    details={"excluded_count": excluded_count},
                )
            )

    if not target_row_labels and not _term_in_text("공통", normalized_question):
        non_common_rows = tuple(
            selection for selection in selected if not _is_common_row(selection.fact)
        )
        non_common_row_labels = _dedupe(
            _row_identity(selection.fact)
            for selection in non_common_rows
            if _row_identity(selection.fact)
        )
        if len(non_common_row_labels) >= 2 and len(non_common_rows) < len(selected):
            diagnostics.append(
                TableFactSelectionDiagnostic(
                    code="generic_common_rows_excluded",
                    message="질문이 공통 조건을 직접 묻지 않아 일반 공통 행을 우선 근거에서 제외했습니다.",
                    details={"excluded_count": len(selected) - len(non_common_rows)},
                )
            )
            selected = non_common_rows

    if not selected and table_facts:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="no_table_fact_selected",
                message="질문과 충분히 겹치는 행, 열, 표 맥락을 가진 표 근거가 없습니다.",
            )
        )

    sorted_selected = tuple(
        sorted(
            selected,
            key=lambda selection: (
                -selection.score,
                selection.fact.table_id,
                selection.fact.row_index if selection.fact.row_index is not None else 10**9,
                selection.fact.column_index if selection.fact.column_index is not None else 10**9,
                selection.fact.fact_id,
            ),
        )
    )
    selection_limit = max(0, max_facts)
    selected = sorted_selected[:selection_limit]
    return TableFactSelectionResult(
        selections=selected,
        comparison_mode=comparison_mode,
        target_row_labels=target_row_labels,
        diagnostics=tuple(diagnostics),
        normalized_question=normalized_question,
        truncated=len(sorted_selected) > selection_limit,
    )


def build_table_fact_evidence_preview(
    selection_result: TableFactSelectionResult,
    *,
    max_lines: int = 8,
) -> TableFactEvidencePreview:
    """Render selected facts and explain whether they are safe prompt candidates.

    This function is still side-effect free. Runtime code may use the readiness
    result for trace output or for prompt injection after its own retrieval checks.
    """
    diagnostics: list[TableFactSelectionDiagnostic] = []
    reasons: list[str] = []
    selections = selection_result.selections

    if not selections:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="no_selected_table_facts_for_evidence",
                message="근거 텍스트로 바꿀 선택된 표 근거가 없습니다.",
            )
        )
        return TableFactEvidencePreview(
            prompt_candidate_ready=False,
            evidence_text="",
            diagnostics=tuple([*selection_result.diagnostics, *diagnostics]),
        )

    if selection_result.truncated:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="selected_table_facts_truncated",
                message="선택된 표 근거가 최대 선택 개수를 넘어 즉시 답변 후보에서 제외했습니다.",
                details={"selected_count": len(selections)},
            )
        )

    table_ids = _dedupe(selection.fact.table_id for selection in selections)
    if len(table_ids) > 1:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="multiple_tables_selected",
                message="선택된 표 근거가 여러 표에서 나와 prompt 후보 근거로 쓰기 안전하지 않습니다.",
                details={"table_count": len(table_ids)},
            )
        )
    else:
        reasons.append("single_table")

    selected_row_identities = [
        _row_identity(selection.fact)
        for selection in selections
    ]
    selected_row_labels = _dedupe(
        row_identity
        for row_identity in selected_row_identities
        if row_identity
    )
    target_row_labels = selection_result.target_row_labels
    question_scoped_shared_contexts = _question_scoped_shared_evidence_contexts(
        selections,
        selection_result.normalized_question,
    )
    if selection_result.comparison_mode:
        missing_targets = sorted(set(target_row_labels) - set(selected_row_labels))
        if len(target_row_labels) < 2 or missing_targets:
            diagnostics.append(
                TableFactSelectionDiagnostic(
                    code="comparison_rows_incomplete_for_evidence",
                    message="비교 질문의 prompt 후보 근거에는 비교 대상 행이 모두 들어 있어야 합니다.",
                    details={
                        "target_row_labels": list(target_row_labels),
                        "selected_row_labels": list(selected_row_labels),
                        "missing_target_row_labels": missing_targets,
                    },
                )
            )
        else:
            reasons.append("comparison_rows_covered")
    else:
        if not target_row_labels:
            if len(selected_row_labels) >= 2 and question_scoped_shared_contexts:
                reasons.append("shared_context_scoped_rows")
            else:
                diagnostics.append(
                    TableFactSelectionDiagnostic(
                        code="target_row_unresolved_for_evidence",
                        message="비교 질문이 아닌 경우에는 prompt 후보 근거로 쓰기 전에 질문 대상 행이 명확해야 합니다.",
                        details={"selected_row_labels": list(selected_row_labels)},
                    )
                )
        elif len(target_row_labels) > 1:
            reasons.append("multiple_target_rows")
        else:
            reasons.append("single_target_row")

        if not any(selection.matched_column_terms for selection in selections):
            diagnostics.append(
                TableFactSelectionDiagnostic(
                    code="target_column_unresolved_for_evidence",
                    message="비교 질문이 아닌 경우에는 prompt 후보 근거로 쓰기 전에 질문 대상 열이 명확해야 합니다.",
                )
            )
        else:
            reasons.append("target_column_matched")

    evidence_text, truncated = render_selected_table_facts_as_evidence_text(
        selections,
        max_lines=max_lines,
    )
    if not evidence_text:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="no_renderable_table_fact_evidence",
                message="선택된 표 근거가 라벨 반복값이나 공통값만 포함해 답변 근거 문장으로 만들 수 없습니다.",
            )
        )
    elif truncated:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="truncated_table_fact_evidence",
                message="선택된 표 근거가 미리보기 최대 줄 수를 넘어 즉시 답변 후보에서 제외했습니다.",
                details={"max_lines": max_lines},
            )
        )
    all_diagnostics = (*selection_result.diagnostics, *diagnostics)
    return TableFactEvidencePreview(
        prompt_candidate_ready=not diagnostics,
        evidence_text=evidence_text,
        reasons=_dedupe(reasons),
        diagnostics=all_diagnostics,
        truncated=truncated,
    )


def render_selected_table_facts_as_evidence_text(
    selections: Sequence[TableFactSelection],
    *,
    max_lines: int = 8,
) -> tuple[str, bool]:
    """Render selected table facts as compact Korean key-value evidence text."""
    if not selections:
        return "", False

    renderable_selections = _renderable_evidence_selections(selections)
    if not renderable_selections:
        return "", False

    shared_contexts = _shared_evidence_contexts(selections)
    max_lines = max(0, max_lines)
    lines = ["[표 근거 후보]"]
    emitted = 0
    truncated = False
    current_caption = None
    for selection in renderable_selections:
        if emitted >= max_lines:
            truncated = True
            break
        fact = selection.fact
        caption = _display_caption(fact)
        if caption and caption != current_caption:
            lines.append(f"표 제목: {caption}")
            if shared_contexts:
                lines.append(f"공통 맥락: {', '.join(shared_contexts)}")
            current_caption = caption
        row_label = _display_path(fact.row_header_path, fact.row_label)
        column_label = _display_path(fact.column_path, fact.column_label)
        lines.append(f"- 행: {row_label} / 열: {column_label} / 값: {fact.value}")
        emitted += 1

    if truncated:
        lines.append(f"- 추가 표 근거 {len(renderable_selections) - emitted}개는 미리보기에서 생략됨")
    return "\n".join(lines), truncated


def _renderable_evidence_selections(
    selections: Sequence[TableFactSelection],
) -> tuple[TableFactSelection, ...]:
    rows = _dedupe(
        _row_identity(selection.fact)
        for selection in selections
        if _row_identity(selection.fact)
    )
    shared_comparison_values = (
        _shared_column_values(selections) if len(rows) >= 2 else set()
    )
    renderable: list[TableFactSelection] = []
    for selection in selections:
        fact = selection.fact
        if _is_label_echo_fact(fact):
            continue
        column_value_key = (
            _normalize_text(fact.column_label),
            _normalize_text(fact.value),
        )
        if column_value_key in shared_comparison_values:
            continue
        renderable.append(selection)
    return tuple(renderable)


def _shared_evidence_contexts(
    selections: Sequence[TableFactSelection],
) -> tuple[str, ...]:
    shared_values = _shared_column_values(selections)
    contexts: list[str] = []
    seen: set[str] = set()
    for selection in selections:
        fact = selection.fact
        key = (
            _normalize_text(fact.column_label),
            _normalize_text(fact.value),
        )
        if key not in shared_values or _is_label_echo_fact(fact):
            continue
        column_label = _display_path(fact.column_path, fact.column_label)
        context = f"{column_label}={fact.value}"
        if context in seen:
            continue
        seen.add(context)
        contexts.append(context)
    return tuple(contexts)


def _question_scoped_shared_evidence_contexts(
    selections: Sequence[TableFactSelection],
    normalized_question: str,
) -> tuple[str, ...]:
    """Return shared row context only when its value is explicitly in the question."""
    if not normalized_question:
        return ()

    shared_values = _shared_column_values(selections)
    contexts: list[str] = []
    seen: set[str] = set()
    for selection in selections:
        fact = selection.fact
        key = (
            _normalize_text(fact.column_label),
            _normalize_text(fact.value),
        )
        if key not in shared_values or _is_label_echo_fact(fact):
            continue
        if not _term_in_text(key[1], normalized_question):
            continue
        column_label = _display_path(fact.column_path, fact.column_label)
        context = f"{column_label}={fact.value}"
        if context in seen:
            continue
        seen.add(context)
        contexts.append(context)
    return tuple(contexts)


def _question_scoped_shared_context_selections(
    selections: Sequence[TableFactSelection],
    normalized_question: str,
) -> tuple[TableFactSelection, ...]:
    """Keep shared scope cells needed to explain multi-row column answers."""
    if not normalized_question:
        return ()

    shared_values = _shared_column_values(selections)
    scoped: list[TableFactSelection] = []
    for selection in selections:
        fact = selection.fact
        key = (
            _normalize_text(fact.column_label),
            _normalize_text(fact.value),
        )
        if key not in shared_values or _is_label_echo_fact(fact):
            continue
        if _term_in_text(key[1], normalized_question):
            scoped.append(selection)
    return tuple(scoped)


def _shared_column_values(
    selections: Sequence[TableFactSelection],
) -> set[tuple[str, str]]:
    rows_by_column_value: dict[tuple[str, str], set[str]] = {}
    for selection in selections:
        fact = selection.fact
        key = (_normalize_text(fact.column_label), _normalize_text(fact.value))
        if not key[0] or not key[1]:
            continue
        rows_by_column_value.setdefault(key, set()).add(_row_identity(fact))
    return {
        key
        for key, row_labels in rows_by_column_value.items()
        if len(row_labels) >= 2
    }


def _is_label_echo_fact(fact: TableFact) -> bool:
    value = _normalize_text(fact.value)
    if not value:
        return True
    label_terms = _normalized_terms(
        [
            fact.row_label,
            *fact.row_header_path,
            fact.column_label,
            *fact.column_path,
        ]
    )
    return value in label_terms


def _is_common_row(fact: TableFact) -> bool:
    return _row_identity(fact) in {"공통", "공통 지원자격", "공통 조건"}


def _score_table_fact(
    fact: TableFact,
    normalized_question: str,
) -> TableFactSelection:
    score = 0
    reasons: list[str] = []
    matched_row_terms: list[str] = []
    matched_column_terms: list[str] = []

    for term in _row_terms(fact):
        if _term_in_text(term, normalized_question):
            score += 40
            reasons.append("row_match")
            matched_row_terms.append(term)

    for term in _column_terms(fact):
        if _term_in_text(term, normalized_question):
            score += 18
            reasons.append("column_match")
            matched_column_terms.append(term)

    for term in _context_terms(fact):
        if _term_in_text(term, normalized_question):
            score += 6
            reasons.append("table_context_match")

    value_text = _normalize_text(fact.value)
    if value_text and _term_in_text(value_text, normalized_question):
        score += 10
        reasons.append("value_match")

    return TableFactSelection(
        fact=fact,
        score=score,
        reasons=_dedupe(reasons),
        matched_row_terms=_dedupe(matched_row_terms),
        matched_column_terms=_dedupe(matched_column_terms),
    )


def _target_row_labels(
    selections: Sequence[TableFactSelection],
    comparison_mode: bool,
) -> tuple[str, ...]:
    labels = _matched_row_labels(selections)
    if comparison_mode:
        return labels if len(labels) >= 2 else ()
    if len(labels) == 1:
        return labels
    return labels


def _matched_row_labels(
    selections: Sequence[TableFactSelection],
) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for selection in sorted(
        selections,
        key=lambda item: (-len(item.matched_row_terms), -item.score, item.fact.fact_id),
    ):
        if not selection.matched_row_terms:
            continue
        row_label = _row_identity(selection.fact)
        if not row_label or row_label in seen:
            continue
        seen.add(row_label)
        labels.append(row_label)
    return tuple(labels)


def _row_terms(fact: TableFact) -> tuple[str, ...]:
    values = [fact.row_label, *fact.row_header_path]
    if fact.row_header_path:
        values.append(" ".join(fact.row_header_path))
        values.append(" > ".join(fact.row_header_path))
    return _normalized_terms(values)


def _column_terms(fact: TableFact) -> tuple[str, ...]:
    values = [fact.column_label, *fact.column_path]
    if fact.column_path:
        values.append(" ".join(fact.column_path))
        values.append(" > ".join(fact.column_path))
    return _normalized_terms(values)


def _context_terms(fact: TableFact) -> tuple[str, ...]:
    values = [fact.caption or "", *fact.header_path]
    return _normalized_terms(values)


def _display_caption(fact: TableFact) -> str:
    if fact.caption:
        return fact.caption.strip()
    if fact.header_path:
        return fact.header_path[-1].strip()
    return ""


def _display_path(path: Sequence[str], fallback: str) -> str:
    values = [str(value).strip() for value in path if str(value).strip()]
    if values:
        return " > ".join(values)
    return str(fallback or "").strip()


def _row_identity(fact: TableFact) -> str:
    row_label = fact.row_header_path[-1] if fact.row_header_path else fact.row_label
    return _normalize_text(row_label)


def _normalized_terms(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        term
        for term in _dedupe(_normalize_text(value) for value in values)
        if len(_compact(term)) >= 2 and term not in _STOPWORDS
    )


def _term_in_text(term: str, normalized_text: str) -> bool:
    if not term:
        return False
    return term in normalized_text or _compact(term) in _compact(normalized_text)


def _is_comparison_question(normalized_question: str) -> bool:
    return any(term in normalized_question for term in _COMPARISON_TERMS)


def _normalize_text(value: object) -> str:
    text = str(value or "").upper()
    text = _normalize_roman_numerals(text)
    text = re.sub(r"[^0-9A-Z가-힣]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_roman_numerals(text: str) -> str:
    for source, target in _UNICODE_ROMAN_NUMERALS.items():
        text = text.replace(source, target)
    return _ASCII_ROMAN_TOKEN_RE.sub(
        lambda match: _ASCII_ROMAN_NUMERALS[match.group(1)],
        text,
    )


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _unique_selections(
    selections: Iterable[TableFactSelection],
) -> tuple[TableFactSelection, ...]:
    unique: list[TableFactSelection] = []
    seen: set[str] = set()
    for selection in selections:
        fact_id = selection.fact.fact_id
        if fact_id in seen:
            continue
        seen.add(fact_id)
        unique.append(selection)
    return tuple(unique)


_ASCII_ROMAN_NUMERALS = {
    "I": "1",
    "II": "2",
    "III": "3",
    "IV": "4",
    "V": "5",
}
_UNICODE_ROMAN_NUMERALS = {
    "Ⅰ": "1",
    "Ⅱ": "2",
    "Ⅲ": "3",
    "Ⅳ": "4",
    "Ⅴ": "5",
}
_ASCII_ROMAN_TOKEN_RE = re.compile(r"(?<![0-9A-Z])(IV|III|II|I|V)(?![0-9A-Z])")
_COMPARISON_TERMS = ("차이", "비교", "다른", "각각", "VS", "VERSUS")
_STOPWORDS = {
    "값",
    "관련",
    "기준",
    "내용",
    "무엇",
    "무엇인가요",
    "비교",
    "차이",
    "표",
    "해당",
}
