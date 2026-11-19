"""OpenDataLoader JSON 길의 표 사실 행 이름(row_label) 테스트.

지은 학교(가나대학) 자료만 쓴다. 이슈 #264: 행 이름을 늘 첫 칸으로 정해, 첫 열이 연번(1, 2, 3 …)인 표는
「100」 같은 숫자가 행 이름이 되고 실습실명 같은 실제 이름은 칸 값으로 밀려났다.
"""

from __future__ import annotations

from opendataloader_contract_adapter import adapt_opendataloader_json_page
from test_opendataloader_table_caption import _page, _table


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


def test_row_label_skips_repeated_group_column_and_dash_column():
    facts = _facts([
        ["연번", "학부", "비고", "실습실명", "등급"],
        ["1", "가나학부", "―", "가나실습실", "2"],
        ["2", "가나학부", "―", "다라실습실", "1"],
        ["3", "다라학부", "―", "마바실습실", "1"],
    ])

    assert _row_labels(facts) == ["가나실습실", "다라실습실", "마바실습실"]


def test_serial_column_without_distinct_name_column_stays_row_label():
    facts = _facts([
        ["주차", "기간"],
        ["1", "―"],
        ["2", "―"],
        ["3", "―"],
    ])

    assert _row_labels(facts) == ["1", "2", "3"]
