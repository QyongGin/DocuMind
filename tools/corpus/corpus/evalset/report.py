"""분포 보고(결정 ⑥): 문항 수·답의 모양·주제·꼬리표·문서당 문항 수를 목표와 나란히 보인다.

실패를 내지 않고 '충족·부족'만 알린다. 초안을 더 쓸지, 어느 주제를 채울지 정하는 데 쓴다.
"""

from collections import Counter

from ..ledger import Ledger
from . import schema
from .split import SECTION_THRESHOLD, group_key, sample_errors

MAIN_TOTAL = 250
EASY_TOTAL = 96
SHAPE_TARGETS = {"값": 75, "목록": 38, "절차": 37, "예아니오": 25, "설명": 25, "거절": 50}
TOPIC_MIN = {"입시": 40, "학사": 40, "장학·등록금": 40, "학과·캠퍼스 생활": 40}
YEAR_TEST_MIN = 20
UNRELATED_MAX = 5
DOC_CAP = 10


def _mark(ok: bool) -> str:
    return "충족" if ok else "부족"


def build(items: list[dict], ledger: Ledger, caps: dict[str, int] | None = None) -> list[str]:
    caps = caps or {}
    live = [item for item in items if (item.get("review") or {}).get("status") != "버림"]
    main = [item for item in live if item["set"] == "본"]
    easy = [item for item in live if item["set"] == "쉬운"]
    answerable = [item for item in main if item["shape"] != "거절"]
    quarter = len(answerable) / 4
    lines = [f"본 문항 {len(main)}/{MAIN_TOTAL} · 쉬운 문항 {len(easy)}/{EASY_TOTAL} · 버림 {len(items) - len(live)}"]

    parts = Counter(item.get("part") or "미정" for item in main)
    lines.append(f"나눔: 연습 {parts['연습']} · 실전 {parts['실전']} · 미정 {parts['미정']}")
    shapes = Counter(item["shape"] for item in main)
    lines.append("모양: " + " · ".join(f"{shape} {shapes[shape]}/{target}" for shape, target in SHAPE_TARGETS.items()))
    topics = Counter(item.get("topic") or "미정" for item in main)
    lines.append("주제: " + " · ".join(f"{topic} {topics[topic]}(최소 {minimum}, {_mark(topics[topic] >= minimum)})"
                                       for topic, minimum in TOPIC_MIN.items())
                 + f" · 기타 {topics['기타']}")
    tags = Counter(tag for item in answerable for tag in item["tags"])
    lines.append(
        f"꼬리표: 표 근거 {tags['표 근거']}({_mark(tags['표 근거'] >= quarter)}) · 글 근거 {tags['글 근거']}"
        f"({_mark(tags['글 근거'] >= quarter)}) · 다른 말 {tags['다른 말']}({_mark(tags['다른 말'] >= quarter)}) · "
        f"연도 시험 {tags['연도 시험']}(최소 {YEAR_TEST_MIN}, {_mark(tags['연도 시험'] >= YEAR_TEST_MIN)}) "
        f"— 기준은 답 있는 본 문항 {len(answerable)}개의 1/4")
    unrelated = sum(1 for item in main if (item.get("refusal") or {}).get("kind") == "무관")
    lines.append(f"학교와 무관한 거절 문항 {unrelated}(최대 {UNRELATED_MAX}, {_mark(unrelated <= UNRELATED_MAX)})")
    faq_based = sum(1 for item in answerable if (ledger.get(item["evidence"][0]["doc"]) or {}).get("kind") == "faq")
    lines.append(f"FAQ를 근거로 한 본 문항 {faq_based}(최대 {len(main) // 4}, {_mark(faq_based <= len(main) // 4)})")

    per_doc = Counter(item["evidence"][0]["doc"] for item in live if item["evidence"])
    over = [f"{doc} {count}/{caps.get(doc, DOC_CAP)}" for doc, count in sorted(per_doc.items())
            if count > caps.get(doc, DOC_CAP)]
    lines.append("문서당 상한 넘음: " + (", ".join(over) if over else "없음"))
    groups = Counter(group_key(item, ledger) for item in live)
    unsplit = sorted(key for key, count in groups.items() if count > SECTION_THRESHOLD and any(
        not (item["evidence"] and item["evidence"][0].get("section"))
        for item in live if group_key(item, ledger) == key))
    lines.append("장(section)이 빠진 큰 묶음: " + (", ".join(unsplit) if unsplit else "없음"))

    needs = Counter(item.get("need") or "-" for item in items)
    statuses = Counter((item.get("review") or {}).get("status") or "미검수" for item in items)
    lines.append("사람이 볼 이유: " + " · ".join(f"{need} {needs[need]}" for need in schema.NEEDS)
                 + f" · 자동 승인 {statuses['자동 승인']}")
    lines.append("검수: " + " · ".join(f"{status} {count}" for status, count in sorted(statuses.items())))
    checked, wrong = sample_errors(items)
    if checked:
        advice = "표본을 30개 더 본다(need --more 30)" if wrong >= 2 else "자동 승인 유지"
        lines.append(f"표본 {checked}개 중 고침·버림 {wrong}개 → {advice}")
    return lines
