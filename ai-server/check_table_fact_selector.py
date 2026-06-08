"""Smoke checks for question-aware typed TableFact selection."""

from __future__ import annotations

from rag_contract_builders import build_table_cell_fact
from rag_table_fact_selector import select_table_facts_for_question


def main() -> None:
    """Verify row-scoped TableFact selection without running DocuMind runtime."""
    table_facts = [
        _fact(0, 1, "유형 I", "지원자격", "일반고 졸업자"),
        _fact(0, 2, "유형 I", "제출서류", "학교생활기록부"),
        _fact(1, 1, "유형 II", "지원자격", "검정고시 출신자"),
        _fact(1, 2, "유형 II", "제출서류", "검정고시 성적증명서"),
        _fact(2, 1, "공통 지원자격", "지원자격", "고등학교 졸업 이상"),
        _fact(3, 1, "추가선발", "지원자격", "미충원 시 별도 선발"),
        _fact(0, 1, "면접학과", "계", "50,000원", table_index=2),
    ]

    comparison_result = select_table_facts_for_question(
        "유형 I과 유형 II의 차이는 무엇인가요?",
        table_facts,
    )
    comparison_rows = {selection.fact.row_label for selection in comparison_result.selections}
    assert comparison_result.comparison_mode is True
    assert comparison_result.target_row_labels == ("유형 1", "유형 2")
    assert comparison_rows == {"유형 I", "유형 II"}
    assert "공통 지원자격" not in comparison_rows
    assert "추가선발" not in comparison_rows
    assert "면접학과" not in comparison_rows

    single_row_result = select_table_facts_for_question(
        "유형 1의 지원자격은 무엇인가요?",
        table_facts,
    )
    single_rows = {selection.fact.row_label for selection in single_row_result.selections}
    assert single_row_result.comparison_mode is False
    assert single_row_result.target_row_labels == ("유형 1",)
    assert single_rows == {"유형 I"}
    assert all(selection.fact.column_label == "지원자격" for selection in single_row_result.selections)

    column_only_result = select_table_facts_for_question(
        "지원자격은 무엇인가요?",
        table_facts,
        max_facts=4,
    )
    column_rows = {selection.fact.row_label for selection in column_only_result.selections}
    assert column_only_result.target_row_labels == ()
    assert {"유형 I", "유형 II", "공통 지원자격", "추가선발"}.issuperset(column_rows)
    assert "면접학과" not in column_rows

    unresolved_comparison = select_table_facts_for_question(
        "유형 I과 유형 II의 차이는 무엇인가요?",
        [
            _fact(0, 1, "유형 II", "지원자격", "검정고시 출신자"),
            _fact(1, 1, "공통", "지원자격", "고등학교 졸업 이상"),
        ],
    )
    assert unresolved_comparison.comparison_mode is True
    assert unresolved_comparison.target_row_labels == ()
    assert unresolved_comparison.selections == ()
    assert unresolved_comparison.diagnostics[0].code == "comparison_target_rows_unresolved"

    print("table fact selector smoke ok")


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
        document_id="selector-smoke",
        table_index=table_index,
        row_index=row_index,
        column_index=column_index,
        row_label=row_label,
        column_label=column_label,
        value=value,
        source_block_id=f"source-{table_index}",
        caption="전형 유형 비교표" if table_index == 1 else "전형료 표",
        row_header_path=(row_label,),
        column_path=(column_label,),
        header_path=("문서 제목", "전형 유형"),
        confidence=0.9,
    )


if __name__ == "__main__":
    main()
