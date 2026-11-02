"""학습 예시의 '그날'과 그날 서비스 색인에 없었을 문서(ADR-0047).

그날 = 질문 재료 문서의 게시일(첨부처럼 날짜가 비면 부모 게시글의 날짜). 게시일이 없는 재료(학과 페이지·규정)와
재료가 없는 예시(엉뚱한 근거 종류)는 근거를 붙이는 날이다.
그날 서비스 색인에 없었을 문서는 데이터셋 AI 서버의 평가 전용 칸(exclude_ledger_ids)으로 검색 후보에서 뺀다.
그날 뒤에 올라온 문서는 늘 빼고, 그날 이미 유효 기간이 지난 문서는 약 90%의 예시에서 뺀다 — 나머지 약 10%는 옛 판을
남겨 운영에서 여러 학기 판이 섞이는 사고를 연습시킨다. 판단은 문서 대장의 게시일·유효 기간 한 곳에서 한다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

# 그날 이미 만료된 판을 남기는 예시 비율(ADR-0047 결정 2). 운영 개발셋의 여러 학기 판 섞임 3.4%보다 조금 높게 잡은
# 판단값이다 — 학습 1회차 결과로 다시 본다
OLD_VERSIONS_SHARE = 0.1


@dataclass(frozen=True)
class Dates:
    """문서 하나의 게시일·유효 기간(YYYY-MM-DD, 없으면 None)."""

    posted_at: str | None
    valid_until: str | None


def _day(value) -> str | None:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def ledger_dates(con: sqlite3.Connection) -> dict[str, Dates]:
    """데이터셋용 색인에 올라간 문서(대장 uploads의 대상 dataset)의 게시일·유효 기간. 날짜가 비면 부모 문서의 날짜를 쓴다."""
    own = {row[0]: (row[1], _day(row[2]), _day(row[3]))
           for row in con.execute("SELECT doc_id, parent_id, posted_at, valid_until FROM ledger")}
    uploaded = [row[0] for row in con.execute(
        "SELECT doc_id FROM uploads WHERE target = 'dataset' AND status IN ('ready', 'exists')")]
    dates = {}
    for doc_id in uploaded:
        parent_id, posted, valid = own.get(doc_id, (None, None, None))
        parent = own.get(parent_id) if parent_id else None
        if parent:
            posted, valid = posted or parent[1], valid or parent[2]
        dates[doc_id] = Dates(posted, valid)
    return dates


def the_day(material_ledger_id: str | None, dates: dict[str, Dates], today: str) -> str:
    """그날: 질문 재료 문서의 게시일. 재료가 없거나 게시일이 없는 문서면 근거를 붙이는 날(today)."""
    found = dates.get(material_ledger_id or "")
    return found.posted_at if found and found.posted_at else today


def keeps_old_versions(item_id: str, share: float = OLD_VERSIONS_SHARE) -> bool:
    """그날 이미 만료된 판을 남기는 예시인가. 예시 번호로 정해 다시 돌려도 같은 답이 나온다."""
    return int(hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:8], 16) / 0x100000000 < share


def excluded_ledger_ids(day: str, dates: dict[str, Dates], keep_old: bool = False) -> list[str]:
    """그날 서비스 색인에 없었을 문서: 그날 뒤에 올라온 문서(늘)와 그날 이미 유효 기간이 지난 문서(keep_old가 아니면).
    게시일·유효 기간이 없는 문서(페이지·규정)는 빼지 않는다."""
    out = []
    for doc_id, found in dates.items():
        if found.posted_at and found.posted_at > day:
            out.append(doc_id)
        elif not keep_old and found.valid_until and found.valid_until < day:
            out.append(doc_id)
    return sorted(out)
