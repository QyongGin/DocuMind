"""평가용 질의 옵션(include_eval_trace) 테스트 — M1 11번 채점기.

채점기는 실패 위치(검색 실패·후보 탈락·생성 실패)를 붙이려고, 답을 만든 바로 그 실행의 단계별 후보와 프롬프트,
생성 종료 이유가 필요하다. 이 옵션은 운영 경로(Spring Boot는 보내지 않음)의 응답과 검색 결과를 바꾸면 안 된다.
데이터는 모두 합성(가나대학)이다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main

LONG_TAIL = "가나대학 생활관 안내 문장이다. " * 40  # 미리보기(360자)보다 긴 청크
DOCS = ["가나대학 전형료는 30,000원이다. 원서 접수는 9월 8일부터다. " + LONG_TAIL, "가나대학 기숙사 신청은 7월 초다."]
METAS = [
    {"document_id": "11", "ledger_id": "gana/page/1", "source": "모집요강.pdf", "chunk_index": 0},
    {"document_id": "12", "ledger_id": "gana/page/2", "source": "생활관.html", "chunk_index": 3},
]
IDS = ["11_0", "12_3"]
STAGES = ("vector", "bm25", "table_fact", "expanded", "prioritized", "reranked", "focused", "final")


@pytest.fixture
def fake_retrieval(monkeypatch):
    """임베딩·Chroma·BM25·표 사실 조회만 가짜로 바꾸고, 그 뒤 단계(펼치기·우선순위·재정렬·근거 집중·문맥)는 실제 코드를 탄다."""
    monkeypatch.setattr(main, "_embed_texts", lambda texts: ([[0.1, 0.2]], {}))
    monkeypatch.setattr(
        main,
        "_query_vector_results",
        lambda vector, limit, include_vectors=False: {
            "documents": [list(DOCS)], "metadatas": [[dict(meta) for meta in METAS]], "ids": [list(IDS)],
            "distances": [[0.1, 0.2]],
        },
    )
    monkeypatch.setattr(main, "_lookup_bm25_raw_chunks", lambda analysis, limit: ([], [], []))
    monkeypatch.setattr(main, "_lookup_lexical_table_facts", lambda question: ([], [], []))
    monkeypatch.setattr(main, "_load_source_block_texts", lambda ids: {})


def test_prepare_query_records_stages_without_changing_result(fake_retrieval):
    question = "가나대학 전형료 얼마예요?"
    plain = main._prepare_query(question, 5, None)
    stages: dict = {}
    traced = main._prepare_query(question, 5, None, stages)

    assert traced[0] == plain[0] and traced[1] == plain[1]  # 프롬프트·출처가 같다
    assert all(name in stages for name in STAGES)
    assert stages["prompt"] == plain[0] and stages["context"] and stages["context"] in plain[0]
    assert stages["vector"][0]["text"] == DOCS[0]  # 글 전체(미리보기로 자르지 않음)
    assert stages["vector"][0]["ledger_id"] == "gana/page/1"
    final = [(entry["document_id"], entry["chunk_index"]) for entry in stages["final"]]
    assert final == [(source["document_id"], source["chunk_index"]) for source in plain[1]]


class FakeLLM:
    def __init__(self, text: str = "가나대학 전형료는 30,000원입니다.", done_reason: str = "stop"):
        self.text, self.done_reason, self.calls = text, done_reason, []

    async def ainvoke(self, prompt):
        self.calls.append("ainvoke")
        return self.text

    async def agenerate(self, prompts):
        self.calls.append("agenerate")
        info = {"done_reason": self.done_reason, "eval_count": 37, "prompt_eval_count": 900, "context": [1, 2, 3]}
        return SimpleNamespace(generations=[[SimpleNamespace(text=self.text, generation_info=info)]])


def fake_prepare(priority_answer: str | None = None):
    source = {"document_id": "11", "source": "모집요강.pdf", "page": None, "chunk_index": 0, "content": "전형료 30,000원"}
    metrics = {"context_chars": 10, "prompt_chars": 20, "prepare_elapsed": 0.0, "priority_table_fact_answer": priority_answer}

    def prepare(question, top_k, system_prompt=None, eval_stages=None, retrieval_mode="rules"):
        prepare.modes.append(retrieval_mode)
        if eval_stages is not None:
            eval_stages.update(final=[{"chunk_id": "11_0", "document_id": "11", "ledger_id": "gana/page/1",
                                       "chunk_index": 0, "chunk_role": "raw", "text": "전형료 30,000원"}],
                               context="[문서 1] 전형료 30,000원", prompt="PROMPT")
        return "PROMPT", [source], metrics

    prepare.modes = []
    return prepare


def test_query_response_is_unchanged_without_eval_trace(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(main, "llm", fake)
    monkeypatch.setattr(main, "_prepare_query", fake_prepare())
    body = TestClient(main.app).post("/query", json={"question": "가나대학 전형료 얼마예요?"}).json()
    assert set(body) == {"answer", "sources"}
    assert fake.calls == ["ainvoke"]


def test_query_returns_eval_trace_with_generation_info(monkeypatch):
    fake = FakeLLM(done_reason="length")
    monkeypatch.setattr(main, "llm", fake)
    monkeypatch.setattr(main, "_prepare_query", fake_prepare())
    body = TestClient(main.app).post("/query", json={"question": "가나대학 전형료 얼마예요?",
                                                       "include_eval_trace": True}).json()
    assert body["answer"] == fake.text and body["sources"][0]["document_id"] == "11"
    trace = body["eval_trace"]
    assert trace["answer_path"] == "llm" and trace["prompt"] == "PROMPT" and trace["context"].startswith("[문서 1]")
    assert trace["stages"]["final"][0]["ledger_id"] == "gana/page/1"
    assert "context" not in trace["stages"] and "prompt" not in trace["stages"]
    assert trace["generation"] == {"done_reason": "length", "eval_count": 37, "prompt_eval_count": 900}
    assert trace["runtime"]["num_predict"] == main.OLLAMA_NUM_PREDICT and trace["runtime"]["llm_model"]
    assert fake.calls == ["agenerate"]


def test_eval_trace_marks_priority_answer_without_calling_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(main, "llm", fake)
    monkeypatch.setattr(main, "_prepare_query", fake_prepare(priority_answer="전형료는 30,000원입니다."))
    body = TestClient(main.app).post("/query", json={"question": "가나대학 전형료 얼마예요?",
                                                       "include_eval_trace": True}).json()
    assert body["eval_trace"]["answer_path"] == "priority_table_fact"
    assert body["eval_trace"]["generation"] is None
    assert fake.calls == []


# M2 실험용 검색 방식(retrieval_mode): 운영 기본값은 rules 그대로, rrf는 규칙 없이 순위 융합만 쓴다(가나대학 합성 데이터).
def test_fuse_reciprocal_rank_merges_same_chunk_and_orders_by_score():
    vector = (["벡터1", "공통"], [{"id": "v1"}, {"id": "c"}], ["v1", "c"])
    bm25 = (["공통", "키워드1"], [{"id": "c"}, {"id": "b1"}], ["c", "b1"])
    docs, metas, ids = main._fuse_reciprocal_rank([bm25, vector])
    # 공통: 1/62 + 1/61, 키워드1(bm25 2위)과 벡터1(vector 1위)은 1/62·1/61
    assert ids == ["c", "v1", "b1"]
    assert docs == ["공통", "벡터1", "키워드1"] and metas[0] == {"id": "c"}
    assert main._fuse_reciprocal_rank([([], [], [])]) == ([], [], [])


def test_prepare_query_rrf_mode_skips_rule_stages(fake_retrieval, monkeypatch):
    called = []
    for name in ("_prioritize_query_results", "_rerank_by_query_analysis", "_focus_candidates_with_query_evidence",
                 "_priority_table_fact_evidence_for_prompt", "_priority_query_evidence_for_prompt"):
        original = getattr(main, name)
        monkeypatch.setattr(main, name, lambda *args, _name=name, _original=original, **kwargs: (
            called.append(_name), _original(*args, **kwargs))[1])
    # 키워드 검색이 기숙사 청크(벡터 2위)를 1위로 찾으면 순위 융합에서 그 청크가 맨 앞에 온다
    monkeypatch.setattr(main, "_lookup_bm25_raw_chunks",
                        lambda analysis, limit: ([DOCS[1]], [dict(METAS[1])], [IDS[1]]))
    stages: dict = {}
    prompt, sources, metrics = main._prepare_query("가나대학 기숙사 신청 언제예요?", 5, None, stages, "rrf")
    assert called == []
    assert [entry["chunk_id"] for entry in stages["final"]] == ["12_3", "11_0"]
    assert stages["focused"] == stages["expanded"]
    assert metrics["priority_table_fact_answer"] is None and metrics["priority_query_evidence_answer"] is None
    assert prompt and sources[0]["document_id"] == "12"
    called.clear()
    main._prepare_query("가나대학 기숙사 신청 언제예요?", 5, None, None)
    assert "_prioritize_query_results" in called  # 기본값(rules)은 운영 경로 그대로


def test_prepare_query_rejects_unknown_retrieval_mode(fake_retrieval):
    with pytest.raises(ValueError):
        main._prepare_query("가나대학 전형료 얼마예요?", 5, None, None, "dense")


def test_query_passes_retrieval_mode_and_defaults_to_rules(monkeypatch):
    monkeypatch.setattr(main, "llm", FakeLLM())
    prepare = fake_prepare()
    monkeypatch.setattr(main, "_prepare_query", prepare)
    client = TestClient(main.app)
    client.post("/query", json={"question": "가나대학 전형료 얼마예요?"})
    client.post("/query", json={"question": "가나대학 전형료 얼마예요?", "retrieval_mode": "rrf", "include_eval_trace": True})
    assert prepare.modes == ["rules", "rrf"]
    assert client.post("/query", json={"question": "가나대학 전형료 얼마예요?", "retrieval_mode": "dense"}).status_code == 422
