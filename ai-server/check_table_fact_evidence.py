"""Smoke checks for selected TableFact evidence text readiness."""

from __future__ import annotations

from rag_contract_builders import build_table_cell_fact
from rag_table_fact_selector import (
    build_table_fact_evidence_preview,
    select_table_facts_for_question,
)


def main() -> None:
    """Verify evidence text rendering stays trace-only and conservative."""
    table_facts = [
        _fact(0, 0, "유형 I", "전형", "농어촌"),
        _fact(0, 1, "유형 I", "전형", "유형 I"),
        _fact(0, 2, "유형 I", "지원자격", "중학교 입학부터 고등학교 졸업까지 거주"),
        _fact(0, 3, "유형 I", "제출서류", "학교생활기록부"),
        _fact(1, 0, "유형 II", "전형", "농어촌"),
        _fact(1, 1, "유형 II", "전형", "유형 II"),
        _fact(1, 2, "유형 II", "지원자격", "초등학교 입학부터 고등학교 졸업까지 거주"),
        _fact(1, 3, "유형 II", "제출서류", "가족관계증명서"),
        _fact(2, 2, "공통", "지원자격", "지원자격을 졸업일까지 유지"),
    ]

    comparison_result = select_table_facts_for_question(
        "유형 I과 유형 II의 차이는 무엇인가요?",
        table_facts,
    )
    comparison_preview = build_table_fact_evidence_preview(comparison_result)
    assert comparison_preview.prompt_candidate_ready is True
    assert "comparison_rows_covered" in comparison_preview.reasons
    assert "행: 유형 I / 열: 지원자격" in comparison_preview.evidence_text
    assert "행: 유형 II / 열: 지원자격" in comparison_preview.evidence_text
    assert "공통 맥락: 전형=농어촌" in comparison_preview.evidence_text
    assert "행: 공통" not in comparison_preview.evidence_text
    assert "열: 전형" not in comparison_preview.evidence_text
    assert "row_label" not in comparison_preview.evidence_text
    assert "source_block_id" not in comparison_preview.evidence_text

    scoped_comparison_result = select_table_facts_for_question(
        "유형 I과 유형 II의 농어촌 전형 지원자격이 어떻게 돼?",
        table_facts,
    )
    scoped_comparison_preview = build_table_fact_evidence_preview(
        scoped_comparison_result
    )
    assert scoped_comparison_preview.prompt_candidate_ready is True
    assert "공통 맥락: 전형=농어촌" in scoped_comparison_preview.evidence_text
    assert "행: 유형 I / 열: 지원자격" in scoped_comparison_preview.evidence_text
    assert "행: 유형 II / 열: 지원자격" in scoped_comparison_preview.evidence_text

    shared_scope_result = select_table_facts_for_question(
        "농어촌 전형 지원 자격은",
        table_facts,
    )
    shared_scope_preview = build_table_fact_evidence_preview(shared_scope_result)
    assert shared_scope_preview.prompt_candidate_ready is True
    assert "shared_context_scoped_rows" in shared_scope_preview.reasons
    assert "공통 맥락: 전형=농어촌" in shared_scope_preview.evidence_text
    assert "행: 유형 I / 열: 지원자격" in shared_scope_preview.evidence_text
    assert "행: 유형 II / 열: 지원자격" in shared_scope_preview.evidence_text
    assert "행: 공통" not in shared_scope_preview.evidence_text

    type_scope_result = select_table_facts_for_question(
        "농어촌 유형 지원자격이 어떻게 돼?",
        table_facts,
    )
    type_scope_preview = build_table_fact_evidence_preview(type_scope_result)
    assert type_scope_preview.prompt_candidate_ready is True
    assert "shared_context_scoped_rows" in type_scope_preview.reasons
    assert "공통 맥락: 전형=농어촌" in type_scope_preview.evidence_text
    assert "행: 유형 I / 열: 지원자격" in type_scope_preview.evidence_text
    assert "행: 유형 II / 열: 지원자격" in type_scope_preview.evidence_text
    assert "행: 공통" not in type_scope_preview.evidence_text

    single_cell_result = select_table_facts_for_question(
        "유형 I의 지원자격은 무엇인가요?",
        table_facts,
    )
    single_cell_preview = build_table_fact_evidence_preview(single_cell_result)
    assert single_cell_preview.prompt_candidate_ready is True
    assert "single_target_row" in single_cell_preview.reasons
    assert "target_column_matched" in single_cell_preview.reasons
    assert "행: 유형 I / 열: 지원자격" in single_cell_preview.evidence_text
    assert "행: 유형 I / 열: 제출서류" not in single_cell_preview.evidence_text

    column_only_result = select_table_facts_for_question(
        "지원자격은 무엇인가요?",
        table_facts,
    )
    column_only_preview = build_table_fact_evidence_preview(column_only_result)
    assert column_only_preview.prompt_candidate_ready is False
    assert "target_row_unresolved_for_evidence" in _diagnostic_codes(
        column_only_preview
    )

    repeated_answer_result = select_table_facts_for_question(
        "지원자격은 무엇인가요?",
        [
            _fact(0, 1, "일반고", "지원자격", "고등학교 졸업자"),
            _fact(1, 1, "특성화고", "지원자격", "고등학교 졸업자"),
        ],
    )
    repeated_answer_preview = build_table_fact_evidence_preview(
        repeated_answer_result
    )
    assert repeated_answer_preview.prompt_candidate_ready is False
    assert "shared_context_scoped_rows" not in repeated_answer_preview.reasons
    assert "target_row_unresolved_for_evidence" in _diagnostic_codes(
        repeated_answer_preview
    )

    many_row_facts = [
        fact
        for row_index in range(9)
        for fact in (
            _fact(row_index, 0, f"유형 {row_index}", "전형", "농어촌"),
            _fact(row_index, 1, f"유형 {row_index}", "지원자격", f"조건 {row_index}"),
        )
    ]
    selection_truncated_result = select_table_facts_for_question(
        "농어촌 전형 지원자격은?",
        many_row_facts,
    )
    selection_truncated_preview = build_table_fact_evidence_preview(
        selection_truncated_result
    )
    assert selection_truncated_preview.prompt_candidate_ready is False
    assert "selected_table_facts_truncated" in _diagnostic_codes(
        selection_truncated_preview
    )

    render_truncated_result = select_table_facts_for_question(
        "농어촌 전형 지원자격은?",
        many_row_facts,
        max_facts=20,
    )
    render_truncated_preview = build_table_fact_evidence_preview(
        render_truncated_result
    )
    assert render_truncated_preview.truncated is True
    assert render_truncated_preview.prompt_candidate_ready is False
    assert "truncated_table_fact_evidence" in _diagnostic_codes(
        render_truncated_preview
    )

    unresolved_comparison = select_table_facts_for_question(
        "유형 I과 유형 II의 차이는 무엇인가요?",
        [_fact(0, 1, "유형 II", "지원자격", "초등학교 입학부터 거주")],
    )
    unresolved_preview = build_table_fact_evidence_preview(unresolved_comparison)
    assert unresolved_preview.prompt_candidate_ready is False
    assert "comparison_target_rows_unresolved" in _diagnostic_codes(
        unresolved_preview
    )
    assert "no_selected_table_facts_for_evidence" in _diagnostic_codes(
        unresolved_preview
    )
    assert unresolved_preview.evidence_text == ""

    multiple_table_result = select_table_facts_for_question(
        "유형 I의 지원자격은 무엇인가요?",
        [
            _fact(0, 1, "유형 I", "지원자격", "첫 번째 표 조건", table_index=1),
            _fact(0, 1, "유형 I", "지원자격", "두 번째 표 조건", table_index=2),
        ],
    )
    multiple_table_preview = build_table_fact_evidence_preview(multiple_table_result)
    assert multiple_table_preview.prompt_candidate_ready is False
    assert "multiple_tables_selected" in _diagnostic_codes(multiple_table_preview)

    label_only_result = select_table_facts_for_question(
        "유형 I과 유형 II의 차이는 무엇인가요?",
        [
            _fact(0, 0, "유형 I", "전형", "농어촌"),
            _fact(0, 1, "유형 I", "전형", "유형 I"),
            _fact(1, 0, "유형 II", "전형", "농어촌"),
            _fact(1, 1, "유형 II", "전형", "유형 II"),
        ],
    )
    label_only_preview = build_table_fact_evidence_preview(label_only_result)
    assert label_only_preview.prompt_candidate_ready is False
    assert label_only_preview.evidence_text == ""
    assert "no_renderable_table_fact_evidence" in _diagnostic_codes(label_only_preview)

    print("table fact evidence smoke ok")


def _fact(
    row_index: int,
    column_index: int,
    row_label: str,
    column_label: str,
    value: str,
    *,
    table_index: int = 1,
):
    return build_table_cell_fact(
        document_id="evidence-smoke",
        table_index=table_index,
        row_index=row_index,
        column_index=column_index,
        row_label=row_label,
        column_label=column_label,
        value=value,
        source_block_id=f"source-{table_index}",
        caption="정원외 특별전형 지원자격",
        row_header_path=(row_label,),
        column_path=(column_label,),
        header_path=("모집요강", "지원자격"),
        confidence=0.9,
    )


def _diagnostic_codes(preview) -> set[str]:
    return {diagnostic.code for diagnostic in preview.diagnostics}


if __name__ == "__main__":
    main()
