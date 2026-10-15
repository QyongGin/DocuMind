"""#110 generation grounding 변경의 동작 고정 테스트.

#110은 검색된 근거를 LLM이 답에 반영하도록 프롬프트와 context를 정리했다.
이 파일은 그중 지금 답 경로에 남은 동작을 LLM·DB 없이 함수 단위로 잠근다.

- 실험1b ``_format_context_block``: 구조화 근거(표 검색 정보 또는 질문 의도 추출
  정보)와 발췌가 함께 있으면 원문 전체(전체 내용)를 뺀다. 그 외에는 원문을 유지한다.

실험2(값 모양 없는 우선 근거 거르기)·실험4(우선 질의 근거 승격)는 규칙 경로와 함께 지웠다(#169, ADR-0032).

입력은 모두 합성이다.
"""

from __future__ import annotations

import pytest

import main
from main import (
    QueryAnalysis,
    _format_context_block,
)

FULL_CONTENT_LABEL = "전체 내용:"
EXCERPT_LABEL = "질문 관련 발췌:"


def _analysis(intent: str | None = None) -> QueryAnalysis:
    return QueryAnalysis(
        tokens=[],
        subject_terms=set(),
        intent=intent,
        primary_terms=set(),
        context_terms=set(),
    )


def _stub_context_parts(monkeypatch, *, excerpt: str, table_facts: list[str], evidence_facts: str) -> None:
    """발췌·표 검색 정보·질문 의도 추출 정보를 고정값으로 바꿔 분기 조건만 검사한다."""
    monkeypatch.setattr(main, "_select_relevant_excerpt", lambda doc, terms: excerpt)
    monkeypatch.setattr(main, "_get_matched_table_facts", lambda meta: list(table_facts))
    monkeypatch.setattr(main, "_extract_query_evidence_facts", lambda doc, analysis, meta=None: evidence_facts)


# --- 실험1b: 원문 전체를 빼는 조건 ---------------------------------------------

@pytest.mark.parametrize(
    ("excerpt", "table_facts", "evidence_facts", "expect_full_content"),
    [
        ("합성 발췌", ["행: 가 / 열: 금액 / 값: 10,000원"], "", False),
        ("합성 발췌", [], "신청 방법: 합성 홈페이지", False),
        ("합성 발췌", [], "", True),
        ("", ["행: 가 / 열: 금액 / 값: 10,000원"], "", True),
        ("", [], "", True),
    ],
    ids=[
        "발췌+표정보-원문제외",
        "발췌+의도추출-원문제외",
        "발췌만-원문유지",
        "발췌없음+표정보-원문유지",
        "아무것도없음-원문유지",
    ],
)
def test_format_context_block_drops_full_content_only_with_excerpt_and_structured_evidence(
    monkeypatch, excerpt, table_facts, evidence_facts, expect_full_content
):
    _stub_context_parts(monkeypatch, excerpt=excerpt, table_facts=table_facts, evidence_facts=evidence_facts)

    block = _format_context_block(1, "합성 원문 본문", {"source": "합성.pdf"}, "chunk-1", _analysis())

    assert (FULL_CONTENT_LABEL in block) is expect_full_content
    assert (EXCERPT_LABEL in block) is bool(excerpt)
