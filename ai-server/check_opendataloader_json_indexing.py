"""Smoke checks for OpenDataLoader JSON TableFact upload indexing."""

from __future__ import annotations

import json
import os
import tempfile

from langchain_core.documents import Document

# main.py initializes a Chroma PersistentClient at import time. Keep that import
# in a temporary cwd so root-level smoke runs do not create ./chroma_db.
_ORIGINAL_CWD = os.getcwd()
_SMOKE_WORKDIR = tempfile.TemporaryDirectory(prefix="documind-chroma-smoke-")
_SMOKE_CHROMA_HOST = os.environ.pop("CHROMA_HOST", None)
os.chdir(_SMOKE_WORKDIR.name)
try:
    import main as runtime_main
    from main import (
        OPENDATALOADER_JSON_TABLE_FACT_SOURCE,
        _build_index_document_id,
        _build_index_documents,
        _build_bm25_sparse_index,
        _build_opendataloader_json_index_artifacts,
        _expand_table_fact_results,
        _priority_table_fact_evidence_for_prompt,
        _typed_table_fact_contract_candidates,
    )
finally:
    os.chdir(_ORIGINAL_CWD)
    if _SMOKE_CHROMA_HOST is not None:
        os.environ["CHROMA_HOST"] = _SMOKE_CHROMA_HOST


def _cell(text: str, *, row: int, column: int, row_span: int = 1) -> dict:
    cell = {
        "type": "table cell",
        "row number": row,
        "column number": column,
        "content": text,
    }
    if row_span > 1:
        cell["row span"] = row_span
    return cell


def _json_page(page: int, title: str, rows: list[tuple[str, str]]) -> Document:
    table_rows = [
        {
            "type": "table row",
            "row number": 1,
            "cells": [
                _cell("구분", row=1, column=1),
                _cell("지원자격", row=1, column=2),
            ],
        }
    ]
    for row_number, (row_label, value) in enumerate(rows, start=2):
        table_rows.append(
            {
                "type": "table row",
                "row number": row_number,
                "cells": [
                    _cell(row_label, row=row_number, column=1),
                    _cell(value, row=row_number, column=2),
                ],
            }
        )

    page_json = {
        "page number": page,
        "kids": [
            {
                "type": "heading",
                "heading level": 1,
                "page number": page,
                "content": title,
            },
            {
                "type": "table",
                "id": page * 10,
                "page number": page,
                "rows": table_rows,
            },
        ],
    }
    return Document(page_content=json.dumps(page_json, ensure_ascii=False), metadata={"page": page})


def _rowspan_json_page() -> Document:
    table_rows = [
        {
            "type": "table row",
            "row number": 1,
            "cells": [
                _cell("구분", row=1, column=1),
                _cell("유형", row=1, column=2),
                _cell("지원자격", row=1, column=3),
            ],
        },
        {
            "type": "table row",
            "row number": 2,
            "cells": [
                _cell("지역전형", row=2, column=1, row_span=2),
                _cell("유형Ⅰ", row=2, column=2),
                _cell("중학교 입학일부터 고등학교 졸업일까지 거주", row=2, column=3),
            ],
        },
        {
            "type": "table row",
            "row number": 3,
            "cells": [
                _cell("유형Ⅱ", row=3, column=2),
                _cell("초등학교 입학일부터 고등학교 졸업일까지 거주", row=3, column=3),
            ],
        },
    ]
    page_json = {
        "page number": 3,
        "kids": [
            {
                "type": "heading",
                "heading level": 1,
                "page number": 3,
                "content": "지역전형 지원자격",
            },
            {
                "type": "table",
                "id": 30,
                "page number": 3,
                "rows": table_rows,
            },
        ],
    }
    return Document(page_content=json.dumps(page_json, ensure_ascii=False), metadata={"page": 3})


class _FakeBm25Collection:
    def __init__(self, raw_count: int) -> None:
        self.raw_count = raw_count
        self.get_calls: list[dict] = []

    def count(self) -> int:
        raise AssertionError("BM25 raw limit must not use total collection.count()")

    def get(self, **kwargs) -> dict:
        self.get_calls.append(kwargs)
        assert kwargs["where"] == {"chunk_role": "raw"}
        assert kwargs["include"] == ["documents", "metadatas"]
        assert kwargs["limit"] == 3
        ids = [f"raw-{index}" for index in range(self.raw_count)]
        return {
            "ids": ids,
            "documents": [f"alpha beta {index}" for index in range(self.raw_count)],
            "metadatas": [
                {
                    "chunk_role": "raw",
                    "Header 1": "BM25",
                }
                for _ in range(self.raw_count)
            ],
        }


def _check_bm25_limit_uses_raw_records() -> None:
    original_collection = runtime_main.collection
    original_max_entries = runtime_main.BM25_INDEX_MAX_ENTRIES
    try:
        runtime_main.BM25_INDEX_MAX_ENTRIES = 2

        within_limit_collection = _FakeBm25Collection(raw_count=2)
        runtime_main.collection = within_limit_collection
        sparse_index = _build_bm25_sparse_index()
        assert len(sparse_index.records) == 2
        assert len(within_limit_collection.get_calls) == 1

        over_limit_collection = _FakeBm25Collection(raw_count=3)
        runtime_main.collection = over_limit_collection
        sparse_index = _build_bm25_sparse_index()
        assert sparse_index.records == []
        assert len(over_limit_collection.get_calls) == 1
    finally:
        runtime_main.collection = original_collection
        runtime_main.BM25_INDEX_MAX_ENTRIES = original_max_entries


def main() -> None:
    """Verify OpenDataLoader JSON facts are indexable and typed at query time."""
    json_docs = [
        _json_page(
            1,
            "전형 지원자격",
            [
                ("유형Ⅰ", "중학교 입학일부터 고등학교 졸업일까지 거주"),
                ("유형Ⅱ", "초등학교 입학일부터 고등학교 졸업일까지 거주"),
            ],
        ),
        _json_page(2, "전형 지원자격", [("기타", "별도 공지")]),
    ]
    artifacts = _build_opendataloader_json_index_artifacts(
        json_docs,
        filename="sample.pdf",
        document_id=103,
    )

    assert len(artifacts.source_docs) == 2
    assert len(artifacts.table_fact_docs) == 3

    fact_ids = {
        doc.metadata["table_fact_id"]
        for doc in artifacts.table_fact_docs
    }
    assert len(fact_ids) == 3

    lookup_ids = {
        _build_index_document_id(103, doc.metadata, index)
        for index, doc in enumerate(artifacts.table_fact_docs)
    }
    assert lookup_ids == {"103_odl_fact_0", "103_odl_fact_1", "103_odl_fact_2"}

    for fact_doc in artifacts.table_fact_docs:
        metadata = fact_doc.metadata
        assert metadata["table_fact_source"] == OPENDATALOADER_JSON_TABLE_FACT_SOURCE
        assert "kids" not in metadata
        assert "rows" not in metadata
        assert "구분 | 지원자격" in metadata["parent_content"]
        typed_candidates = _typed_table_fact_contract_candidates(
            chunk_id=metadata["table_fact_lookup_id"],
            doc=fact_doc.page_content,
            meta=metadata,
            source_block_id=metadata["source_block_id"],
        )
        assert len(typed_candidates) == 1
        table_fact, fact_source = typed_candidates[0]
        assert fact_source == "typed_table_fact_metadata"
        assert table_fact.row_label in {"유형Ⅰ", "유형Ⅱ", "기타"}
        assert table_fact.column_label == "지원자격"

    index_docs, source_docs, retrieval_docs, _, table_fact_count = _build_index_documents(
        [Document(page_content="# 전형 지원자격\n\n기존 Markdown 청크", metadata={"page": 1})],
        "sample.pdf",
        103,
        [],
        artifacts,
    )
    assert len(source_docs) == 3
    assert len(retrieval_docs) == 1
    assert table_fact_count == 3
    assert sum(1 for doc in index_docs if doc.metadata.get("table_fact_source")) == 3

    comparison_docs = artifacts.table_fact_docs[:2]
    expanded_docs, expanded_metadatas, expanded_ids = _expand_table_fact_results(
        [doc.page_content for doc in comparison_docs],
        [doc.metadata for doc in comparison_docs],
        [doc.metadata["table_fact_lookup_id"] for doc in comparison_docs],
    )
    assert len(expanded_docs) == 1

    priority_evidence = _priority_table_fact_evidence_for_prompt(
        "유형 I과 유형 II의 지원자격은?",
        expanded_docs,
        expanded_metadatas,
        expanded_ids,
    )
    assert priority_evidence is not None
    assert "행: 유형Ⅰ / 열: 지원자격" in priority_evidence.evidence_text
    assert "행: 유형Ⅱ / 열: 지원자격" in priority_evidence.evidence_text

    rowspan_artifacts = _build_opendataloader_json_index_artifacts(
        [_rowspan_json_page()],
        filename="sample.pdf",
        document_id=104,
    )
    support_docs = [
        doc
        for doc in rowspan_artifacts.table_fact_docs
        if doc.metadata["table_fact_column_label"] == "지원자격"
    ]
    assert len(support_docs) == 2
    support_by_row = {
        doc.metadata["table_fact_row_label"]: doc
        for doc in support_docs
    }
    assert set(support_by_row) == {"유형Ⅰ", "유형Ⅱ"}
    assert json.loads(support_by_row["유형Ⅰ"].metadata["table_fact_row_header_path"]) == [
        "지역전형",
        "유형Ⅰ",
    ]
    assert "행 경로=지역전형 > 유형Ⅰ" in support_by_row["유형Ⅰ"].page_content

    rowspan_expanded_docs, rowspan_expanded_metadatas, rowspan_expanded_ids = _expand_table_fact_results(
        [doc.page_content for doc in support_docs],
        [doc.metadata for doc in support_docs],
        [doc.metadata["table_fact_lookup_id"] for doc in support_docs],
    )
    rowspan_evidence = _priority_table_fact_evidence_for_prompt(
        "지역전형 유형 I과 유형 II의 지원자격은?",
        rowspan_expanded_docs,
        rowspan_expanded_metadatas,
        rowspan_expanded_ids,
    )
    assert rowspan_evidence is not None
    assert "행: 지역전형 > 유형Ⅰ / 열: 지원자격" in rowspan_evidence.evidence_text
    assert "행: 지역전형 > 유형Ⅱ / 열: 지원자격" in rowspan_evidence.evidence_text

    _check_bm25_limit_uses_raw_records()

    print("opendataloader json indexing smoke ok")


if __name__ == "__main__":
    main()
