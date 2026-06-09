"""Smoke checks for priority query evidence promotion."""

from __future__ import annotations

import os
import tempfile

# main.py initializes a Chroma PersistentClient at import time. Keep that import
# in a temporary cwd so root-level smoke runs do not create ./chroma_db.
_ORIGINAL_CWD = os.getcwd()
_SMOKE_WORKDIR = tempfile.TemporaryDirectory(prefix="documind-chroma-smoke-")
_SMOKE_CHROMA_HOST = os.environ.pop("CHROMA_HOST", None)
os.chdir(_SMOKE_WORKDIR.name)
try:
    from main import (
        _analyze_query,
        _build_rag_prompt,
        _priority_query_evidence_answer_disabled_reason,
        _priority_query_evidence_answer_for_request,
        _priority_query_evidence_for_prompt,
    )
finally:
    os.chdir(_ORIGINAL_CWD)
    if _SMOKE_CHROMA_HOST is not None:
        os.environ["CHROMA_HOST"] = _SMOKE_CHROMA_HOST


def main() -> None:
    """Verify query_evidence_facts can become safe priority evidence."""
    question = "항공운항과 면접 예약은 어떻게 해?"
    analysis = _analyze_query(question)

    evidence_fact = (
        "- 항공운항과 면접 신청: 면접 일자 및 시간은 예약 기간에 선착순으로 신청"
        "(입학 홈페이지에서 신청); 학과에 따라 면접 일자 선택은 하루만 가능할 수 있음; "
        "면접고사 예약을 하지 않을 경우 임의로 배정; 면접고사 일자 및 시간은 변경 불가"
    )
    numeric_dump = "- 관련 근거: |항공운항과|90|35.5|4.5|-|3|10|29.3|3.8|-|-|12|17.6|768|665|1|"

    priority_evidence = _priority_query_evidence_for_prompt(
        ["Ⅱ. 전형일정\n면접고사 안내"],
        [{"query_evidence_facts": [evidence_fact, numeric_dump]}],
        ["query-evidence-smoke_1"],
        analysis,
    )
    assert priority_evidence is not None
    assert evidence_fact in priority_evidence.evidence_text
    assert numeric_dump not in priority_evidence.evidence_text
    assert priority_evidence.chunk_id == "query-evidence-smoke_1"

    prompt = _build_rag_prompt(
        None,
        "[출처 1]\n면접고사 안내",
        question,
        "표 제목: 예시\n- 행: 정시 / 열: 면접 안내 / 값: 항공운항과",
        priority_evidence.evidence_text,
    )
    assert "[우선 표 근거]" in prompt
    assert "[우선 질의 근거]" in prompt
    assert prompt.index("[우선 표 근거]") < prompt.index("[우선 질의 근거]")

    answer = _priority_query_evidence_answer_for_request(priority_evidence, None, analysis)
    assert answer is not None
    assert "입학 홈페이지" in answer
    assert "임의로 배정" in answer
    assert _priority_query_evidence_answer_disabled_reason(priority_evidence, None, analysis) is None
    assert _priority_query_evidence_answer_for_request(
        priority_evidence,
        "JSON 형식으로만 답하세요.",
        analysis,
    ) is None
    assert _priority_query_evidence_answer_disabled_reason(
        priority_evidence,
        "JSON 형식으로만 답하세요.",
        analysis,
    ) == "custom_system_prompt"

    numeric_priority_evidence = _priority_query_evidence_for_prompt(
        ["입시결과 숫자 표"],
        [{"query_evidence_facts": [numeric_dump]}],
        ["query-evidence-smoke_2"],
        analysis,
    )
    assert numeric_priority_evidence is None

    generic_fact = "- 관련 근거: 항공운항과 면접 예약은 입학 홈페이지에서 신청한다."
    generic_priority_evidence = _priority_query_evidence_for_prompt(
        ["Ⅱ. 전형일정\n면접고사 안내"],
        [{"query_evidence_facts": [generic_fact]}],
        ["query-evidence-smoke_3"],
        analysis,
    )
    assert generic_priority_evidence is not None
    assert generic_fact in generic_priority_evidence.evidence_text
    assert _priority_query_evidence_answer_for_request(
        generic_priority_evidence,
        None,
        analysis,
    ) is None
    assert _priority_query_evidence_answer_disabled_reason(
        generic_priority_evidence,
        None,
        analysis,
    ) == "safety_conditions_not_met"

    print("query evidence priority smoke ok")


if __name__ == "__main__":
    main()
