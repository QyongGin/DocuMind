"""OpenDataLoader JSON 길의 표 머리글 줄 수 테스트.

지은 학교(가나대학) 자료만 쓴다. 이슈 #264: 위 머리글 줄에 가로로 합친 칸(「연계 대상」이 두 열)이 있고 그 아래 줄이 하위
머리글(「대학」, 「학과」)인데, 아래 줄 첫 칸이 위 줄 첫 칸과 달라 데이터 줄로 읽혀 열 이름이 「연계 대상」에서 끝났다.
"""

from __future__ import annotations

from opendataloader_contract_adapter import adapt_opendataloader_json_page
from test_opendataloader_table_caption import _cell, _page


def _span_table(element_id: int, rows: list[list[tuple[str, int, int]]]) -> dict:
    """rows: 행마다 (글, 아래로 합친 행 수, 옆으로 합친 열 수) 목록. 합친 칸이 덮는 자리는 목록에서 뺀다."""
    covered: set[tuple[int, int]] = set()
    out_rows = []
    for r, row in enumerate(rows, start=1):
        cells, c = [], 1
        for text, row_span, col_span in row:
            while (r, c) in covered:
                c += 1
            cell = _cell(r, c, text)
            cell["row span"], cell["column span"] = row_span, col_span
            cells.append(cell)
            covered.update((r + i, c + j) for i in range(row_span) for j in range(col_span))
            c += col_span
        out_rows.append({"type": "table row", "row number": r, "cells": cells})
    return {"type": "table", "id": element_id, "rows": out_rows}


def _facts(rows):
    page = _page(1, [{"type": "list", "id": 1, "content": "나. 연계 학과"}, _span_table(2, rows)])
    return adapt_opendataloader_json_page(page, document_id=7, source="가나대학.pdf").table_facts


def test_subheader_row_under_horizontally_merged_header_is_header():
    facts = _facts([
        [("연계 대상", 1, 2), ("지원 가능 학과", 2, 1)],
        [("대학", 1, 1), ("학과", 1, 1)],
        [("가나대학", 1, 1), ("가나학과", 1, 1), ("마바학과", 1, 1)],
        [("다라대학", 1, 1), ("다라학과", 1, 1), ("사아학과", 1, 1)],
    ])

    paths = {fact.value: fact.column_path for fact in facts}
    assert paths["가나학과"] == ("연계 대상", "학과")
    assert paths["마바학과"] == ("지원 가능 학과",)
    assert {fact.row_label for fact in facts} == {"가나대학", "다라대학"}
    assert not any(fact.value in {"대학", "학과"} for fact in facts)


def test_data_row_under_merged_header_stays_data():
    # 합친 칸이 아닌 열에서 위 줄과 글이 다르면(「비고」 아래 「없음」) 데이터 줄이다
    facts = _facts([
        [("학과", 1, 2), ("비고", 1, 1)],
        [("가나학과", 1, 1), ("다라학과", 1, 1), ("없음", 1, 1)],
        [("마바학과", 1, 1), ("사아학과", 1, 1), ("있음", 1, 1)],
    ])

    assert {fact.value for fact in facts} >= {"다라학과", "없음", "사아학과", "있음"}
    assert {fact.column_path for fact in facts if fact.value == "없음"} == {("비고",)}


def test_numeric_row_under_merged_header_stays_data():
    facts = _facts([
        [("모집인원", 1, 2), ("학과", 2, 1)],
        [("30", 1, 1), ("20", 1, 1)],
        [("10", 1, 1), ("5", 1, 1), ("가나학과", 1, 1)],
    ])

    assert {fact.value for fact in facts} >= {"20", "5"}
    assert {fact.column_path for fact in facts if fact.value == "20"} == {("모집인원",)}


def test_row_under_full_width_title_row_stays_data():
    # 위 줄 전체가 한 칸(표 제목)이면 그 아래 「항목 | 값」 줄은 데이터다
    facts = _facts([
        [("가나대학 연락처", 1, 2)],
        [("누리집", 1, 1), ("www.ganada.ac.kr", 1, 1)],
        [("전화", 1, 1), ("02-000-0000", 1, 1)],
    ])

    assert {(fact.row_label, fact.value) for fact in facts} == {("누리집", "www.ganada.ac.kr"), ("전화", "02-000-0000")}
