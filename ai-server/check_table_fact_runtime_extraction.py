"""Smoke checks for runtime Markdown table fact extraction."""

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
        _build_priority_table_fact_answer,
        _build_rag_prompt,
        _extract_table_fact_pairs,
        _extract_table_fact_row_subject,
        _extract_table_facts,
        _priority_table_fact_answer_for_request,
        _priority_table_fact_evidence_for_prompt,
        _typed_table_fact_contract_candidates,
    )
finally:
    os.chdir(_ORIGINAL_CWD)
    if _SMOKE_CHROMA_HOST is not None:
        os.environ["CHROMA_HOST"] = _SMOKE_CHROMA_HOST


def main() -> None:
    """Verify row labels survive grouped Markdown table extraction."""
    sample = """
###### 전형 지원자격

|전형| |지원자격|
|---|---|---|
|지역전형|유형Ⅰ|중학교 입학일부터 고등학교 졸업일까지 거주한 지원자|
| |유형Ⅱ|초등학교 입학일부터 고등학교 졸업일까지 거주한 지원자|
| |공통|지원자격을 졸업일까지 유지해야 함|
|---|---|---|
"""
    facts = _extract_table_facts(sample, {"document_id": "runtime-table-smoke"})
    subjects = [_extract_table_fact_row_subject(fact) for fact in facts]

    assert "유형Ⅰ" in subjects
    assert "유형Ⅱ" in subjects
    assert "공통" in subjects
    assert "---" not in subjects

    fact_by_subject = {
        _extract_table_fact_row_subject(fact): _extract_table_fact_pairs(fact)
        for fact in facts
    }
    assert ("전형", "지역전형") in fact_by_subject["유형Ⅰ"]
    assert ("전형", "유형Ⅰ") in fact_by_subject["유형Ⅰ"]
    assert ("전형", "지역전형") in fact_by_subject["유형Ⅱ"]
    assert ("전형", "유형Ⅱ") in fact_by_subject["유형Ⅱ"]

    ordinary_sample = """
###### 학과별 지원자격

|모집단위|전형|지원자격|
|---|---|---|
|컴퓨터정보공학과|일반고|일반고 졸업자|
"""
    ordinary_facts = _extract_table_facts(
        ordinary_sample,
        {"document_id": "runtime-table-smoke"},
    )
    ordinary_subjects = [
        _extract_table_fact_row_subject(fact)
        for fact in ordinary_facts
    ]
    assert "컴퓨터정보공학과" in ordinary_subjects
    assert "일반고" not in ordinary_subjects

    wide_sample = """
###### 전형 지원자격

|전형| |지원자격|항목1|항목2|항목3|항목4|항목5|항목6|항목7|항목8|
|---|---|---|---|---|---|---|---|---|---|---|
|지역전형|유형Ⅰ|조건1|A1|B1|C1|D1|E1|F1|G1|H1|
| |유형Ⅱ|조건2|A2|B2|C2|D2|E2|F2|G2|H2|
"""
    typed_candidates = _typed_table_fact_contract_candidates(
        chunk_id="wide-table-smoke",
        doc=wide_sample,
        meta={"document_id": "runtime-table-smoke"},
        source_block_id="source-wide-table-smoke",
    )
    typed_rows = {
        table_fact.row_label
        for table_fact, _ in typed_candidates
    }
    assert "유형Ⅰ" in typed_rows
    assert "유형Ⅱ" in typed_rows

    stale_fact_candidates = _typed_table_fact_contract_candidates(
        chunk_id="stale-fact-smoke",
        doc=sample,
        meta={
            "document_id": "runtime-table-smoke",
            "matched_table_facts": [
                "전형 지원자격: 오래된행 행 정보는 지원자격=오래된 값이다."
            ],
        },
        source_block_id="source-stale-fact-smoke",
    )
    stale_fact_sources = {
        fact_source
        for _, fact_source in stale_fact_candidates
    }
    stale_fact_rows = {
        table_fact.row_label
        for table_fact, _ in stale_fact_candidates
    }
    assert stale_fact_sources == {"extracted_from_candidate_doc"}
    assert "오래된행" not in stale_fact_rows

    priority_evidence = _priority_table_fact_evidence_for_prompt(
        "지역전형 지원 자격은",
        [sample],
        [{"document_id": "runtime-table-smoke"}],
        ["runtime-table-smoke_1"],
    )
    assert priority_evidence is not None
    assert "공통 맥락: 전형=지역전형" in priority_evidence.evidence_text
    assert "행: 유형Ⅰ / 열: 지원자격" in priority_evidence.evidence_text
    assert "행: 유형Ⅱ / 열: 지원자격" in priority_evidence.evidence_text
    assert "행: 공통" not in priority_evidence.evidence_text

    prompt = _build_rag_prompt(
        None,
        "[출처 1]\n표 원문",
        "지역전형 지원 자격은",
        priority_evidence.evidence_text,
    )
    assert "[우선 표 근거]" in prompt
    assert "공통 맥락: 전형=지역전형" in prompt

    priority_answer = _build_priority_table_fact_answer(priority_evidence)
    assert priority_answer is not None
    assert "유형Ⅰ: 중학교 입학일부터 고등학교 졸업일까지 거주한 지원자" in priority_answer
    assert "유형Ⅱ: 초등학교 입학일부터 고등학교 졸업일까지 거주한 지원자" in priority_answer
    assert _priority_table_fact_answer_for_request(priority_evidence, None) == priority_answer
    assert _priority_table_fact_answer_for_request(
        priority_evidence,
        "JSON 형식으로만 답하세요.",
    ) is None

    type_priority_evidence = _priority_table_fact_evidence_for_prompt(
        "지역전형 유형 지원자격은",
        [sample],
        [{"document_id": "runtime-table-smoke"}],
        ["runtime-table-smoke_1"],
    )
    assert type_priority_evidence is not None
    assert "공통 맥락: 전형=지역전형" in type_priority_evidence.evidence_text
    type_priority_answer = _build_priority_table_fact_answer(type_priority_evidence)
    assert type_priority_answer is not None
    assert "유형Ⅰ: 중학교 입학일부터 고등학교 졸업일까지 거주한 지원자" in type_priority_answer
    assert "유형Ⅱ: 초등학교 입학일부터 고등학교 졸업일까지 거주한 지원자" in type_priority_answer

    repeated_answer_sample = """
###### 학과별 지원자격

|구분|지원자격|
|---|---|
|일반고|고등학교 졸업자|
|특성화고|고등학교 졸업자|
"""
    ambiguous_priority_evidence = _priority_table_fact_evidence_for_prompt(
        "지원자격은 무엇인가요?",
        [repeated_answer_sample],
        [{"document_id": "runtime-table-smoke"}],
        ["runtime-table-smoke_2"],
    )
    assert ambiguous_priority_evidence is None

    print("table fact runtime extraction smoke ok")


if __name__ == "__main__":
    main()
