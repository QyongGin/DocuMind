"""Smoke checks for runtime Markdown table fact extraction."""

from __future__ import annotations

from main import (
    _extract_table_fact_pairs,
    _extract_table_fact_row_subject,
    _extract_table_facts,
)


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

    print("table fact runtime extraction smoke ok")


if __name__ == "__main__":
    main()
