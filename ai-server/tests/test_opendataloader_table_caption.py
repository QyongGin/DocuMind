"""OpenDataLoader JSON 길의 표 사실 표 이름(caption) 테스트.

지은 학교(가나대학) 자료만 쓴다. 이슈 #264: 표 이름을 그 쪽의 제목 경로에서만 가져와, 제목이 없는 쪽의 표와
제목이 아닌 짧은 줄(목록, 문단) 아래 표가 이름 없이 「문서 표」가 되던 문제.
"""

from __future__ import annotations

import json

from opendataloader_contract_adapter import adapt_opendataloader_json_page


def _cell(row: int, col: int, text: str) -> dict:
    return {
        "type": "table cell",
        "row number": row,
        "column number": col,
        "row span": 1,
        "column span": 1,
        "kids": [{"type": "paragraph", "content": text}],
    }


def _table(element_id: int, rows: list[list[str]]) -> dict:
    return {
        "type": "table",
        "id": element_id,
        "rows": [
            {"type": "table row", "row number": r, "cells": [_cell(r, c, text) for c, text in enumerate(row, start=1)]}
            for r, row in enumerate(rows, start=1)
        ],
    }


def _page(number: int, kids: list[dict]) -> str:
    return json.dumps({"page number": number, "kids": kids}, ensure_ascii=False)


def _captions(result) -> set[str | None]:
    return {fact.caption for fact in result.table_facts}


def test_short_line_right_before_table_becomes_caption():
    page = _page(1, [
        {"type": "heading", "id": 1, "heading level": 1, "content": "가나대학 2027 모집 안내"},
        {"type": "list", "id": 2, "content": "1. 학과별 모집인원"},
        _table(3, [["학과", "모집인원"], ["가나학과", "30"], ["다라학과", "20"]]),
    ])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 모집요강.pdf")

    assert _captions(result) == {"1. 학과별 모집인원"}


def test_long_sentence_or_note_before_table_is_not_caption():
    page = _page(1, [
        {"type": "heading", "id": 1, "heading level": 2, "content": "나. 장학금 안내"},
        {"type": "paragraph", "id": 2, "content": "※ 모집인원은 사정에 따라 바뀔 수 있음"},
        _table(3, [["장학금", "금액"], ["가나장학금", "100"]]),
    ])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 장학.pdf")

    assert _captions(result) == {"나. 장학금 안내"}


def test_table_continued_on_next_page_keeps_previous_caption():
    first = adapt_opendataloader_json_page(
        _page(1, [
            {"type": "list", "id": 1, "content": "2. 실습실 점검 결과"},
            _table(2, [["실습실", "등급"], ["가나실습실", "1"]]),
        ]),
        document_id=7,
        source="가나대학 점검.pdf",
    )
    second = adapt_opendataloader_json_page(
        _page(2, [_table(3, [["실습실", "등급"], ["다라실습실", "2"]])]),
        document_id=7,
        source="가나대학 점검.pdf",
        block_index_offset=len(first.parsed_blocks),
        initial_heading_path=first.last_heading_path,
        previous_table_caption=first.last_table_caption,
    )

    assert _captions(first) == {"2. 실습실 점검 결과"}
    assert _captions(second) == {"2. 실습실 점검 결과"}


def test_heading_path_carries_over_pages_when_nothing_precedes_table():
    first = adapt_opendataloader_json_page(
        _page(1, [
            {"type": "heading", "id": 1, "heading level": 2, "content": "다. 등록금"},
            {"type": "paragraph", "id": 2, "content": "등록금은 학기마다 정해진 기간에 낸다. 자세한 일정은 학사 일정을 따른다."},
        ]),
        document_id=7,
        source="가나대학 등록.pdf",
    )
    second = adapt_opendataloader_json_page(
        _page(2, [_table(3, [["구분", "수업료"], ["첫 학기", "100"]])]),
        document_id=7,
        source="가나대학 등록.pdf",
        block_index_offset=len(first.parsed_blocks),
        initial_heading_path=first.last_heading_path,
        previous_table_caption=first.last_table_caption,
    )

    assert _captions(second) == {"다. 등록금"}


def test_null_characters_from_pdf_text_layer_are_removed_from_caption():
    page = _page(1, [
        {"type": "list", "id": 1, "content": "\x00 3.\x00 학과별\x00 정원"},
        _table(2, [["학과", "정원"], ["가나학과", "30"]]),
    ])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 정원.pdf")

    assert _captions(result) == {"3. 학과별 정원"}


def test_index_artifacts_pass_caption_to_table_continued_on_next_page():
    import main
    from langchain_core.documents import Document

    pages = [
        Document(page_content=_page(1, [
            {"type": "list", "id": 1, "content": "4. 학과별 실습실"},
            _table(2, [["실습실", "호실"], ["가나실습실", "101"]]),
        ])),
        Document(page_content=_page(2, [_table(3, [["실습실", "호실"], ["다라실습실", "102"]])])),
    ]

    artifacts = main._build_opendataloader_json_index_artifacts(pages, "가나대학 실습실.pdf", 7)

    captions = {doc.metadata.get("table_fact_caption") for doc in artifacts.table_fact_docs}
    assert captions == {"4. 학과별 실습실"}


def _caption_after(line: str, heading: str = "라. 학과별 모집인원") -> set[str | None]:
    page = _page(1, [
        {"type": "heading", "id": 1, "heading level": 2, "content": heading},
        {"type": "paragraph", "id": 2, "content": line},
        _table(3, [["학과", "모집인원"], ["가나학과", "30"]]),
    ])
    return _captions(adapt_opendataloader_json_page(page, document_id=7, source="가나대학 모집요강.pdf"))


def test_unit_or_basis_line_before_table_is_not_caption():
    # 표 바로 앞의 단위 표시나 기준 시점 줄은 표 이름이 아니므로 다음 순위(제목 경로)로 넘어간다
    assert _caption_after("(단위: 명, 천 원)") == {"라. 학과별 모집인원"}
    assert _caption_after("(2027. 3. 2. 기준, 단위:명)") == {"라. 학과별 모집인원"}
    assert _caption_after("’27년 3월 기준") == {"라. 학과별 모집인원"}


def test_line_without_name_text_before_table_is_not_caption():
    # 로마 숫자나 번호, 기호만 있는 줄과 「- 아 래 -」 같은 구분 줄은 표 이름이 될 수 없다
    for line in ("IV", "Ⅲ", "5.", "❍", "▶", "- 아 래 -"):
        assert _caption_after(line) == {"라. 학과별 모집인원"}, line


def test_sentence_line_before_table_is_not_caption():
    assert _caption_after("아래와 같이 가나대학 장학생을 선발합니다.") == {"라. 학과별 모집인원"}
    assert _caption_after("8) 이 요강에 없는 사항은 입시위원회가 정한다.") == {"라. 학과별 모집인원"}


def test_heading_that_cannot_be_table_name_is_not_caption():
    page = _page(1, [
        {"type": "heading", "id": 1, "heading level": 2, "content": "본인은 가나대학에 입학하고자 지원합니다."},
        _table(2, [["이름", "연락처"], ["가나", "010"]]),
    ])

    result = adapt_opendataloader_json_page(page, document_id=7, source="가나대학 지원서.pdf")

    assert _captions(result) == {None}


def test_title_lines_with_symbols_or_basis_words_stay_captions():
    # 줄 모양만 보므로 기호로 시작하는 제목, 「기준」으로 끝나는 제목, 괄호에 기준 연도가 든 제목은 그대로 쓴다
    for line in ("□ 선발 방법", "2) 동점자 처리 기준", "□ 등록금 (2027학년도 기준)", "Symbols", "○ 진행 절차"):
        assert _caption_after(line) == {line}, line
