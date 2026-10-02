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


# ── #126 문서 단위 메타데이터(문서 대장 정보·카테고리) ──────────────────────

def test_document_metadata_keeps_only_present_values():
    import main

    assert main._document_metadata_from_form(" www/bbs/1/2 ", "", None, 2026, None, "학사") == {
        "ledger_id": "www/bbs/1/2",
        "academic_year": 2026,
        "category": "학사",
    }
    assert main._document_metadata_from_form() == {}


def test_loader_cannot_set_document_metadata_keys():
    doc = Document(page_content="합성 본문", metadata={"category": "로더 값", "ledger_id": "로더 값", "Header 1": "제목"})

    meta = _build_chunk_metadata(doc, "합성.html", 101, 0, [])

    assert "category" not in meta and "ledger_id" not in meta
    assert meta["Header 1"] == "제목"


class _FakeCollection:
    def __init__(self, name: str, added: dict):
        self.name = name
        self.added = added

    def add(self, **kwargs):
        self.added.setdefault(self.name, []).extend(kwargs["metadatas"])


def test_document_metadata_reaches_every_collection(monkeypatch):
    import main

    added: dict[str, list[dict]] = {}
    monkeypatch.setattr(main, "collection", _FakeCollection("documents", added))
    monkeypatch.setattr(main, "source_block_collection", _FakeCollection("source_blocks", added))
    monkeypatch.setattr(main, "retrieval_chunk_collection", _FakeCollection("retrieval_chunks", added))
    monkeypatch.setattr(main, "_embed_texts", lambda texts: ([[0.0, 1.0] for _ in texts], {}))
    docs = [Document(page_content="학사 안내\n\n| 구분 | 금액 |\n| --- | --- |\n| 수업료 | 100 |", metadata={})]
    metadata = main._document_metadata_from_form(
        "www/bbs/11/1/a2", "https://www.example.ac.kr/notice/1", "2026-08-01", 2026, 3, "학사"
    )

    main._store_document_chunks(docs, "합성.html", 777, [], None, metadata)

    assert "documents" in added and "source_blocks" in added
    roles = {meta.get("chunk_role") for meta in added["documents"]}
    assert {"raw", "table_fact"} <= roles
    for name, metadatas in added.items():
        for meta in metadatas:
            assert meta["ledger_id"] == "www/bbs/11/1/a2", name
            assert meta["source_url"] == "https://www.example.ac.kr/notice/1", name
            assert meta["posted_at"] == "2026-08-01", name
            assert meta["academic_year"] == 2026 and meta["category_id"] == 3 and meta["category"] == "학사", name


def test_upload_endpoint_passes_form_metadata_to_pipeline(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    captured = {}

    async def fake_pipeline(tmp_path, filename, document_id, document_metadata=None):
        captured.update(filename=filename, document_id=document_id, metadata=document_metadata)
        return 1

    monkeypatch.setattr(main, "_run_upload_pipeline", fake_pipeline)
    response = TestClient(main.app).post(
        "/documents",
        files={"file": ("안내.html", "<p>합성</p>".encode("utf-8"), "text/html")},
        data={
            "document_id": "55",
            "ledger_id": "www/page/236",
            "source_url": "https://www.example.ac.kr/page/236",
            "academic_year": "2026",
            "category_id": "4",
            "category": "기타",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "filename": "안내.html",
        "document_id": 55,
        "metadata": {
            "ledger_id": "www/page/236",
            "source_url": "https://www.example.ac.kr/page/236",
            "academic_year": 2026,
            "category_id": 4,
            "category": "기타",
        },
    }
