"""색인할 때 표 청크에 문서 안 표 번호를 남기는 테스트(#269).

지은 학교(가나대학) 자료만 쓴다. 표 하나가 청크 여럿으로 나뉘면 청크에 어느 표의 조각인지가 남지 않아,
다음 단계(표 번호로 그 표의 모든 조각 꺼내기)를 할 수 없었다.
"""

from __future__ import annotations

import json

import chromadb
from langchain_core.documents import Document

from table_numbering import ChunkText, LoaderPage, has_table_rows, number_document_tables

ADMISSION_HEAD = "| 학과 | 모집인원 | 전형료 |\n| --- | --- | --- |"
ADMISSION_ROWS = [
    "| 가나학과 | 30 | 35000 |",
    "| 다라학과 | 25 | 35000 |",
    "| 마바학과 | 40 | 40000 |",
    "| 사아학과 | 20 | 35000 |",
    "| 자차학과 | 35 | 40000 |",
    "| 카타학과 | 15 | 30000 |",
]
ROOM_TABLE = "| 실습실 | 호실 |\n| --- | --- |\n| 가나실습실 | 101 |\n| 다라실습실 | 102 |"
FEE_TABLE = "| 항목 | 금액 |\n| --- | --- |\n| 기숙사비 | 900000 |\n| 식비 | 450000 |"


def _admission_table() -> str:
    return ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS)


def _admission_chunks() -> list[ChunkText]:
    """표 하나를 청크 셋으로 나눈 모양(뒤 청크는 머리 줄을 다시 단다)."""
    return [
        ChunkText("7_0", "## 가. 모집인원\n\n" + ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS[:2])),
        ChunkText("7_1", ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS[2:4])),
        ChunkText("7_2", ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS[4:]) + "\n\n※ 전형료는 원서 접수 때 낸다."),
    ]


# ---------------------------------------------------------------- 번호 규칙


def test_table_split_into_several_chunks_gets_one_number():
    pages = [LoaderPage(None, "# 가나대학 모집요강\n\n## 가. 모집인원\n\n" + _admission_table())]

    numbering = number_document_tables(pages, _admission_chunks())

    assert numbering.table_count == 1
    assert [numbering.numbers_for_chunk(key) for key in ("7_0", "7_1", "7_2")] == [[1], [1], [1]]


def test_chunk_with_two_tables_keeps_both_numbers():
    text = "## 실습실\n\n" + ROOM_TABLE + "\n\n## 생활비\n\n" + FEE_TABLE
    pages = [LoaderPage(None, "# 가나대학 안내\n\n" + _admission_table() + "\n\n" + text)]
    chunks = [ChunkText("7_0", _admission_table()), ChunkText("7_1", text)]

    numbering = number_document_tables(pages, chunks)

    assert numbering.table_count == 3
    assert numbering.numbers_for_chunk("7_0") == [1]
    assert numbering.numbers_for_chunk("7_1") == [2, 3]


def _cell(row: int, col: int, text: str) -> dict:
    return {"type": "table cell", "row number": row, "column number": col,
            "kids": [{"type": "paragraph", "content": text}]}


def _json_table(element_id: int, rows: list[list[str]], previous: int | None = None, following: int | None = None) -> dict:
    table = {
        "type": "table",
        "id": element_id,
        "rows": [{"type": "table row", "cells": [_cell(r, c, text) for c, text in enumerate(row, 1)]}
                 for r, row in enumerate(rows, 1)],
    }
    if previous is not None:
        table["previous table id"] = previous
    if following is not None:
        table["next table id"] = following
    return table


def _cross_page_input(linked: bool):
    """1쪽 끝에서 시작해 2쪽으로 이어지는 표. linked면 JSON에 앞·뒤 표 id가 있다."""
    first = ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS[:3])
    second = "\n".join(ADMISSION_ROWS[3:])
    second_md = "| 사아학과 | 20 | 35000 |\n| --- | --- | --- |\n" + "\n".join(ADMISSION_ROWS[4:])
    pages = [LoaderPage(1, "## 모집인원\n\n" + first), LoaderPage(2, second_md + "\n\n다음 안내")]
    head = ["학과", "모집인원", "전형료"]
    rows = [row.strip("| ").split(" | ") for row in ADMISSION_ROWS]
    json_pages = [
        (1, {"page number": 1, "kids": [_json_table(10, [head, *rows[:3]], following=11 if linked else None)]}),
        (2, {"page number": 2, "kids": [_json_table(11, rows[3:], previous=10 if linked else None)]}),
    ]
    chunks = [ChunkText("7_0", first, 1, 1), ChunkText("7_1", second, 2, 2)]
    blocks = [
        ChunkText("7_odl_0", "\n".join(" | ".join(r) for r in [head, *rows[:3]]), 1),
        ChunkText("7_odl_1", "\n".join(" | ".join(r) for r in rows[3:]), 2),
    ]
    return pages, chunks, json_pages, blocks


def test_table_across_pages_is_one_number_through_json_table_links():
    pages, chunks, json_pages, blocks = _cross_page_input(linked=True)

    numbering = number_document_tables(pages, chunks, json_pages, blocks)

    assert numbering.table_count == 1
    assert numbering.cross_page_links == 1
    assert numbering.numbers_for_chunk("7_0") == numbering.numbers_for_chunk("7_1") == [1]
    assert numbering.numbers_for_block("7_odl_0") == numbering.numbers_for_block("7_odl_1") == [1]


def test_tables_on_two_pages_without_json_link_stay_separate():
    pages, chunks, json_pages, blocks = _cross_page_input(linked=False)

    numbering = number_document_tables(pages, chunks, json_pages, blocks)

    assert numbering.table_count == 2
    assert numbering.numbers_for_chunk("7_0") == [1]
    assert numbering.numbers_for_chunk("7_1") == [2]
    assert numbering.numbers_for_block("7_odl_1") == [2]


def test_document_without_table_has_no_numbers():
    text = "# 가나대학 학사 안내\n\n수강 신청은 학기 시작 전 두 주 동안 한다."
    numbering = number_document_tables([LoaderPage(None, text)], [ChunkText("7_0", text)])

    assert numbering.table_count == 0
    assert numbering.numbers_for_chunk("7_0") == []


def test_box_with_less_than_two_rows_or_columns_is_not_a_table():
    one_row = "| 문의: 가나대학 입학처 |\n\n| 가나학과 | 30 |"
    one_column = "| 비고 |\n| --- |\n| 원서는 온라인으로만 받는다 |\n| 마감 뒤에는 받지 않는다 |"
    text = one_row + "\n\n본문\n\n" + one_column

    numbering = number_document_tables([LoaderPage(None, text)], [ChunkText("7_0", text)])

    assert not has_table_rows(text)
    assert numbering.table_count == 0
    assert numbering.numbers_for_chunk("7_0") == []


def test_same_input_gives_same_numbers():
    pages, chunks, json_pages, blocks = _cross_page_input(linked=True)
    extra = [LoaderPage(3, ROOM_TABLE + "\n\n" + FEE_TABLE)]
    extra_chunks = [ChunkText("7_2", ROOM_TABLE + "\n\n" + FEE_TABLE, 3, 3)]

    first = number_document_tables(pages + extra, chunks + extra_chunks, json_pages, blocks)
    second = number_document_tables(pages + extra, chunks + extra_chunks, json_pages, blocks)

    assert first.chunk_tables == second.chunk_tables
    assert first.block_tables == second.block_tables
    assert first.numbers_for_chunk("7_2") == [2, 3]


# ---------------------------------------------------------------- 색인 경로


def _index_inputs():
    """마크다운 표 두 개(하나는 청크 둘로 나뉨)와 표 없는 청크 하나가 든 문서."""
    loader_docs = [Document(page_content="# 가나대학 안내\n\n" + _admission_table() + "\n\n## 실습실\n\n" + ROOM_TABLE
                            + "\n\n## 학사\n\n수강 신청은 학기 시작 전에 한다.", metadata={})]
    final_docs = [
        Document(page_content=ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS[:3]), metadata={"Header 1": "가나대학 안내"}),
        Document(page_content=ADMISSION_HEAD + "\n" + "\n".join(ADMISSION_ROWS[3:]), metadata={"Header 1": "가나대학 안내"}),
        Document(page_content="## 실습실\n\n" + ROOM_TABLE, metadata={"Header 2": "실습실"}),
        Document(page_content="## 학사\n\n수강 신청은 학기 시작 전에 한다.", metadata={"Header 2": "학사"}),
    ]
    return loader_docs, final_docs


def _build(main, final_docs, loader_docs, artifacts=None):
    return main._build_index_documents(final_docs, "가나대학 안내.md", 7, [], artifacts, loader_docs=loader_docs)


def test_index_documents_keep_text_ids_and_count_and_only_add_table_numbers():
    import main

    loader_docs, final_docs = _index_inputs()
    before = _build(main, final_docs, None)
    after = _build(main, final_docs, loader_docs)

    for old_docs, new_docs in zip(before[:3], after[:3]):
        assert len(old_docs) == len(new_docs)
        assert [d.page_content for d in old_docs] == [d.page_content for d in new_docs]
        assert [main._build_index_document_id(7, d.metadata, i) for i, d in enumerate(old_docs)] == \
            [main._build_index_document_id(7, d.metadata, i) for i, d in enumerate(new_docs)]
        for old, new in zip(old_docs, new_docs):
            added = {k: v for k, v in new.metadata.items() if k not in old.metadata}
            assert {k: v for k, v in new.metadata.items() if k in old.metadata} == old.metadata
            assert set(added) <= {"table_numbers"}
    assert after[4] == before[4]  # 표 사실 수


def test_raw_chunk_and_source_block_carry_table_numbers():
    import main

    loader_docs, final_docs = _index_inputs()
    index_docs, source_docs, retrieval_docs, _, _ = _build(main, final_docs, loader_docs)

    raw = {d.metadata["chunk_index"]: d.metadata.get("table_numbers") for d in index_docs if d.metadata["chunk_role"] == "raw"}
    source = {d.metadata["chunk_index"]: d.metadata.get("table_numbers") for d in source_docs}
    assert raw == source == {0: [1], 1: [1], 2: [2], 3: None}
    assert [d.metadata.get("table_numbers") for d in retrieval_docs] == [[1], [1], [2], None]


def test_opendataloader_source_blocks_and_table_facts_get_json_table_number():
    import main

    pages = [
        Document(page_content=json.dumps({"page number": 1, "kids": [
            {"type": "heading", "id": 1, "heading level": 2, "content": "가. 모집인원"},
            _json_table(2, [["학과", "모집인원"], ["가나학과", "30"], ["다라학과", "25"]], following=3),
        ]}, ensure_ascii=False), metadata={"page": 1}),
        Document(page_content=json.dumps({"page number": 2, "kids": [
            _json_table(3, [["마바학과", "40"], ["사아학과", "20"]], previous=2),
        ]}, ensure_ascii=False), metadata={"page": 2}),
    ]
    artifacts = main._build_opendataloader_json_index_artifacts(pages, "가나대학 모집요강.pdf", 7)
    loader_docs = [
        Document(page_content="## 가. 모집인원\n\n| 학과 | 모집인원 |\n| --- | --- |\n| 가나학과 | 30 |\n| 다라학과 | 25 |",
                 metadata={"page": 1}),
        Document(page_content="| 마바학과 | 40 |\n| --- | --- |\n| 사아학과 | 20 |", metadata={"page": 2}),
    ]
    final_docs = [Document(page_content=doc.page_content, metadata={}) for doc in loader_docs]

    index_docs, source_docs, _, _, _ = main._build_index_documents(
        final_docs, "가나대학 모집요강.pdf", 7, [], artifacts, loader_docs=loader_docs
    )

    odl_sources = [d for d in source_docs if d.metadata.get("parser_name") == main.OPENDATALOADER_JSON_TABLE_FACT_SOURCE]
    odl_facts = [d for d in index_docs if d.metadata.get("table_fact_source") == main.OPENDATALOADER_JSON_TABLE_FACT_SOURCE]
    assert len(odl_sources) == 2 and odl_facts
    assert {tuple(d.metadata["table_numbers"]) for d in odl_sources + odl_facts} == {(1,)}
    raw = [d.metadata.get("table_numbers") for d in source_docs if d.metadata.get("parser_name") is None]
    assert raw == [[1], [1]]
    # 표 번호를 넣기 전 묶음은 그대로다(다시 색인해도 같은 입력에서 시작한다)
    assert all("table_numbers" not in d.metadata for d in artifacts.source_docs + artifacts.table_fact_docs)


def test_chroma_accepts_table_numbers_and_finds_every_piece_of_one_table():
    import main

    loader_docs, final_docs = _index_inputs()
    _, source_docs, _, _, _ = _build(main, final_docs, loader_docs)
    client = chromadb.EphemeralClient()
    collection = client.create_collection("ganadae_table_numbers_test")
    collection.add(
        ids=[d.metadata["source_lookup_id"] for d in source_docs],
        documents=[d.page_content for d in source_docs],
        metadatas=[d.metadata for d in source_docs],
        embeddings=[[float(i), 1.0] for i in range(len(source_docs))],
    )

    found = collection.get(where={"$and": [{"document_id": "7"}, {"table_numbers": {"$contains": 1}}]})

    assert sorted(found["ids"]) == ["7_0_source", "7_1_source"]
