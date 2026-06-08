"""Question-aware selection helpers for typed TableFact candidates.

This module is intentionally side-effect free. It does not call ChromaDB,
change retrieval ranking, alter prompts, or connect to ``/query``. Its job is
to smoke-test whether typed table facts can be narrowed to the rows that a
question actually asks about.
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
                message="Comparison question did not resolve at least two explicit target rows.",
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
                    message="Question matched explicit target rows, so non-target rows were excluded.",
                    details={
                        "excluded_count": excluded_count,
                        "target_row_labels": list(target_row_labels),
                    },
                )
            )

    column_scoped = tuple(selection for selection in selected if selection.matched_column_terms)
    if column_scoped:
        excluded_count = len(selected) - len(column_scoped)
        selected = column_scoped
        if excluded_count:
            diagnostics.append(
                TableFactSelectionDiagnostic(
                    code="non_target_columns_excluded",
                    message="Question matched explicit target columns, so non-target columns were excluded.",
                    details={"excluded_count": excluded_count},
                )
            )

    if not selected and table_facts:
        diagnostics.append(
            TableFactSelectionDiagnostic(
                code="no_table_fact_selected",
                message="No TableFact had enough row, column, or table context overlap with the question.",
            )
        )

    selected = tuple(
        sorted(
            selected,
            key=lambda selection: (
                -selection.score,
                selection.fact.table_id,
                selection.fact.row_index if selection.fact.row_index is not None else 10**9,
                selection.fact.column_index if selection.fact.column_index is not None else 10**9,
                selection.fact.fact_id,
            ),
        )[: max(0, max_facts)]
    )
    return TableFactSelectionResult(
        selections=selected,
        comparison_mode=comparison_mode,
        target_row_labels=target_row_labels,
        diagnostics=tuple(diagnostics),
    )


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
