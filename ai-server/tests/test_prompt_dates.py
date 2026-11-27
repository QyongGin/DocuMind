"""프롬프트 날짜 줄 세 줄과 근거 머리말 「학년도:」 줄 테스트(#273, ADR-0047).

「작년 입시」, 「올해」 질문은 오늘이 어느 학년도인지와 근거 문서가 어느 학년도 것인지를 알아야 풀 수 있다.
경계는 학년도 시작 월(기본 3월 1일)과 2학기 시작 월(기본 9월 1일)이다. 데이터는 모두 합성(가나대학)이다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

import main
import prompt_dates
from prompt_dates import academic_calendar, date_lines, validate_term_months


# (기준 날짜, 지금 학년도, 학기, 지금 모집 중인 입시, 직전 입시). 학년도 경계는 2월 말과 3월 1일, 학기 경계는 8월 말과 9월 1일
BOUNDARY_CASES = [
    (date(2026, 2, 28), 2025, 2, 2026, 2025),
    (date(2026, 3, 1), 2026, 1, 2027, 2026),
    (date(2026, 8, 31), 2026, 1, 2027, 2026),
    (date(2026, 9, 1), 2026, 2, 2027, 2026),
    (date(2026, 12, 31), 2026, 2, 2027, 2026),
    (date(2027, 1, 1), 2026, 2, 2027, 2026),
]


@pytest.mark.parametrize(("today", "school_year", "semester", "recruiting", "previous"), BOUNDARY_CASES)
def test_calendar_at_boundaries(today, school_year, semester, recruiting, previous):
    calendar = academic_calendar(today)
    assert (calendar.school_year, calendar.semester) == (school_year, semester)
    assert (calendar.recruiting_year, calendar.previous_recruiting_year) == (recruiting, previous)
    assert date_lines(today) == [
        f"오늘: {today.isoformat()} ({school_year}학년도 {semester}학기)",
        f"지금 모집 중인 입시: {recruiting}학년도",
        f"직전 입시(작년에 치른 입시): {previous}학년도",
    ]


def test_date_lines_shape():
    assert date_lines(date(2026, 10, 31)) == [
        "오늘: 2026-10-31 (2026학년도 2학기)",
        "지금 모집 중인 입시: 2027학년도",
        "직전 입시(작년에 치른 입시): 2026학년도",
    ]


def test_calendar_follows_month_settings():
    # 학년도가 4월에 시작하는 학교: 3월 31일은 아직 앞 학년도 2학기, 4월 1일부터 새 학년도
    march = academic_calendar(date(2026, 3, 31), 4, 9)
    assert (march.school_year, march.semester, march.recruiting_year) == (2025, 2, 2026)
    april = academic_calendar(date(2026, 4, 1), 4, 9)
    assert (april.school_year, april.semester, april.recruiting_year) == (2026, 1, 2027)
    # 2학기가 8월에 시작하는 학교: 8월 1일부터 2학기
    assert academic_calendar(date(2026, 7, 31), 3, 8).semester == 1
    assert academic_calendar(date(2026, 8, 1), 3, 8).semester == 2


@pytest.mark.parametrize(("start", "second"), [(0, 9), (3, 13), (9, 9), (10, 9), ("3", 9), (True, 9)])
def test_invalid_month_settings_are_rejected(start, second):
    with pytest.raises(ValueError):
        validate_term_months(start, second)
    with pytest.raises(ValueError):
        academic_calendar(date(2026, 10, 31), start, second)


def test_server_month_settings(monkeypatch):
    assert (main.ACADEMIC_YEAR_START_MONTH, main.SECOND_SEMESTER_START_MONTH) == (3, 9)
    monkeypatch.setenv("AI_ACADEMIC_YEAR_START_MONTH", "4")
    monkeypatch.setenv("AI_SECOND_SEMESTER_START_MONTH", "10")
    assert main._term_month_settings() == (4, 10)
    monkeypatch.setenv("AI_ACADEMIC_YEAR_START_MONTH", "")  # 빈 값은 기본값
    assert main._term_month_settings() == (3, 10)


@pytest.mark.parametrize(("start", "second"), [("0", "9"), ("3", "13"), ("9", "3"), ("9", "9"), ("삼", "9")])
def test_server_refuses_invalid_month_settings(monkeypatch, start, second):
    # 다른 정수 설정처럼 기본값으로 되돌리지 않고, 뜰 때 이 함수가 ValueError를 내 서버가 멈춘다
    monkeypatch.setenv("AI_ACADEMIC_YEAR_START_MONTH", start)
    monkeypatch.setenv("AI_SECOND_SEMESTER_START_MONTH", second)
    with pytest.raises(ValueError, match="AI_"):
        main._term_month_settings()


def test_runtime_settings_record_month_settings():
    settings = main._model_settings()
    assert settings["academic_year_start_month"] == 3
    assert settings["second_semester_start_month"] == 9


def test_prompt_uses_server_month_settings(monkeypatch):
    monkeypatch.setattr(main, "ACADEMIC_YEAR_START_MONTH", 4)
    prompt = main._build_rag_prompt(None, "근거", "질문", today=date(2026, 3, 31))
    assert prompt.startswith("오늘: 2026-03-31 (2025학년도 2학기)\n지금 모집 중인 입시: 2026학년도\n")


# 근거 머리말 「학년도:」 줄 ------------------------------------------------------------------------

ANALYSIS_QUESTION = "가나대학 장학금 신청 기간"
META = {"source": "장학 공지.html", "posted_at": "2025-08-13", "academic_year": 2026,
        "page": 2, "chunk_index": 3, "Header 1": "장학금"}


def block_lines(meta: dict) -> list[str]:
    analysis = main._analyze_query(ANALYSIS_QUESTION)
    block = main._format_context_block(1, "가나대학 장학금 신청 기간은 9월 10일까지다.", meta, "70_3", analysis)
    return block.splitlines()


def test_academic_year_line_sits_between_chunk_and_section(monkeypatch):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    assert block_lines(META)[:7] == [
        "[출처 1]", "문서: 장학 공지.html", "게시: 2025-08-13", "위치: PDF 2페이지",
        "청크: 문서 내 4번째 청크", "학년도: 2026", "섹션: 장학금",
    ]


@pytest.mark.parametrize("value", [2026, "2026", " 2026 "])
def test_academic_year_line_reads_integer_values(monkeypatch, value):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    assert "학년도: 2026" in block_lines({**META, "academic_year": value})


@pytest.mark.parametrize("value", [None, "", "2026학년도", "미정", "2026.5", True])
def test_academic_year_line_absent_without_integer_value(monkeypatch, value):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    meta = {**META, "academic_year": value} if value is not None else {k: v for k, v in META.items() if k != "academic_year"}
    lines = block_lines(meta)
    assert not any(line.startswith("학년도:") for line in lines)
    assert lines[4:6] == ["청크: 문서 내 4번째 청크", "섹션: 장학금"]  # 다른 줄은 그대로 붙는다


def test_academic_year_not_guessed_from_title_or_posted_date(monkeypatch):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    meta = {"source": "2027학년도 가나대학 모집요강.pdf", "posted_at": "2026-05-01", "chunk_index": 0}
    assert not any(line.startswith("학년도:") for line in block_lines(meta))


# 날짜 줄 설정 꺼짐 -----------------------------------------------------------------------------------

def test_date_lines_off_by_default_drops_all_date_lines():
    assert main.PROMPT_DATE_LINES_ENABLED is False
    assert main._prompt_today(date(2026, 10, 31)) is None
    prompt = main._build_rag_prompt(None, "근거", "질문", today=main._prompt_today(date(2026, 10, 31)))
    assert not prompt.startswith("오늘:")
    assert "모집 중인 입시" not in prompt and "직전 입시" not in prompt
    lines = block_lines(META)
    assert not any(line.startswith(("게시:", "학년도:")) for line in lines)


# 평가 요청의 기준 날짜 ------------------------------------------------------------------------------

DOCS = ["가나대학 장학금 신청 기간은 9월 10일까지다."]
METAS = [{"document_id": "70", "ledger_id": "gana/bbs/70", "source": "장학 공지.html", "chunk_index": 3,
          "posted_at": "2025-08-13", "academic_year": 2026}]


@pytest.fixture
def fake_retrieval(monkeypatch):
    """임베딩·Chroma·BM25·표 사실 조회만 가짜로 바꾸고, 순위 융합과 프롬프트 조립은 실제 코드를 탄다."""
    monkeypatch.setattr(main, "_embed_query", lambda question: ([[0.1, 0.2]], {}))
    monkeypatch.setattr(
        main, "_query_vector_results",
        lambda vector, limit, include_vectors=False, **kwargs: {
            "documents": [list(DOCS)], "metadatas": [[dict(meta) for meta in METAS]], "ids": [["70_3"]],
            "distances": [[0.1]],
        },
    )
    monkeypatch.setattr(main, "_lookup_bm25_raw_chunk_candidates", lambda analysis, limit=5, **kwargs: [])
    monkeypatch.setattr(main, "_lookup_lexical_table_fact_candidates", lambda question, limit=5, **kwargs: [])
    monkeypatch.setattr(main, "_load_source_block_texts", lambda ids: {})


def test_prepare_query_uses_as_of_for_date_lines(monkeypatch, fake_retrieval):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    prompt, _, _ = main._prepare_query("가나대학 장학금 언제까지야?", 5, None, as_of=date(2026, 2, 28))
    assert prompt.startswith(
        "오늘: 2026-02-28 (2025학년도 2학기)\n지금 모집 중인 입시: 2026학년도\n직전 입시(작년에 치른 입시): 2025학년도\n"
    )
    assert "\n학년도: 2026\n" in prompt


def test_prepare_query_without_as_of_uses_korean_today(monkeypatch, fake_retrieval):
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", True)
    before = datetime.now(main.SERVICE_TIMEZONE).date()
    prompt, _, _ = main._prepare_query("가나대학 장학금 언제까지야?", 5, None)
    after = datetime.now(main.SERVICE_TIMEZONE).date()
    assert prompt.splitlines()[:3] in (prompt_dates.date_lines(before), prompt_dates.date_lines(after))


def test_prepare_query_with_date_lines_off_has_no_date_lines(fake_retrieval):
    prompt, _, _ = main._prepare_query("가나대학 장학금 언제까지야?", 5, None, as_of=date(2026, 2, 28))
    assert not prompt.startswith("오늘:")
    assert "게시:" not in prompt and "\n학년도:" not in prompt
