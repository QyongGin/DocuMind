"""프롬프트 맨 위 날짜 줄 세 줄을 기준 날짜에서 계산한다(#273, ADR-0047 변경 메모).

「작년 입시」, 「올해」 같은 질문은 달력의 해를 그대로 학년도로 옮기면 틀린다. 가을에 치르는 입시는 다음 해
학년도 이름으로 불리기 때문이다(2026년 가을 모집은 2027학년도 입시). 모델에게 계산을 맡기지 않고 규칙으로 푼
값만 프롬프트에 적는다.

    오늘: 2026-10-31 (2026학년도 2학기)
    지금 모집 중인 입시: 2027학년도
    직전 입시(작년에 치른 입시): 2026학년도

규칙(설정 둘: 학년도 시작 월, 2학기 시작 월):
- 지금 학년도: 달이 학년도 시작 월 이상이면 그 해, 아니면 앞 해(1~2월은 앞 학년도 2학기로 본다).
- 학기: 학년도 시작 월 이상이고 2학기 시작 월 미만이면 1, 그 밖은 2.
- 지금 모집 중인 입시: 달이 학년도 시작 월 이상이면 그 해 + 1, 아니면 그 해. 직전 입시는 그 값 - 1.

이 모듈은 날짜와 설정값만 받는 순수 함수다. 설정을 읽고 날짜 줄을 켜고 끄는 일은 `main.py`가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DEFAULT_ACADEMIC_YEAR_START_MONTH = 3
DEFAULT_SECOND_SEMESTER_START_MONTH = 9


@dataclass(frozen=True)
class AcademicCalendar:
    """기준 날짜 하나의 학년도, 학기, 입시 학년도."""

    today: date
    school_year: int
    semester: int
    recruiting_year: int

    @property
    def previous_recruiting_year(self) -> int:
        return self.recruiting_year - 1


def validate_term_months(academic_year_start_month: int, second_semester_start_month: int) -> None:
    """두 월 설정이 1~12 안이고 학년도 시작 월이 2학기 시작 월보다 앞인지 본다. 아니면 ValueError."""
    for name, month in (
        ("학년도 시작 월", academic_year_start_month),
        ("2학기 시작 월", second_semester_start_month),
    ):
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError(f"{name}은 1~12 정수여야 한다: {month!r}")
    if academic_year_start_month >= second_semester_start_month:
        raise ValueError(
            "학년도 시작 월은 2학기 시작 월보다 작아야 한다: "
            f"{academic_year_start_month} >= {second_semester_start_month}"
        )


def academic_calendar(
    today: date,
    academic_year_start_month: int = DEFAULT_ACADEMIC_YEAR_START_MONTH,
    second_semester_start_month: int = DEFAULT_SECOND_SEMESTER_START_MONTH,
) -> AcademicCalendar:
    """기준 날짜에서 지금 학년도와 학기, 지금 모집 중인 입시 학년도를 계산한다."""
    validate_term_months(academic_year_start_month, second_semester_start_month)
    year_started = today.month >= academic_year_start_month
    semester = 1 if academic_year_start_month <= today.month < second_semester_start_month else 2
    return AcademicCalendar(
        today=today,
        school_year=today.year if year_started else today.year - 1,
        semester=semester,
        recruiting_year=today.year + 1 if year_started else today.year,
    )


def date_lines(
    today: date,
    academic_year_start_month: int = DEFAULT_ACADEMIC_YEAR_START_MONTH,
    second_semester_start_month: int = DEFAULT_SECOND_SEMESTER_START_MONTH,
) -> list[str]:
    """프롬프트 맨 위에 넣을 날짜 줄 세 줄."""
    calendar = academic_calendar(today, academic_year_start_month, second_semester_start_month)
    return [
        f"오늘: {today.isoformat()} ({calendar.school_year}학년도 {calendar.semester}학기)",
        f"지금 모집 중인 입시: {calendar.recruiting_year}학년도",
        f"직전 입시(작년에 치른 입시): {calendar.previous_recruiting_year}학년도",
    ]
