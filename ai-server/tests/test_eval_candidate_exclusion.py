"""평가·학습 데이터 전용 제외 목록과 프롬프트 날짜 줄 테스트(ADR-0047·0048).

학습 예시의 근거를 질문 재료가 올라온 날의 서비스 색인 모양으로 만들려고, 그날 없던 문서를 검색 후보에서 뺀다.
빼기는 세 검색기(벡터·BM25·표 사실)가 후보를 개수로 자르기 전에 해야 빈자리를 다음 후보가 채운다.
운영 경로(Spring Boot)는 이 칸을 보내지 않으므로, 보내지 않으면 검색기 호출과 프롬프트가 그대로여야 한다.
데이터는 모두 합성(가나대학)이다.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main

Exclusion = main.CandidateExclusion


def test_exclusion_of_empty_request_is_none():
    assert Exclusion.of([], []) is None
    assert Exclusion.of(["  "], None) is None
    assert Exclusion.of(["gana/bbs/1"], []).ledger_ids == frozenset({"gana/bbs/1"})


def test_exclusion_matches_ledger_chunk_and_parent_chunks():
    exclusion = Exclusion.of(["gana/bbs/2025"], ["31_2"])
    assert exclusion.excludes({"ledger_id": "gana/bbs/2025"}, "40_0")  # 그 문서의 어느 청크든
    assert exclusion.excludes({}, "31_2")  # 원문 청크
    assert exclusion.excludes({"chunk_role": "table_fact", "parent_chunk_id": "31_2"}, "31_2_fact_0")  # 그 청크의 표 사실
    assert exclusion.excludes({"source_parent_chunk_id": "31_2"}, "31_2_r1")  # 그 청크의 검색용 청크
    assert exclusion.excludes({"document_id": "31", "chunk_index": 2}, "31_2_r9")  # 부모 id를 문서·청크 번호로 복원
    assert not exclusion.excludes({"ledger_id": "gana/bbs/2026", "document_id": "31", "chunk_index": 3}, "31_3")


def records(*entries):
    return [SimpleNamespace(chunk_id=chunk_id, document=f"{chunk_id} 가나대학 장학금 신청 기간", metadata=meta, score=score)
            for chunk_id, meta, score in entries]


BM25_RECORDS = records(
    ("10_0", {"ledger_id": "gana/bbs/2026"}, 9.0),  # 그날 뒤에 올라온 판
    ("11_0", {"ledger_id": "gana/bbs/2025"}, 8.0),
    ("12_0", {"ledger_id": "gana/page/1"}, 7.0),
)


@pytest.fixture
def fake_bm25(monkeypatch):
    index = SimpleNamespace(records=BM25_RECORDS, postings={"장학금": {0, 1, 2}})
    monkeypatch.setattr(main, "_get_bm25_sparse_index", lambda: index)
    monkeypatch.setattr(main, "_score_bm25_record", lambda tokens, record, sparse_index: record.score)
    return SimpleNamespace(tokens=["장학금"], intent=None, subject_terms=set())


def test_bm25_excludes_before_cutting_to_limit(fake_bm25):
    plain = main._lookup_bm25_raw_chunk_candidates(fake_bm25, limit=2)
    assert [candidate["chunk_id"] for candidate in plain] == ["10_0", "11_0"]
    excluded = main._lookup_bm25_raw_chunk_candidates(fake_bm25, limit=2, exclusion=Exclusion.of(["gana/bbs/2026"], []))
    # 뺀 자리를 다음 후보가 채운다(자른 뒤에 빼면 1개만 남는다)
    assert [candidate["chunk_id"] for candidate in excluded] == ["11_0", "12_0"]


TABLE_FACTS = records(
    ("31_2_fact_0", {"chunk_role": "table_fact", "parent_chunk_id": "31_2", "ledger_id": "gana/bbs/2025"}, 5),
    ("32_0_fact_0", {"chunk_role": "table_fact", "parent_chunk_id": "32_0", "ledger_id": "gana/bbs/2024"}, 4),
)


def test_table_facts_exclude_facts_of_excluded_chunk(monkeypatch):
    monkeypatch.setattr(main, "_extract_lexical_query_terms", lambda question: ({"장학금"}, {"기간"}))
    monkeypatch.setattr(main, "_get_table_fact_cache", lambda: TABLE_FACTS)
    monkeypatch.setattr(main, "_score_prepared_table_fact", lambda fact, *args: fact.score)
    plain = main._lookup_lexical_table_fact_candidates("가나대학 장학금 신청 기간", limit=1)
    assert [candidate["chunk_id"] for candidate in plain] == ["31_2_fact_0"]
    excluded = main._lookup_lexical_table_fact_candidates("가나대학 장학금 신청 기간", limit=1,
                                                         exclusion=Exclusion.of([], ["31_2"]))
    assert [candidate["chunk_id"] for candidate in excluded] == ["32_0_fact_0"]


RANKED = [(f"5{number}_0", {"ledger_id": f"gana/bbs/{number}", "document_id": f"5{number}", "chunk_index": 0})
          for number in range(6)]


@pytest.fixture
def fake_chroma(monkeypatch):
    calls = []

    def query(chroma_collection, question_vector, n_results, include_vectors):
        calls.append(n_results)
        top = RANKED[:n_results]
        return {"documents": [[f"{chunk_id} 글" for chunk_id, _ in top]], "metadatas": [[dict(meta) for _, meta in top]],
                "ids": [[chunk_id for chunk_id, _ in top]], "distances": [[0.1 * rank for rank in range(len(top))]]}

    monkeypatch.setattr(main, "QUERY_RETRIEVAL_CHUNKS_ENABLED", False)
    monkeypatch.setattr(main, "_query_chroma_vectors", query)
    return calls


def test_vector_search_without_exclusion_is_unchanged(fake_chroma):
    result = main._query_vector_results([0.1], 3, include_vectors=False)
    assert fake_chroma == [3]  # 운영과 같은 개수로 한 번만 부른다
    assert result["ids"][0] == ["50_0", "51_0", "52_0"]


def test_vector_search_overfetches_and_keeps_order(fake_chroma):
    exclusion = Exclusion.of(["gana/bbs/0", "gana/bbs/1"], ["53_0"])
    result = main._query_vector_results([0.1], 3, include_vectors=False, exclusion=exclusion)
    assert result["ids"][0] == ["52_0", "54_0", "55_0"]  # 뺀 셋을 건너뛰고 순서대로 셋을 채운다
    assert result["distances"][0] == pytest.approx([0.2, 0.4, 0.5])
    assert fake_chroma[0] > 3  # 늘려 받았다


def test_vector_search_stops_when_results_run_out(fake_chroma):
    exclusion = Exclusion.of([f"gana/bbs/{number}" for number in range(5)], [])
    result = main._query_vector_results([0.1], 3, include_vectors=False, exclusion=exclusion)
    assert result["ids"][0] == ["55_0"]  # 더 받을 것이 없으면 남은 만큼만


def test_date_lines_are_off_by_default():
    assert main.PROMPT_DATE_LINES_ENABLED is False
    assert main._prompt_today(date(2025, 8, 13)) is None
    assert main._format_posted_label({"posted_at": "2025-08-13"}) == ""
    assert not main._build_rag_prompt(None, "근거", "질문").startswith("오늘:")


def test_date_lines_when_enabled(monkeypatch):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    assert main._prompt_today(date(2025, 8, 13)) == date(2025, 8, 13)  # 평가 요청의 날짜
    assert isinstance(main._prompt_today(), date)  # 없으면 한국 시간 오늘
    prompt = main._build_rag_prompt(None, "근거", "질문", today=date(2025, 8, 13))
    assert prompt.startswith("오늘: 2025-08-13\n")
    analysis = main._analyze_query("가나대학 장학금 신청 기간")
    block = main._format_context_block(1, "가나대학 장학금 신청 기간은 9월 10일까지다.",
                                       {"source": "장학 공지.html", "posted_at": "2025-08-13T09:00:00"}, "70_0", analysis)
    assert block.splitlines()[:3] == ["[출처 1]", "문서: 장학 공지.html", "게시: 2025-08-13"]
    no_date = main._format_context_block(1, "가나대학 학과 안내.", {"source": "학과.html"}, "71_0", analysis)
    assert "게시:" not in no_date  # 게시일이 없는 문서(페이지·규정)는 줄이 없다


class FakeLLM:
    async def ainvoke(self, prompt):
        return "가나대학 장학금 신청은 9월 10일까지입니다."

    async def agenerate(self, prompts):
        info = {"done_reason": "stop", "eval_count": 10, "prompt_eval_count": 100}
        return SimpleNamespace(generations=[[SimpleNamespace(text="답", generation_info=info)]])


@pytest.fixture
def captured_prepare(monkeypatch):
    calls = []

    def prepare(question, top_k, system_prompt=None, eval_stages=None, **kwargs):
        calls.append(kwargs)
        return "프롬프트", [], {"context_chars": 1, "prompt_chars": 1, "prepare_elapsed": 0.0}

    monkeypatch.setattr(main, "_prepare_query", prepare)
    monkeypatch.setattr(main, "llm", FakeLLM())
    return calls


def test_query_without_eval_fields_calls_prepare_like_production(captured_prepare):
    response = TestClient(main.app).post("/query", json={"question": "가나대학 장학금 언제까지야?"})
    assert response.status_code == 200
    assert captured_prepare == [{}]  # 평가 전용 인자를 더하지 않는다


def test_query_passes_exclusion_and_as_of(captured_prepare):
    response = TestClient(main.app).post("/query", json={
        "question": "가나대학 장학금 언제까지야?", "include_eval_trace": True,
        "exclude_ledger_ids": ["gana/bbs/2026"], "exclude_chunk_ids": ["31_2"], "as_of": "2025-08-13"})
    assert response.status_code == 200
    kwargs = captured_prepare[0]
    assert kwargs["exclusion"] == Exclusion(frozenset({"gana/bbs/2026"}), frozenset({"31_2"}))
    assert kwargs["as_of"] == date(2025, 8, 13)
    assert response.json()["eval_trace"]["runtime"]["prompt_date_lines"] is False
