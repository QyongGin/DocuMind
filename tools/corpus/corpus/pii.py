"""개인정보 2단계 검사 (수집 규칙 ⑦⑧).

1차: 제목·첨부 파일명 키워드 → 내려받지 않고 보류.
2차: 받은 글의 본문 패턴 → 보류. 학교 업무 전화(032-870-…)는 잡지 않는다.
보류 건은 사람이 확인해 제외하거나 가린다. 자동 검사만으로 통과시키지 않는다.
"""

import re

TITLE_KEYWORDS = ("명단", "선발자", "합격자", "대상자", "인증자", "당첨")

TEXT_PATTERNS: dict[str, re.Pattern[str]] = {
    # 19·20으로 시작하는 8~10자리 숫자. 날짜(2026.03.02)는 점이 끼어 걸리지 않는다
    "학번형 숫자": re.compile(r"(?<!\d)(?:19|20)\d{6,8}(?!\d)"),
    "휴대전화": re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"),
    "주민등록번호 형식": re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)"),
    "가린 이름": re.compile(r"[가-힣][*○◯][가-힣]"),
}


def title_hit(title: str) -> str | None:
    for keyword in TITLE_KEYWORDS:
        if keyword in title:
            return keyword
    return None


def text_hits(text: str | None) -> list[str]:
    if not text:
        return []
    return [name for name, pattern in TEXT_PATTERNS.items() if pattern.search(text)]


def judge(title: str, text: str | None) -> tuple[str, str | None]:
    """(개인정보 상태, 사유)를 돌려준다. 상태는 '통과' 또는 '보류'."""
    keyword = title_hit(title)
    if keyword:
        return "보류", f"1차 제목·파일명: {keyword}"
    hits = text_hits(text)
    if hits:
        return "보류", "2차 본문: " + ", ".join(hits)
    return "통과", None
