"""#110 generation grounding 변경의 동작 고정 테스트.

#110은 검색된 근거를 LLM이 답에 반영하도록 프롬프트와 context를 정리했다.
이 파일은 그중 지금 답 경로에 남은 동작을 LLM·DB 없이 함수 단위로 잠근다.

- ``_format_context_block``: 원문 전체(전체 내용)를 늘 넣는다. 발췌·표 검색 정보·질문 의도 추출
  정보는 있으면 원문 앞에 함께 둔다. #110 실험1b의 '구조화 근거와 발췌가 있으면 원문을 뺀다'는
  M2 4단계에서 껐다(발췌가 떨어진 줄의 답을 지움).

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


# --- 원문 전체는 늘 들어간다 ----------------------------------------------------

@pytest.mark.parametrize(
    ("excerpt", "table_facts", "evidence_facts"),
    [
        ("합성 발췌", ["행: 가 / 열: 금액 / 값: 10,000원"], ""),
        ("합성 발췌", [], "신청 방법: 합성 홈페이지"),
        ("합성 발췌", ["행: 가 / 열: 금액 / 값: 10,000원"], "신청 방법: 합성 홈페이지"),
        ("합성 발췌", [], ""),
        ("", ["행: 가 / 열: 금액 / 값: 10,000원"], ""),
        ("", [], ""),
    ],
    ids=[
        "발췌+표정보",
        "발췌+의도추출",
        "발췌+표정보+의도추출",
        "발췌만",
        "발췌없음+표정보",
        "아무것도없음",
    ],
)
def test_format_context_block_always_keeps_full_content(monkeypatch, excerpt, table_facts, evidence_facts):
    _stub_context_parts(monkeypatch, excerpt=excerpt, table_facts=table_facts, evidence_facts=evidence_facts)

    block = _format_context_block(1, "합성 원문 본문", {"source": "합성.pdf"}, "chunk-1", _analysis())

    assert FULL_CONTENT_LABEL in block
    assert block.rstrip().endswith("합성 원문 본문")
    assert (EXCERPT_LABEL in block) is bool(excerpt)
    assert ("표 검색 정보:" in block) is bool(table_facts)
    assert ("질문 의도 추출 정보:" in block) is bool(evidence_facts)


def test_format_context_block_keeps_answer_line_far_from_query_terms(monkeypatch):
    # 가나대학 장학금 청크: 발췌는 질문 낱말 근처 1~3줄만 고르지만, 떨어진 5줄의 접수 기간도 프롬프트에 남아야 한다
    doc = "\n".join([
        "성적우수장학금",
        "대상: 직전 학기 평점 3.5 이상",
        "금액: 등록금의 50%",
        "제출 서류: 신청서, 성적증명서",
        "접수: 3월 2일 ~ 3월 13일, 가나대학 학생지원팀",
    ])
    _stub_context_parts(
        monkeypatch,
        excerpt="성적우수장학금\n대상: 직전 학기 평점 3.5 이상\n금액: 등록금의 50%",
        table_facts=[],
        evidence_facts="장학금 대상: 직전 학기 평점 3.5 이상",
    )

    block = _format_context_block(1, doc, {"source": "가나대학-장학금-안내.pdf"}, "chunk-1", _analysis())

    assert "접수: 3월 2일 ~ 3월 13일, 가나대학 학생지원팀" in block
