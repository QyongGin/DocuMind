"""OpenDataLoader JSON 길의 표 칸 글에서 PDF 빈 문자(\\x00)를 지우는 테스트.

지은 학교(가나대학) 자료만 쓴다. 이슈 #264: PDF 글자 층의 빈 문자가 칸 글 끝이나 공백 옆에 섞여 나와
「반영\\x00 총점」 같은 열 이름과 칸 값이 표 사실과 프롬프트에 그대로 들어갔다. 표 이름에서만 지우고 있었다.
"""

from __future__ import annotations

from opendataloader_contract_adapter import adapt_opendataloader_json_page
from test_opendataloader_table_caption import _page, _table
from test_opendataloader_table_row_label import _merged_table


def _facts(table: dict):
    page = _page(1, [{"type": "list", "id": 1, "content": "가. 성적 반영"}, table])
    return adapt_opendataloader_json_page(page, document_id=7, source="가나대학.pdf").table_facts


def _all_text(facts) -> list[str]:
    out = []
    for fact in facts:
        out += [fact.value, fact.column_label, fact.row_label, *fact.column_path, *fact.row_header_path]
    return out


def test_null_characters_are_removed_from_values_columns_and_row_labels():
    facts = _facts(_table(2, [
        ["학과\x00", "반영\x00 총점", "면접\x00"],
        ["가나학과\x00", "200점\x00", "\x00 있음"],
        ["다라학과", "300점", "없음"],
    ]))

    assert facts
    assert not any("\x00" in text for text in _all_text(facts))
    first_row = [fact for fact in facts if fact.row_label == "가나학과"]
    assert {(fact.column_label, fact.value) for fact in first_row} == {("반영 총점", "200점"), ("면접", "있음")}


def test_null_characters_are_removed_from_row_header_path_of_merged_group_column():
    facts = _facts(_merged_table(2, [
        ["계열", "학과", "정원"],
        ["공학\x00 계열", "가나학과", "30"],
        ["", "다라학과", "40"],
        ["인문 계열\x00", "마바학과", "50"],
    ], spans={(2, 1): 2}))

    paths = {fact.row_label: fact.row_header_path for fact in facts}
    assert paths["가나학과"] == ("공학 계열", "가나학과")
    assert paths["다라학과"] == ("공학 계열", "다라학과")
    assert not any("\x00" in text for text in _all_text(facts))


def _caption_of(kids: list[dict]) -> set:
    page = _page(1, kids)
    return {fact.caption for fact in adapt_opendataloader_json_page(page, document_id=7, source="가나대학.pdf").table_facts}


def test_null_characters_are_removed_from_heading_path_caption():
    table = _table(3, [["구분", "면접 학과"], ["수시", "가나학과"], ["정시", "다라학과"]])
    caption = _caption_of([
        {"type": "heading", "id": 1, "heading level": 1, "content": "Ⅲ.\x00 면접고사"},
        {"type": "paragraph", "id": 2, "content": "※ 면접 일정은 학과별로 따로 알림"},
        table,
    ])

    assert caption == {"Ⅲ. 면접고사"}


def test_heading_made_only_of_null_characters_is_not_used_as_caption():
    table = _table(4, [["구분", "가산점"], ["1등급", "20점"], ["2등급", "16점"]])
    caption = _caption_of([
        {"type": "heading", "id": 1, "heading level": 1, "content": "가. 영어 가산점"},
        {"type": "heading", "id": 2, "heading level": 2, "content": "\x00 \x00"},
        {"type": "paragraph", "id": 3, "content": "※ 다른 영역에는 가산점 없음"},
        table,
    ])

    assert caption == {"가. 영어 가산점"}


def test_linked_caption_of_only_null_characters_falls_back_to_heading():
    table = _table(3, [["학과", "정원"], ["가나학과", "30"], ["다라학과", "40"]])
    caption = _caption_of([
        {"type": "heading", "id": 1, "heading level": 1, "content": "1. 학과별 정원"},
        {"type": "caption", "id": 2, "content": "\x00 \x00", "linked content id": 3},
        table,
    ])

    assert caption == {"1. 학과별 정원"}
