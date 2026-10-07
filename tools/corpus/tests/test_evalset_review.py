"""검수 화면 HTML 만들기와 검수 기록 합치기(결정 ④·⑦)."""

import json
from datetime import datetime

from evalset_data import build_corpus, item, refusal_item

from corpus.evalset import checks, review

BUILT = datetime(2026, 10, 6, 9, 30, 0)


def screen_data(html: str) -> dict:
    """HTML에 넣은 자료(`const D=...;`)를 다시 읽는다."""
    start = html.index("const D=") + len("const D=")
    return json.loads(html[start:html.index(";\nconst CHECKS")].replace("<\\/", "</"))


def test_quote_span_ignores_spaces_and_table_bars():
    text = "| 구분 | 수시 1차 |\n| 전형료 | 30,000원 |\n원서 접수"
    start, end = review.quote_span(text, "전형료 30,000원")
    assert text[start:end] == "전형료 | 30,000원"
    assert review.quote_span(text, "전형료 99,000원") is None and review.quote_span(text, " ") is None


def test_window_shows_short_text_whole_and_long_text_around_quote():
    short = "가나대학 안내\n전형료 30,000원"
    assert review.window(short, [(8, 20)]) == (0, short)
    lines = [f"{number:05d}번째 줄 내용입니다" for number in range(2000)]
    long_text = "\n".join(lines)
    at = long_text.index("01500번째")
    start, shown = review.window(long_text, [(at, at + 5)])
    assert len(shown) < len(long_text) and "01500번째" in shown
    assert start == 0 or long_text[start - 1] == "\n"  # 줄 경계에서 자른다
    assert shown.split("\n")[-1] in lines


def test_build_html_holds_only_items_people_must_see(ledger, tmp_path):
    build_corpus(ledger, tmp_path)
    items = [
        item("ev-0001", need="불일치", part="실전",
             cross={"answer": "25,000원입니다.", "verdict": "불일치", "label": "틀림", "reader": "원본 HTML", "model": "m"}),
        refusal_item("ev-0002", need="실전용 거절", part="실전", cross={"verdict": "일치"}),
        item("ev-0003", need=None, part="연습", review={"status": "자동 승인", "reason": "", "at": "2026-10-06", "sec": 0}),
        item("ev-0004", question="</script><script>alert(1)</script> 원서비?", need="표본", part="실전"),
    ]
    html, count = review.build_html(items, checks.TextSource(ledger, tmp_path), ledger, BUILT, "evalset.jsonl")
    assert count == 3 and "</script><script>alert(1)" not in html  # 질문 글이 스크립트를 끝내지 못한다
    data = screen_data(html)
    assert [entry["id"] for entry in data["items"]] == ["ev-0001", "ev-0002", "ev-0004"]
    assert data["total"] == 4 and data["auto"] == 1 and data["built_at"] == "2026-10-06T09:30:00"
    first = data["items"][0]
    assert first["why"] == "교차 확인 답: 25,000원입니다. — 규칙 판정 '틀림'"
    source = first["sources"][0]
    start, end = source["spans"][0]
    assert source["doc"] == "gana/page/fee" and "전형료" in source["text"][start:end]
    refusal = data["items"][1]
    assert refusal["sources"][0]["where"] == "가까운 문서" and refusal["refusal"]["check"]["hits"] == 0
    assert "evalset merge --records" in html


def record(item_id: str, status: str, at: str, **extra) -> dict:
    return {"id": item_id, "status": status, "reason": extra.pop("reason", ""), "changed": extra.pop("changed", []),
            "sec": 42, "at": at, "screen": "2026-10-06T09:30:00", **extra}


def test_merge_applies_latest_record_and_is_idempotent():
    items = [item("ev-0001", machine={"errors": [], "warnings": []}), item("ev-0002"), refusal_item("ev-0003")]
    records = [
        record("ev-0001", "보류", "2026-10-06T10:00:00", reason="2차 기간도 넣나?"),
        record("ev-0001", "고침", "2026-10-06T10:05:00", reason="다른 표기 추가", changed=["facts"],
               edits={"facts": [{"name": "전형료", "values": ["30,000원", "3만 원", "삼만 원"]}]}),
        record("ev-0002", "승인", "2026-10-06T10:06:00"),
        record("ev-0003", "버림", "2026-10-06T10:07:00", reason="시점지남"),
    ]
    result = review.merge(items, records)
    assert result["errors"] == [] and dict(result["counts"]) == {"고침": 1, "승인": 1, "버림": 1}
    fixed = items[0]
    assert fixed["facts"][0]["values"][-1] == "삼만 원" and fixed["rev"] == 2 and fixed["machine"] is None
    assert fixed["review"] == {"status": "고침", "reason": "다른 표기 추가", "at": "2026-10-06T10:05:00", "sec": 42,
                               "changed": ["facts"]}
    assert items[2]["review"]["status"] == "버림" and items[2]["review"]["reason"] == "시점지남"

    again = review.merge(items, records)  # 같은 기록을 두 번 합쳐도 그대로
    assert dict(again["counts"]) == {"이미 합침": 3} and items[0]["rev"] == 2


def test_merge_reports_bad_records_without_touching_items():
    items = [item("ev-0001"), item("ev-0002")]
    result = review.merge(items, [
        record("ev-9999", "승인", "2026-10-06T10:00:00"),
        record("ev-0001", "통과", "2026-10-06T10:00:00"),
        record("ev-0002", "고침", "2026-10-06T10:00:00", edits={"evidence": []}),
        {"status": "승인"},
    ])
    assert result["errors"] == ["ev-0001: 판정 값이 목록에 없음(통과)",
                                "ev-0002: 고친 칸이 없거나 고칠 수 없는 칸(evidence)", "정본에 없는 문항: ev-9999"]
    assert "review" not in items[0] and items[1]["rev"] == 1

    broken = review.merge(items, [record("ev-0002", "고침", "2026-10-06T10:00:00", edits={"answer": " "})])
    assert broken["errors"][0].startswith("ev-0002: 고친 내용이 형식에 맞지 않음") and items[1]["answer"].strip()
