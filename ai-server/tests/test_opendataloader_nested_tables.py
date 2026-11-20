"""OpenDataLoader JSON 길이 목록(list) 안에 든 표도 표 사실로 만드는지 테스트.

지은 학교(가나대학) 자료만 쓴다. 이슈 #264: 목록 요소는 하위 요소를 내려가 보지 않아, 「다. 영어 가산점」 같은
목록 항목 아래에 든 표가 표 사실 없이 빠졌다(PDF 29문서 표 595개 중 35개).
"""

from __future__ import annotations

from opendataloader_contract_adapter import adapt_opendataloader_json_page
from test_opendataloader_table_caption import _page, _table


def _list(element_id: int, items: list[dict]) -> dict:
    return {"type": "list", "id": element_id, "list items": items}


def _item(content: str, kids: list[dict]) -> dict:
    return {"type": "list item", "content": content, "kids": kids}


def test_table_inside_list_item_becomes_table_facts_with_item_title():
    page = _page(1, [
        _list(1, [
            _item("가. 성적 반영 방법", [{"type": "paragraph", "content": "학생부 성적을 반영한다."}]),
            _item("나. 영어 가산점", [_table(2, [["구분", "1등급", "2등급"], ["가산점", "10점", "5점"]])]),
            _item("다. 동점자 처리", [{"type": "paragraph", "content": "동점이면 학생부 성적을 먼저 본다."}]),
        ]),
    ])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 모집요강.pdf")

    values = {(fact.column_label, fact.value) for fact in result.table_facts}
    assert values == {("1등급", "10점"), ("2등급", "5점")}
    assert {fact.caption for fact in result.table_facts} == {"나. 영어 가산점"}


def test_table_inside_nested_list_is_collected():
    inner = _list(3, [_item("1) 동점자 기준", [_table(4, [["순위", "기준"], ["1순위", "가나점수"], ["2순위", "다라점수"]])])])
    page = _page(1, [_list(1, [_item("라. 동점자 처리", [inner])])])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 모집요강.pdf")

    assert {(fact.row_label, fact.value) for fact in result.table_facts} == {("1순위", "가나점수"), ("2순위", "다라점수")}


def test_table_inside_table_cell_is_not_collected_separately():
    outer = _table(1, [["구분", "내용"], ["가나", "안쪽 표"]])
    outer["rows"][1]["cells"][1]["kids"].append(_table(2, [["가", "나"], ["1", "2"]]))
    page = _page(1, [outer])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 안내.pdf")

    assert len({fact.table_id for fact in result.table_facts}) == 1
