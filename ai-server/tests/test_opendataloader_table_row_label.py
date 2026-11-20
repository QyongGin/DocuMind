"""OpenDataLoader JSON 길의 표 사실 행 이름(row_label) 테스트.

지은 학교(가나대학) 자료만 쓴다. 이슈 #264: 행 이름을 늘 첫 칸으로 정해, 첫 열이 연번(1, 2, 3 …)인 표는
「100」 같은 숫자가 행 이름이 되고 실습실명 같은 실제 이름은 칸 값으로 밀려났다.
"""

from __future__ import annotations

from opendataloader_contract_adapter import adapt_opendataloader_json_page
from test_opendataloader_table_caption import _cell, _page, _table


def _merged_table(element_id: int, rows: list[list[str]], spans: dict[tuple[int, int], int]) -> dict:
    """spans: (행, 열)(1부터) → 아래로 합친 행 수. 합친 칸이 덮는 아래 칸은 빼고 만든다."""
    covered = {(r + k, c) for (r, c), n in spans.items() for k in range(1, n)}
    out_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, text in enumerate(row, start=1):
            if (r, c) in covered:
                continue
            cell = _cell(r, c, text)
            cell["row span"] = spans.get((r, c), 1)
            cells.append(cell)
        out_rows.append({"type": "table row", "row number": r, "cells": cells})
    return {"type": "table", "id": element_id, "rows": out_rows}


def _merged_facts(rows, spans):
    page = _page(1, [{"type": "list", "id": 1, "content": "가. 표"}, _merged_table(2, rows, spans)])
    return adapt_opendataloader_json_page(page, document_id=7, source="가나대학.pdf").table_facts


def _facts(rows: list[list[str]]):
    page = _page(1, [{"type": "list", "id": 1, "content": "가. 표"}, _table(2, rows)])
    return adapt_opendataloader_json_page(page, document_id=7, source="가나대학.pdf").table_facts


def _row_labels(facts) -> list[str]:
    seen: list[str] = []
    for fact in facts:
        if fact.row_label not in seen:
            seen.append(fact.row_label)
    return seen


def test_serial_number_first_column_is_not_row_label():
    facts = _facts([
        ["연번", "실습실명", "호실", "등급"],
        ["1", "가나실습실", "101", "2"],
        ["2", "다라실습실", "102", "1"],
        ["3", "마바실습실", "103", "1"],
    ])

    assert _row_labels(facts) == ["가나실습실", "다라실습실", "마바실습실"]
    serials = {(fact.row_label, fact.value) for fact in facts if fact.column_label == "연번"}
    assert serials == {("가나실습실", "1"), ("다라실습실", "2"), ("마바실습실", "3")}
    assert not any(fact.column_label == "실습실명" for fact in facts)


def test_year_first_column_stays_row_label():
    facts = _facts([
        ["연도", "취득자"],
        ["2021", "12"],
        ["2022", "7"],
        ["2023", "3"],
    ])

    assert _row_labels(facts) == ["2021", "2022", "2023"]


def test_text_first_column_stays_row_label():
    facts = _facts([
        ["학과", "정원", "순위"],
        ["가나학과", "30", "1"],
        ["다라학과", "20", "2"],
        ["마바학과", "10", "3"],
    ])

    assert _row_labels(facts) == ["가나학과", "다라학과", "마바학과"]


def test_non_consecutive_numbers_are_not_treated_as_serial():
    facts = _facts([
        ["학번", "이름", "학점"],
        ["17", "가나", "3"],
        ["42", "다라", "2"],
        ["5", "마바", "1"],
    ])

    assert _row_labels(facts) == ["17", "42", "5"]


def test_row_label_skips_merged_group_column_after_serial():
    facts = _merged_facts([
        ["연번", "학부", "실습실명", "등급"],
        ["1", "가나학부", "가나실습실", "2"],
        ["2", "가나학부", "다라실습실", "1"],
        ["3", "다라학부", "마바실습실", "1"],
    ], {(2, 2): 2})

    assert _row_labels(facts) == ["가나실습실", "다라실습실", "마바실습실"]


def test_repeated_column_that_is_not_merged_is_not_a_group():
    facts = _facts([
        ["학과", "참여 여부", "자격증", "학점"],
        ["가나학과", "참여", "가나기사", "2"],
        ["가나학과", "미참여", "다라기사", "3"],
        ["다라학과", "참여", "마바기사", "2"],
    ])

    assert _row_labels(facts) == ["가나학과", "다라학과"]


def test_serial_column_without_distinct_name_column_stays_row_label():
    facts = _facts([
        ["주차", "기간"],
        ["1", "―"],
        ["2", "―"],
        ["3", "―"],
    ])

    assert _row_labels(facts) == ["1", "2", "3"]


def test_group_columns_before_name_column_become_row_path():
    facts = _merged_facts([
        ["계열", "학부", "학과", "정원"],
        ["인문사회", "가나학부", "가나학과", "60"],
        ["인문사회", "가나학부", "다라학과", "20"],
        ["인문사회", "마바학부", "마바학과", "15"],
        ["공학", "사아학부", "사아학과", "40"],
    ], {(2, 1): 3, (2, 2): 2})

    assert _row_labels(facts) == ["가나학과", "다라학과", "마바학과", "사아학과"]
    paths = {fact.row_label: fact.row_header_path for fact in facts}
    assert paths["가나학과"] == ("인문사회", "가나학부", "가나학과")
    assert paths["사아학과"] == ("공학", "사아학부", "사아학과")


def test_numeric_column_between_serial_and_name_is_skipped():
    facts = _facts([
        ["연번", "호실", "실습실명", "등급"],
        ["1", "101", "가나실습실", "2"],
        ["2", "102", "다라실습실", "1"],
        ["3", "103", "마바실습실", "1"],
    ])

    assert _row_labels(facts) == ["가나실습실", "다라실습실", "마바실습실"]


def test_repeated_column_after_serial_is_skipped_without_path():
    facts = _facts([
        ["연번", "관리소속", "실습실명", "등급"],
        ["1", "가나학과", "가나실습실", "2"],
        ["2", "가나학과", "다라실습실", "1"],
        ["3", "다라학과", "마바실습실", "1"],
    ])

    assert _row_labels(facts) == ["가나실습실", "다라실습실", "마바실습실"]
    assert {fact.row_header_path for fact in facts} == {("가나실습실",), ("다라실습실",), ("마바실습실",)}


def test_cell_merged_across_group_and_name_columns_appears_once_in_row_path():
    # 학과명, 구분은 세로로 합친 묶음 열, 자격증명은 값이 겹치는 열이라 교과목이 행 이름이 된다.
    # 한 학과는 「미참여」 한 칸이 구분부터 교과목까지 가로로 합쳐져 있어 묶음 열 값과 행 이름이 같은 칸이다
    def cell(r, c, text, rs=1, cs=1):
        return {"type": "table cell", "row number": r, "column number": c, "row span": rs, "column span": cs,
                "kids": [{"type": "paragraph", "content": text}]}

    rows = [
        [cell(1, 1, "학과명"), cell(1, 2, "구분"), cell(1, 3, "자격증명"), cell(1, 4, "매칭 교과목")],
        [cell(2, 1, "가나학과", rs=2), cell(2, 2, "국가기술자격", rs=2), cell(2, 3, "가나산업기사"), cell(2, 4, "가나실습")],
        [cell(3, 3, "가나산업기사"), cell(3, 4, "다라실습")],
        [cell(4, 1, "마바학과"), cell(4, 2, "미참여", cs=3)],
        [cell(5, 1, "사아학과"), cell(5, 2, "민간자격"), cell(5, 3, "사아자격"), cell(5, 4, "사아실습")],
    ]
    table = {"type": "table", "id": 2,
             "rows": [{"type": "table row", "row number": n, "cells": cs} for n, cs in enumerate(rows, start=1)]}
    page = _page(1, [{"type": "list", "id": 1, "content": "가. 학점인정 자격증"}, table])
    facts = adapt_opendataloader_json_page(page, document_id=7, source="가나대학.pdf").table_facts

    paths = {fact.row_header_path for fact in facts}
    assert all(len(path) == len(set(path)) for path in paths)
    assert ("마바학과", "미참여") in paths
    assert ("가나학과", "국가기술자격", "가나실습") in paths
    assert {fact.row_label for fact in facts} == {"가나실습", "다라실습", "미참여", "사아실습"}
