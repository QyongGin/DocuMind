"""지정 청크 조립과 후보별 단계 순위 기록(#275) 테스트. 데이터는 모두 합성(가나대학)이다.

학습 데이터는 정답 청크를 근거의 정한 자리에 넣은 프롬프트를 서버에서 그대로 받는다. 정답 청크가 근거에 못 든 예시는
검색기별 순위, 순위 융합 뒤 순위, 재순위 뒤 순위, 근거 블록 번호로 어디서 밀렸는지 센다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main

DOCS = ["가나대학 전형료는 30,000원이다.", "가나대학 기숙사 신청은 7월 초다.", "가나대학 도서관은 9시에 연다."]
METAS = [
    {"document_id": "11", "ledger_id": "gana/page/1", "source": "모집요강.pdf", "chunk_index": 0},
    {"document_id": "12", "ledger_id": "gana/page/2", "source": "생활관.html", "chunk_index": 3},
    {"document_id": "13", "ledger_id": "gana/page/3", "source": "도서관.html", "chunk_index": 1},
]
IDS = ["11_0", "12_3", "13_1"]
# 색인에만 있는 청크(검색 후보가 아님): 지정하면 색인에서 꺼낸다
INDEX_ONLY = {"14_2": ("가나대학 장학금 신청은 3월 2일부터다.",
                       {"document_id": "14", "ledger_id": "gana/page/4", "source": "장학.html", "chunk_index": 2})}


@pytest.fixture
def fake_retrieval(monkeypatch):
    """임베딩·Chroma·BM25·표 사실 조회만 가짜로 바꾸고, 그 뒤 단계(순위 융합·지정 청크·문맥)는 실제 코드를 탄다."""
    monkeypatch.setattr(main, "_embed_query", lambda question: ([[0.1, 0.2]], {}))

    def vector(question_vector, limit, include_vectors=False, exclusion=None):
        kept = [(d, m, i) for d, m, i in zip(DOCS, METAS, IDS) if not (exclusion and exclusion.excludes(m, i))]
        return {"documents": [[d for d, _, _ in kept]], "metadatas": [[dict(m) for _, m, _ in kept]],
                "ids": [[i for _, _, i in kept]], "distances": [[0.1 * (n + 1) for n in range(len(kept))]]}

    monkeypatch.setattr(main, "_query_vector_results", vector)
    monkeypatch.setattr(main, "_lookup_bm25_raw_chunk_candidates", lambda analysis, limit=5, exclusion=None: [
        {"rank": 1, "bm25_score": 2.5, "chunk_id": IDS[2], "document": DOCS[2], "metadata": dict(METAS[2])}])
    monkeypatch.setattr(main, "_lookup_lexical_table_fact_candidates", lambda question, limit=5, exclusion=None: [])
    monkeypatch.setattr(main, "_load_source_block_texts", lambda ids: {})
    monkeypatch.setattr(main, "_load_parent_chunk",
                        lambda chunk_id: (INDEX_ONLY[chunk_id][0], dict(INDEX_ONLY[chunk_id][1]))
                        if chunk_id in INDEX_ONLY else (None, None))


def pin(chunk_id: str, rank: int) -> main.PinnedChunk:
    return main.PinnedChunk(chunk_id=chunk_id, rank=rank)


def blocks(prompt: str) -> list[str]:
    """프롬프트의 [출처 N] 블록 첫 줄 아래 문서 이름(블록 순서 확인용)."""
    return [part.split("\n", 2)[1] for part in prompt.split("[출처 ")[1:]]


def test_fused_order_without_pins(fake_retrieval):
    # 기준: 13_1은 BM25 1위·벡터 3위라 순위 융합에서 맨 앞, 나머지는 벡터 순서
    stages: dict = {}
    main._prepare_query("가나대학 안내", 3, None, stages)
    assert [entry["chunk_id"] for entry in stages["final"]] == ["13_1", "11_0", "12_3"]
    assert "pinned" not in stages


def test_pinned_candidate_moves_to_the_rank_and_others_keep_order(fake_retrieval):
    stages: dict = {}
    plain = main._prepare_query("가나대학 안내", 3, None)
    prompt, sources, _ = main._prepare_query("가나대학 안내", 3, None, stages, pins=[pin("12_3", 1)])
    assert [entry["chunk_id"] for entry in stages["final"]] == ["12_3", "13_1", "11_0"]
    assert sources[0]["document_id"] == "12" and prompt != plain[0]
    assert stages["pinned"] == [{"chunk_id": "12_3", "rank": 1, "candidate_rank": 3, "from": "candidates", "block": 1}]
    assert blocks(prompt)[0] == "문서: 생활관.html"


def test_pinned_chunk_outside_candidates_comes_from_index_and_pushes_the_last_out(fake_retrieval):
    stages: dict = {}
    prompt, _, _ = main._prepare_query("가나대학 장학금", 3, None, stages, pins=[pin("14_2", 2)])
    assert [entry["chunk_id"] for entry in stages["final"]] == ["13_1", "14_2", "11_0"]
    assert stages["pinned"][0] == {"chunk_id": "14_2", "rank": 2, "candidate_rank": None, "from": "index", "block": 2}
    assert "가나대학 장학금 신청은 3월 2일부터다." in prompt
    ranks = {entry["chunk_id"]: entry for entry in stages["retrieval"]}
    # 밀려난 12_3: 벡터 2위, 순위 융합 3위였지만 지정 청크가 들어와 4위가 되어 근거 3개 밖
    assert ranks["12_3"]["vector_rank"] == 2 and ranks["12_3"]["fused_rank"] == 3
    assert ranks["12_3"]["final_rank"] == 4 and ranks["12_3"]["block"] is None
    # 지정 청크는 검색기가 찾지 않았다
    assert ranks["14_2"]["retrieval_methods"] == [] and ranks["14_2"]["fused_rank"] is None
    assert (ranks["14_2"]["final_rank"], ranks["14_2"]["block"]) == (2, 2)


def test_two_pins_each_take_their_rank(fake_retrieval):
    stages: dict = {}
    main._prepare_query("가나대학 안내", 3, None, stages, pins=[pin("11_0", 3), pin("14_2", 1)])
    assert [entry["chunk_id"] for entry in stages["final"]] == ["14_2", "13_1", "11_0"]


def test_retrieval_ranks_record_every_stage(fake_retrieval):
    stages: dict = {}
    main._prepare_query("가나대학 안내", 2, None, stages)
    ranks = {entry["chunk_id"]: entry for entry in stages["retrieval"]}
    assert set(ranks) == set(IDS)
    first = ranks["13_1"]
    assert first["retrieval_methods"] == ["vector", "bm25"] and (first["vector_rank"], first["bm25_rank"]) == (3, 1)
    assert (first["fused_rank"], first["rerank_rank"], first["final_rank"], first["block"]) == (1, None, 1, 1)
    assert ranks["12_3"]["block"] is None  # top_k 2라 셋째는 근거 밖
    assert "table_fact_preview" not in first and "text" not in first  # 순위와 점수만


def test_retrieval_ranks_have_rerank_rank_when_rerank_is_used(fake_retrieval, monkeypatch):
    monkeypatch.setattr(main, "RERANKER_URL", "http://reranker.test")
    monkeypatch.setattr(main, "RERANK_CANDIDATES", 3)
    scores = [0.1, 0.2, 0.9]  # 순위 융합 13_1, 11_0, 12_3 → 재순위 12_3, 11_0, 13_1
    monkeypatch.setattr(main.httpx, "post", lambda url, json=None, timeout=None: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: [{"index": i, "score": s} for i, s in enumerate(scores)]))
    stages: dict = {}
    main._prepare_query("가나대학 안내", 2, None, stages)
    ranks = {entry["chunk_id"]: entry for entry in stages["retrieval"]}
    assert (ranks["13_1"]["fused_rank"], ranks["13_1"]["rerank_rank"], ranks["13_1"]["block"]) == (1, 3, None)
    assert (ranks["12_3"]["fused_rank"], ranks["12_3"]["rerank_rank"], ranks["12_3"]["block"]) == (3, 1, 1)


def test_pins_work_with_table_blocks_on(fake_retrieval, monkeypatch):
    # 표 블록을 켜도(표 번호 없는 청크는 표가 아닌 블록) 지정 자리가 근거 블록 번호가 된다
    monkeypatch.setattr(main, "TABLE_BLOCK_ENABLED", True)
    stages: dict = {}
    prompt, _, _ = main._prepare_query("가나대학 장학금", 3, None, stages, pins=[pin("14_2", 3)])
    assert stages["pinned"][0]["block"] == 3 and blocks(prompt)[2] == "문서: 장학.html"
    assert {entry["chunk_id"]: entry["block"] for entry in stages["retrieval"]}["12_3"] is None


def test_pinned_chunk_excluded_or_missing_is_rejected(fake_retrieval):
    exclusion = main.CandidateExclusion.of(["gana/page/4"], [])
    with pytest.raises(main.HTTPException) as excluded:
        main._prepare_query("가나대학 장학금", 3, None, {}, exclusion=exclusion, pins=[pin("14_2", 1)])
    assert excluded.value.status_code == 400
    with pytest.raises(main.HTTPException) as missing:
        main._prepare_query("가나대학 장학금", 3, None, {}, pins=[pin("99_9", 1)])
    assert missing.value.status_code == 400


class FakeLLM:
    async def ainvoke(self, prompt):
        return "가나대학 장학금 신청은 3월 2일부터입니다."

    async def agenerate(self, prompts):
        info = {"done_reason": "stop", "eval_count": 9, "prompt_eval_count": 300}
        return SimpleNamespace(generations=[[SimpleNamespace(text="가나대학 장학금 신청은 3월 2일부터입니다.",
                                                              generation_info=info)]])


def test_query_returns_pins_ranks_and_template_version(fake_retrieval, monkeypatch):
    monkeypatch.setattr(main, "llm", FakeLLM())
    body = TestClient(main.app).post("/query", json={
        "question": "가나대학 장학금", "top_k": 3, "include_eval_trace": True,
        "pinned_chunks": [{"chunk_id": "14_2", "rank": 2}]}).json()
    trace = body["eval_trace"]
    assert trace["pinned"][0]["block"] == 2 and "pinned" not in trace["stages"] and "retrieval" not in trace["stages"]
    assert {entry["chunk_id"] for entry in trace["retrieval"]} == {*IDS, "14_2"}
    assert trace["runtime"]["prompt_template_version"] == main.PROMPT_TEMPLATE_VERSION
    assert trace["runtime"]["default_top_k"] == main.DEFAULT_TOP_K
    assert trace["runtime"]["num_ctx"] == main.OLLAMA_NUM_CTX and trace["runtime"]["num_predict"] == main.OLLAMA_NUM_PREDICT


@pytest.mark.parametrize("request_body", [
    {"pinned_chunks": [{"chunk_id": "14_2", "rank": 4}], "include_eval_trace": True},  # 자리가 top_k(3) 밖
    {"pinned_chunks": [{"chunk_id": "14_2", "rank": 1}]},  # 평가용 기록 없이
    {"pinned_chunks": [{"chunk_id": "14_2", "rank": 1}, {"chunk_id": "11_0", "rank": 1}], "include_eval_trace": True},
    {"pinned_chunks": [{"chunk_id": "14_2", "rank": 1}, {"chunk_id": "14_2", "rank": 2}], "include_eval_trace": True},
    {"pinned_chunks": [{"chunk_id": "99_9", "rank": 1}], "include_eval_trace": True},  # 색인에 없는 청크
])
def test_query_rejects_bad_pins(fake_retrieval, monkeypatch, request_body):
    monkeypatch.setattr(main, "llm", FakeLLM())
    response = TestClient(main.app).post("/query", json={"question": "가나대학 장학금", "top_k": 3, **request_body})
    assert response.status_code == 400


def test_query_without_pins_calls_prepare_without_pin_argument(monkeypatch):
    # 운영 경로(지정 청크 없음)는 _prepare_query를 전과 같은 인자로 부른다
    seen = {}

    def prepare(question, top_k, system_prompt=None, eval_stages=None, **eval_only):
        seen.update(eval_only)
        return None, [], {}

    monkeypatch.setattr(main, "_prepare_query", prepare)
    TestClient(main.app).post("/query", json={"question": "가나대학 장학금"})
    assert seen == {}


def test_rag_trace_returns_runtime_settings(fake_retrieval):
    # 학습 데이터 도구가 생성 없이 근거 수와 입력 틀 판 번호를 읽는다(지정 청크의 자리를 근거 수 안에서 고르려고)
    body = TestClient(main.app).post("/debug/rag-trace", json={"question": "가나대학 안내"}).json()
    assert body["runtime"]["default_top_k"] == main.DEFAULT_TOP_K
    assert body["runtime"]["prompt_template_version"] == main.PROMPT_TEMPLATE_VERSION
    assert body["answer_generated"] is False
