"""색인 글 형식 테스트 — M2 5단계(문서 제목 머리말, 표 행 단위).

검색에 쓰는 글(검색용 청크·BM25·재순위)에는 문서 제목 머리말이 붙어야 하고, PDF 표 칸 사실은 같은 표 안에서
행을 유일하게 가리는 행 경로를, 같은 문서 안에서 서로 다른 표 이름을 가져야 한다. 학과·표 이름을 보지 않는 구조
규칙인지 보려고 모든 데이터는 지어낸 가나대학 것만 쓴다.
"""

from __future__ import annotations

import json

from langchain_core.documents import Document

import main
from rag_contract_builders import (
    build_parsed_block,
    build_retrieval_chunk,
    build_section_node,
    build_source_block,
    build_table_cell_fact,
    compose_retrieval_header,
    document_title_from_source,
)


def _retrieval_chunk(text: str, metadata: dict):
    parsed_block = build_parsed_block(document_id=7, document_format="html", text=text, block_index=0, metadata=metadata)
    section_node = build_section_node(parsed_block)
    source_block = build_source_block(parsed_block, source_index=0)
    return build_retrieval_chunk(parsed_block, source_block, section_node, retrieval_index=0)


def test_document_title_is_upload_file_name_without_extension():
    assert document_title_from_source("교과목개요(가나공학과).html") == "교과목개요(가나공학과)"
    assert document_title_from_source("uploads/2027 가나대학 모집요강.PDF") == "2027 가나대학 모집요강"
    assert document_title_from_source(None) == ""


def test_retrieval_chunk_without_section_path_gets_document_title_header():
    chunk = _retrieval_chunk("전기자기학\n: 전기와 자기 현상을 배운다.", {"source": "교과목개요(가나공학과).html"})
    assert chunk.retrieval_text == "교과목개요(가나공학과)\n전기자기학\n: 전기와 자기 현상을 배운다."
    assert chunk.strategy == "title_prefixed_raw"


def test_retrieval_chunk_header_does_not_repeat_title_in_section_path():
    chunk = _retrieval_chunk(
        "신청은 7월 초다.",
        {"source": "가나대학 생활관.html", "Header 1": "가나대학 생활관", "Header 2": "입사 신청"},
    )
    assert chunk.retrieval_text == "가나대학 생활관\n입사 신청\n신청은 7월 초다."
    assert chunk.strategy == "title_section_prefixed_raw"


def test_bm25_text_adds_title_and_keeps_double_section_weight():
    text = main._build_bm25_document_text("신청은 7월 초다.", {"source": "가나대학 장학 안내.hwp", "Header 1": "신청 기간"})
    assert text == "가나대학 장학 안내\n신청 기간\n신청 기간\n신청은 7월 초다."
    assert main._build_bm25_document_text("본문", {}) == "본문"


def test_rerank_text_uses_same_header_as_retrieval_chunk(monkeypatch):
    sent = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"index": 0, "score": 0.2}, {"index": 1, "score": 0.8}]

    monkeypatch.setattr(main, "RERANKER_URL", "http://reranker.test")
    monkeypatch.setattr(main, "RERANK_CANDIDATES", 2)
    monkeypatch.setattr(main.httpx, "post", lambda url, json=None, timeout=None: sent.append(json) or Response())
    metas = [{"source": "교과목개요(가나공학과).html"}, {"source": "가나대학 생활관.html", "Header 1": "입사 신청"}]
    main._rerank_candidates("질문", ["전기자기학", "신청은 7월 초다."], metas, ["a", "b"])
    assert sent[0]["texts"] == [
        "교과목개요(가나공학과)\n전기자기학",
        compose_retrieval_header("가나대학 생활관", ("입사 신청",)) + "\n신청은 7월 초다.",
    ]


def _cell(row_index: int, column_index: int, row_label: str, column: str, value: str, *, table: int = 1,
          caption: str = "가나대학 장학금 요약표", source: str = "doc-9:source-1"):
    return build_table_cell_fact(
        document_id=9, table_index=table, row_index=row_index, column_index=column_index, row_label=row_label,
        column_label=column, value=value, source_block_id=source, caption=caption,
        row_header_path=(row_label,), column_path=(column,),
    )


def _merged_label_table():
    """첫 칸 '생활비'가 세 행에 병합된 표 — 행 이름만으로는 어느 장학금의 금액인지 알 수 없다."""
    facts = []
    for row_index, (name, amount) in enumerate((("1. 가나 장학", "2.5"), ("2. 다라 장학", "3"), ("3. 마바 장학", "1.5")), 2):
        facts.append(_cell(row_index, 1, "생활비", "장학금명", name))
        facts.append(_cell(row_index, 2, "생활비", "장학 금액", amount))
    return facts


def _ambiguous_groups(texts: list[str]) -> list[str]:
    """같은 표 이름·같은 행 이름·같은 열에 값이 둘 이상인 묶음(행 모호)."""
    seen: dict[tuple[str, str], set[str]] = {}
    for text in texts:
        head, _, value = text.rpartition("=")
        seen.setdefault((head, ""), set()).add(value)
    return [head for (head, _), values in seen.items() if len(values) > 1]


def test_merged_row_label_is_extended_until_each_row_is_unique():
    facts = main._assign_unique_table_row_paths(_merged_label_table())
    texts = [main._format_table_fact_index_text(fact) for fact in facts]
    assert "가나대학 장학금 요약표: 생활비 > 3. 마바 장학 행 정보는 장학 금액=1.5이다." in texts
    assert _ambiguous_groups(texts) == []


def test_rows_already_unique_keep_their_path():
    facts = [_cell(2, 1, "가나공학과", "모집 인원", "40"), _cell(3, 1, "다라공학과", "모집 인원", "35")]
    assert [fact.row_header_path for fact in main._assign_unique_table_row_paths(facts)] == [("가나공학과",), ("다라공학과",)]


def test_repeated_words_from_merged_cell_are_collapsed_in_row_path():
    facts = [_cell(2, 1, "가나공학과 가나공학과 가나공학과", "모집 인원", "40")]
    assert main._assign_unique_table_row_paths(facts)[0].row_header_path == ("가나공학과",)


def test_tables_sharing_a_caption_get_page_or_order_labels():
    facts = [
        _cell(2, 1, "가나공학과", "경쟁률", "11.8", table=1, caption="모집 결과", source="doc-9:source-1"),
        _cell(2, 1, "가나공학과", "경쟁률", "14.5", table=2, caption="모집 결과", source="doc-9:source-2"),
        _cell(2, 1, "가나공학과", "경쟁률", "9.0", table=3, caption="모집 결과", source="doc-9:source-3"),
        _cell(2, 1, "가나공학과", "정원", "40", table=4, caption="학과 정원", source="doc-9:source-4"),
    ]
    pages = {"doc-9:source-1": 17, "doc-9:source-2": 18, "doc-9:source-3": 18, "doc-9:source-4": 2}
    captions = [fact.caption for fact in main._assign_unique_table_row_paths(facts, pages)]
    assert captions == ["모집 결과 (17쪽 표)", "모집 결과 (18쪽 표 1)", "모집 결과 (18쪽 표 2)", "학과 정원"]


def _json_table_page() -> Document:
    def cell(text: str, row: int, column: int, row_span: int = 1) -> dict:
        item = {"type": "table cell", "row number": row, "column number": column, "content": text}
        if row_span > 1:
            item["row span"] = row_span
        return item

    rows = [
        {"type": "table row", "row number": 1,
         "cells": [cell("구분", 1, 1), cell("장학금명", 1, 2), cell("선발 인원", 1, 3), cell("장학 금액", 1, 4)]},
        {"type": "table row", "row number": 2,
         "cells": [cell("생활비", 2, 1, row_span=2), cell("1. 가나 장학", 2, 2), cell("24명", 2, 3), cell("250만원", 2, 4)]},
        {"type": "table row", "row number": 3,
         "cells": [cell("2. 다라 장학", 3, 2), cell("50명", 3, 3), cell("300만원", 3, 4)]},
    ]
    page = {"page number": 1, "kids": [
        {"type": "heading", "heading level": 1, "page number": 1, "content": "가나대학 장학금 요약표"},
        {"type": "table", "id": 10, "page number": 1, "rows": rows},
    ]}
    return Document(page_content=json.dumps(page, ensure_ascii=False), metadata={"page": 1})


def test_pdf_table_index_has_unique_cell_facts_and_one_row_sentence_per_row():
    artifacts = main._build_opendataloader_json_index_artifacts([_json_table_page()], "가나대학 장학 안내.pdf", 9)
    cells = [doc for doc in artifacts.table_fact_docs if doc.metadata.get("table_fact_type") != "row"]
    rows = [doc for doc in artifacts.table_fact_docs if doc.metadata.get("table_fact_type") == "row"]
    assert _ambiguous_groups([doc.page_content for doc in cells]) == []
    assert len(rows) == 2
    row_text = next(doc.page_content for doc in rows if "다라 장학" in doc.page_content)
    assert "장학금명=2. 다라 장학" in row_text and "선발 인원=50명" in row_text and "장학 금액=300만원" in row_text
    lookup_ids = [str(doc.metadata["table_fact_lookup_id"]) for doc in artifacts.table_fact_docs]
    assert len(set(lookup_ids)) == len(lookup_ids)
    # 행 문장은 칸 사실 metadata(typed)를 두지 않아 질의 때 글 표 사실로 읽힌다.
    assert all(main._typed_table_fact_from_metadata(doc.metadata, "") is None for doc in rows)
    assert all(doc.metadata["parent_content"] for doc in rows)
