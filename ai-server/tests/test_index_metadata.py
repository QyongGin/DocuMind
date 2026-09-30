"""색인 metadata 테스트.

``_build_chunk_metadata``는 청크의 document_id·source·chunk_index를 색인 기준으로 정한다.
PDF 로더는 metadata의 source에 업로드 임시 파일 경로(tmpXXXX.pdf)를 넣는데, 예전에는
이 값이 원래 파일명을 덮어써서 출처와 프롬프트의 "문서:" 줄에 임시 파일명이 남았다.
"""

from __future__ import annotations

from langchain_core.documents import Document

from main import _build_chunk_metadata


def test_loader_source_does_not_override_original_filename():
    doc = Document(
        page_content="합성 본문",
        metadata={"source": "/tmp/tmpabc123.pdf", "format": "markdown", "Header 1": "합성 제목"},
    )

    meta = _build_chunk_metadata(doc, "2026 합성 모집요강.pdf", 101, 3, [])

    assert meta["source"] == "2026 합성 모집요강.pdf"
    assert meta["document_id"] == "101"
    assert meta["chunk_index"] == 3


def test_other_loader_metadata_is_kept():
    doc = Document(
        page_content="합성 본문",
        metadata={"source": "/tmp/tmpabc123.pdf", "format": "markdown", "Header 1": "합성 제목"},
    )

    meta = _build_chunk_metadata(doc, "합성.pdf", 101, 0, [])

    assert meta["format"] == "markdown"
    assert meta["Header 1"] == "합성 제목"


def test_loader_cannot_override_document_id_or_chunk_index():
    doc = Document(page_content="합성 본문", metadata={"document_id": "999", "chunk_index": 42})

    meta = _build_chunk_metadata(doc, "합성.pdf", 101, 0, [])

    assert meta["document_id"] == "101"
    assert meta["chunk_index"] == 0
