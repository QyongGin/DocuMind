"""표 사실 조회 캐시 테스트.

예전에는 표 질문마다 ``collection.get(where={"chunk_role": "table_fact"})``로 표 사실 전체를 한 번에
가져와 채점했다. 서비스 전체 색인(표 사실 45,878개)에서는 Chroma 내부 SQLite가 "too many SQL
variables"로 거부해 표 근거가 소리 없이 빠졌다. 지금은 표 사실을 나눠 가져와 메모리에 한 번 두고
(문서를 올리거나 지우면 다시 만듦) 질문마다 메모리에서 채점한다. 채점 규칙은 그대로다.

입력은 모두 합성이다.
"""

from __future__ import annotations

import re

import pytest
from langchain_core.documents import Document

import main

FACTS = [
    "합성공학과 | 등록금 = 3,000,000원",
    "합성공학과 | 모집정원 = 40 | 경쟁률 = 3.2",
    "합성공학과 | 합계 = 40명",
    "다른학과 | 등록금 = 2,500,000원",
    "합성 공학과 | 실습실 = 8호관 101호",
    "합성공학과 입시 결과 | 평균 = 4.1등급",
    "기숙사비 = 1,200,000원",
]
QUESTIONS = [
    "합성공학과 등록금은 얼마인가요?",
    "합성공학과 모집 인원은 몇 명인가요?",
    "합성 공학과 실습실 위치는 어디인가요?",
]


def _previous_score(fact: str, question: str, allow_cost_subject_fallback: bool = False) -> int:
    """고치기 전 채점 함수를 그대로 옮긴 비교 기준."""
    fact_lower = fact.lower()
    subject_terms, intent_terms = main._extract_lexical_query_terms(question)
    asks_cost_value = bool(intent_terms & main.INTENT_QUERY_TERMS["cost"])
    has_money_value = bool(main.MONEY_VALUE_PATTERN.search(fact))
    subject_matches = any(main._term_in_text(term, fact) for term in subject_terms)
    if subject_terms and not subject_matches:
        if not (allow_cost_subject_fallback and asks_cost_value and has_money_value):
            return 0
    score = 0
    score += sum(12 for term in subject_terms if main._term_in_text(term, fact))
    score += sum(4 for term in intent_terms if main._term_in_text(term, fact))
    if asks_cost_value and has_money_value:
        score += 24
    asks_count_value = bool(intent_terms & {"모집", "인원", "정원", "모집인원", "모집정원"})
    has_primary_count_column = bool(re.search(r"(모집\s*정원|모집정원|합계|총|전체|total)\s*=", fact_lower))
    if asks_count_value and has_primary_count_column:
        score += 20
    if asks_count_value and any(term in fact_lower for term in main.TABLE_STATISTIC_TERMS):
        score -= 10
    return max(score, 0)


class _FakeChroma:
    """한 번에 max_rows보다 많이 달라고 하면 실제 Chroma처럼 실패하는 가짜 collection."""

    def __init__(self, facts: list[str], max_rows: int = 1000):
        self.rows = [
            (f"fact-{index}", text, {"chunk_role": "table_fact", "document_id": "9", "row": index})
            for index, text in enumerate(facts)
        ]
        self.max_rows = max_rows
        self.calls: list[dict] = []

    def get(self, where=None, include=None, limit=None, offset=0, ids=None):
        self.calls.append({"where": where, "limit": limit, "offset": offset})
        key, value = next(iter((where or {}).items()))
        matched = [row for row in self.rows if row[2].get(key) == value]
        page = matched[offset:] if limit is None else matched[offset:offset + limit]
        if len(page) > self.max_rows:
            raise RuntimeError("too many SQL variables")
        return {
            "ids": [row[0] for row in page],
            "documents": [row[1] for row in page],
            "metadatas": [dict(row[2]) for row in page],
        }

    def delete(self, ids):
        self.rows = [row for row in self.rows if row[0] not in set(ids)]

    def add(self, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _fresh_cache():
    main._invalidate_table_fact_cache()
    yield
    main._invalidate_table_fact_cache()


def test_prepared_scoring_matches_previous_scoring():
    for question in QUESTIONS:
        for fact in FACTS:
            for fallback in (False, True):
                assert main._score_table_fact_for_question(fact, question, fallback) == _previous_score(fact, question, fallback)


def test_paged_get_reads_everything_without_large_requests(monkeypatch):
    monkeypatch.setattr(main, "CHROMA_GET_PAGE_SIZE", 3)
    fake = _FakeChroma(FACTS * 2, max_rows=3)

    got = main._get_collection_entries_paged(fake, where={"chunk_role": "table_fact"}, include=["documents", "metadatas"])

    assert got["ids"] == [f"fact-{index}" for index in range(len(FACTS) * 2)]
    assert all(call["limit"] == 3 for call in fake.calls)


def test_paged_get_stops_at_max_entries(monkeypatch):
    monkeypatch.setattr(main, "CHROMA_GET_PAGE_SIZE", 3)
    fake = _FakeChroma(FACTS * 2, max_rows=3)

    got = main._get_collection_entries_paged(fake, where={"chunk_role": "table_fact"}, include=[], max_entries=5)

    assert len(got["ids"]) == 5


def test_lookup_reads_chroma_once_and_reuses_cache(monkeypatch):
    monkeypatch.setattr(main, "CHROMA_GET_PAGE_SIZE", 3)
    fake = _FakeChroma(FACTS, max_rows=3)
    monkeypatch.setattr(main, "collection", fake)

    first = main._lookup_lexical_table_fact_candidates(QUESTIONS[0])
    calls_after_first = len(fake.calls)
    second = main._lookup_lexical_table_fact_candidates(QUESTIONS[1])

    assert first and second
    assert calls_after_first > 0
    assert len(fake.calls) == calls_after_first


def test_lookup_ranks_like_previous_scoring(monkeypatch):
    monkeypatch.setattr(main, "collection", _FakeChroma(FACTS))

    for question in QUESTIONS:
        got = main._lookup_lexical_table_fact_candidates(question, limit=3)
        scored = [(_previous_score(fact, question), f"fact-{index}") for index, fact in enumerate(FACTS)]
        expected = sorted([item for item in scored if item[0] > 0], key=lambda item: item[0], reverse=True)[:3]
        assert [(candidate["table_fact_score"], candidate["chunk_id"]) for candidate in got] == expected


def test_returned_metadata_does_not_change_cache(monkeypatch):
    monkeypatch.setattr(main, "collection", _FakeChroma(FACTS))

    got = main._lookup_lexical_table_fact_candidates(QUESTIONS[0])
    got[0]["metadata"]["changed_by_caller"] = True
    again = main._lookup_lexical_table_fact_candidates(QUESTIONS[0])

    assert "changed_by_caller" not in again[0]["metadata"]


def test_failed_cache_build_returns_nothing_and_is_retried(monkeypatch):
    monkeypatch.setattr(main, "collection", _FakeChroma(FACTS, max_rows=0))
    assert main._lookup_lexical_table_fact_candidates(QUESTIONS[0]) == []

    monkeypatch.setattr(main, "collection", _FakeChroma(FACTS))
    assert main._lookup_lexical_table_fact_candidates(QUESTIONS[0])


def test_upload_invalidates_table_fact_cache(monkeypatch):
    monkeypatch.setattr(main, "collection", _FakeChroma(FACTS))
    monkeypatch.setattr(main, "source_block_collection", _FakeChroma([]))
    monkeypatch.setattr(main, "retrieval_chunk_collection", _FakeChroma([]))
    monkeypatch.setattr(main, "_embed_texts", lambda texts: ([[0.0, 1.0] for _ in texts], {}))
    main._get_table_fact_cache()
    docs = [Document(page_content="학사 안내\n\n| 구분 | 금액 |\n| --- | --- |\n| 수업료 | 100 |", metadata={})]

    main._store_document_chunks(docs, "합성.html", 777, [], None, None)

    assert main._table_fact_cache is None


def test_delete_invalidates_table_fact_cache(monkeypatch):
    monkeypatch.setattr(main, "collection", _FakeChroma(FACTS))
    monkeypatch.setattr(main, "source_block_collection", _FakeChroma([]))
    monkeypatch.setattr(main, "retrieval_chunk_collection", _FakeChroma([]))
    main._get_table_fact_cache()

    main._delete_document_chroma_entries(9)

    assert main._table_fact_cache is None
