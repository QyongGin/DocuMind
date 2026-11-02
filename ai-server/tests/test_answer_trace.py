"""처리 기록(include_trace) 테스트 — ADR-0052.

백엔드는 답마다 처리 기록(프롬프트, 단계별 걸린 초, 근거 후보별 검색 점수, 모델 설정)을 저장해 관리자 개발자 모드에서
보인다. 요청한 때만 붙고, 붙여도 답·출처·프롬프트는 같아야 한다. 데이터는 모두 합성(가나대학)이다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import main

DOCS = ["가나대학 전형료는 30,000원이다. 원서 접수는 9월 8일부터다.", "가나대학 기숙사 신청은 7월 초다."]
METAS = [
    {"document_id": "11", "ledger_id": "gana/page/1", "source": "모집요강.pdf", "chunk_index": 0},
    {"document_id": "12", "ledger_id": "gana/page/2", "source": "생활관.html", "chunk_index": 3},
]
IDS = ["11_0", "12_3"]
QUESTION = "가나대학 전형료 얼마예요?"


@pytest.fixture
def retrieval(monkeypatch):
    """검색기 셋을 가짜로 바꾼다: 벡터는 두 청크, BM25는 기숙사 청크, 표 사실은 전형료 청크(11_0)의 표 한 칸을 찾는다."""
    monkeypatch.setattr(main, "_embed_query", lambda question: ([[0.1, 0.2]], {}))
    monkeypatch.setattr(main, "_query_vector_results", lambda vector, limit, include_vectors=False: {
        "documents": [list(DOCS)], "metadatas": [[dict(meta) for meta in METAS]], "ids": [list(IDS)],
        "distances": [[0.31, 0.42]]})
    monkeypatch.setattr(main, "_lookup_bm25_raw_chunk_candidates", lambda analysis, limit=5: [
        {"rank": 1, "bm25_score": 3.2, "chunk_id": IDS[1], "document": DOCS[1], "metadata": dict(METAS[1])}])
    fact_meta = {"document_id": "11", "ledger_id": "gana/page/1", "chunk_role": "table_fact", "parent_chunk_id": "11_0"}
    monkeypatch.setattr(main, "_lookup_lexical_table_fact_candidates", lambda question, limit=5: [
        {"rank": 1, "table_fact_score": 7, "chunk_id": "11_0_fact_2", "document": "전형료: 일반전형 30,000원",
         "metadata": fact_meta}])
    monkeypatch.setattr(main, "_load_parent_chunk",
                        lambda parent_id: (DOCS[0], dict(METAS[0])) if parent_id == "11_0" else (None, None))
    monkeypatch.setattr(main, "_load_source_block_texts", lambda ids: {})


@pytest.fixture
def no_documents(monkeypatch):
    monkeypatch.setattr(main, "_embed_query", lambda question: ([[0.1, 0.2]], {}))
    monkeypatch.setattr(main, "_query_vector_results", lambda vector, limit, include_vectors=False: {
        "documents": [[]], "metadatas": [[]], "ids": [[]], "distances": [[]]})
    monkeypatch.setattr(main, "_lookup_bm25_raw_chunk_candidates", lambda analysis, limit=5: [])
    monkeypatch.setattr(main, "_lookup_lexical_table_fact_candidates", lambda question, limit=5: [])


class FakeLLM:
    def __init__(self, pieces=("가나대학 전형료는 ", "30,000원입니다.\n\n[출처 2]")):
        self.pieces, self.prompts = list(pieces), []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return "".join(self.pieces)

    async def astream(self, prompt):
        self.prompts.append(prompt)
        for piece in self.pieces:
            yield piece


def stream_events(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def test_prepare_query_lists_prompt_candidates_with_retriever_scores(retrieval):
    prompt, sources, metrics = main._prepare_query(QUESTION, 5, None)

    candidates = metrics["candidates"]
    # N번째 후보가 프롬프트의 [출처 N]이다: 출처 목록과 순서가 같다
    assert [c["rank"] for c in candidates] == [1, 2]
    assert [c["document_id"] for c in candidates] == [s["document_id"] for s in sources] == ["12", "11"]
    dorm, fee = candidates
    assert dorm["retrieval"]["retrieval_methods"] == ["vector", "bm25"]
    assert (dorm["retrieval"]["vector_distance"], dorm["retrieval"]["bm25_score"]) == (0.42, 3.2)
    # 표 사실은 부모 청크(11_0)로 펼쳐져 프롬프트에 들어가므로 점수도 부모 청크에 붙는다
    assert fee["chunk_id"] == "11_0" and fee["ledger_id"] == "gana/page/1"
    assert fee["retrieval"]["retrieval_methods"] == ["vector", "table_fact_lexical"]
    assert (fee["retrieval"]["table_fact_score"], fee["retrieval"]["table_fact_hit_chunk_id"]) == (7, "11_0_fact_2")
    assert [c["fused_rank"] for c in candidates] == [1, 2] and dorm["rerank_score"] is None
    assert metrics["rerank"] == {"enabled": False, "used": False, "candidates": 0, "error": None}
    assert "[출처 1]" in prompt and "[출처 2]" in prompt


def test_candidates_keep_fused_rank_and_rerank_score(retrieval, monkeypatch):
    # 순위 융합은 기숙사 청크(12_3)를 앞에 두지만 재순위가 전형료 청크(11_0)를 더 높게 매기면 [출처 1]이 바뀐다
    monkeypatch.setattr(main, "RERANKER_URL", "http://reranker.test")
    monkeypatch.setattr(main, "RERANK_CANDIDATES", 2)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"index": 0, "score": 0.1}, {"index": 1, "score": 0.9}]

    monkeypatch.setattr(main.httpx, "post", lambda url, json=None, timeout=None: Response())
    _, _, metrics = main._prepare_query(QUESTION, 5, None)

    assert [(c["chunk_id"], c["fused_rank"], c["rerank_score"]) for c in metrics["candidates"]] == [
        ("11_0", 2, 0.9), ("12_3", 1, 0.1)]
    assert metrics["rerank"] == {"enabled": True, "used": True, "candidates": 2, "error": None}


def test_query_returns_trace_only_when_asked(retrieval, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(main, "llm", fake)
    client = TestClient(main.app)

    plain = client.post("/query", json={"question": QUESTION}).json()
    traced = client.post("/query", json={"question": QUESTION, "include_trace": True}).json()

    assert set(plain) == {"answer", "sources"}  # 평가 실행기·옛 호출은 그대로 받는다
    assert traced["answer"] == plain["answer"] and traced["sources"] == plain["sources"]
    trace = traced["trace"]
    assert trace["prompt"] == fake.prompts[-1] == fake.prompts[0]  # 모델이 받은 그 프롬프트
    assert set(trace["seconds"]) == {"embedding", "vector_search", "lexical_search", "rerank", "context_build",
                                     "prepare", "generation", "total"}
    assert all(value is not None and value >= 0 for value in trace["seconds"].values())
    assert [c["document_id"] for c in trace["candidates"]] == [s["document_id"] for s in traced["sources"]]
    assert trace["model"]["llm_model"] == main.OLLAMA_LLM_MODEL and "reranker" not in trace["model"]


def test_stream_done_carries_trace_only_when_asked(retrieval, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(main, "llm", fake)
    client = TestClient(main.app)

    plain = stream_events(client.post("/query/stream", json={"question": QUESTION}).text)
    traced = stream_events(client.post("/query/stream", json={"question": QUESTION, "include_trace": True}).text)

    assert [event["token"] for event in traced[:-1]] == fake.pieces  # 흐르는 글은 같다
    assert set(plain[-1]) == {"done", "sources"} and traced[-1]["sources"] == plain[-1]["sources"]
    trace = traced[-1]["trace"]
    assert trace["prompt"] == fake.prompts[-1]
    assert {"first_token", "generation", "total"} <= set(trace["seconds"])
    assert trace["seconds"]["first_token"] <= trace["seconds"]["total"]
    assert [c["rank"] for c in trace["candidates"]] == [1, 2]


def test_trace_without_documents_has_no_prompt(no_documents, monkeypatch):
    monkeypatch.setattr(main, "llm", FakeLLM())
    events = stream_events(TestClient(main.app).post("/query/stream", json={"question": QUESTION,
                                                                            "include_trace": True}).text)

    assert len(events) == 1 and events[0]["answer"] == "관련 내용을 문서에서 찾을 수 없습니다."
    trace = events[0]["trace"]
    assert trace["prompt"] is None and trace["candidates"] == [] and trace["seconds"]["total"] >= 0
