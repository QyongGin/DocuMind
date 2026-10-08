"""개발셋·테스트셋 분할(결정 ⑤), 휴먼 리뷰 대상 고르기(결정 ⑦), 버전 고정(지문).

순서: 자동 검증 → 이중 라벨링 → 분할 → 휴먼 리뷰 대상 고르기(나머지는 자동 승인) → 휴먼 리뷰 → 버전 고정.
표본을 테스트셋의 자동 승인 문항에서 뽑으므로 나누기는 휴먼 리뷰보다 먼저 한다.
"""

import random
from collections import Counter, defaultdict
from datetime import date

from ..ledger import Ledger
from . import schema

HELD_RATIO = 0.4
SECTION_THRESHOLD = 10  # 한 문서 묶음의 문항이 이보다 많으면 장(evidence[0].section) 단위로 나눈다
SAMPLE_SIZE = 30
REASON_ORDER = ("불일치", "경고", "테스트셋 답없음")
HUMAN_STATUSES = ("승인", "고침", "버림")


def group_key(item: dict, ledger: Ledger) -> str:
    """나누는 단위: 근거 문서(답 없는 문항은 가까운 문서)의 문서 묶음. 가까운 문서가 없는 답 없는 문항은 문항 하나."""
    if item["shape"] == "답없음":
        doc = (item.get("unanswerable") or {}).get("near")
        if not doc:
            return f"문항:{item['id']}"
    else:
        doc = item["evidence"][0]["doc"]
    row = ledger.get(doc) or {}
    return row.get("group_id") or f"문서:{doc}"


def units(items: list[dict], ledger: Ledger, section_threshold: int = SECTION_THRESHOLD) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[group_key(item, ledger)].append(item)
    result: dict[str, list[dict]] = {}
    for key, members in groups.items():
        if len(members) <= section_threshold:
            result[key] = members
            continue
        for item in members:
            section = (item["evidence"][0].get("section") if item["evidence"] else None) or "장 없음"
            result.setdefault(f"{key}#{section}", []).append(item)
    return result


def assign_parts(items: list[dict], ledger: Ledger, seed: int, held_ratio: float = HELD_RATIO,
                 section_threshold: int = SECTION_THRESHOLD) -> dict[str, str]:
    """주제마다 테스트셋이 문항의 약 40%가 되도록 단위째 무작위로 배정한다. 같은 씨앗이면 같은 결과."""
    by_topic: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for key, members in units(items, ledger, section_threshold).items():
        by_topic[members[0].get("topic") or "미정"].append((key, members))
    rng = random.Random(seed)
    parts: dict[str, str] = {}
    for topic in sorted(by_topic):
        entries = sorted(by_topic[topic], key=lambda entry: entry[0])
        rng.shuffle(entries)
        target = round(sum(len(members) for _, members in entries) * held_ratio)
        held = 0
        for _, members in entries:
            part = "test" if abs(held + len(members) - target) < abs(held - target) else "dev"
            held += len(members) if part == "test" else 0
            for item in members:
                parts[item["id"]] = part
    return parts


def select_for_review(items: list[dict], seed: int, today: date, sample_size: int = SAMPLE_SIZE) -> Counter:
    """사람이 볼 이유를 정한다. 이유가 없는 문항은 자동 승인하고, 테스트셋 자동 승인 문항에서 표본을 뽑는다.

    이미 이유를 정한 문항(`review_reason` 칸이 있는 문항)은 건드리지 않아 다시 실행해도 결과가 같다.
    """
    fresh = [item for item in items if "review_reason" not in item]
    blocked = [item["id"] for item in fresh
               if (item.get("validation") or {}).get("errors") or not item.get("second_annotation") or not item.get("part")]
    if blocked:
        raise ValueError(f"자동 검증 오류가 있거나 이중 라벨링·나누기를 하지 않은 문항: {', '.join(blocked[:10])}")
    candidates = []
    for item in fresh:
        reasons = []
        if item["second_annotation"]["verdict"] in ("불일치", "애매"):
            reasons.append("불일치")
        if item["validation"].get("warnings"):
            reasons.append("경고")
        if item["part"] == "test" and item["shape"] == "답없음":
            reasons.append("테스트셋 답없음")
        item["review_reason"] = min(reasons, key=REASON_ORDER.index) if reasons else None
        if item["review_reason"] is None and item["part"] == "test":
            candidates.append(item)
    for item in random.Random(seed).sample(sorted(candidates, key=lambda entry: entry["id"]),
                                           min(sample_size, len(candidates))):
        item["review_reason"] = "표본"
    for item in fresh:
        if item["review_reason"] is None:
            item["review"] = {"status": "자동 승인", "reason": "자동 검증·이중 라벨링 통과", "at": today.isoformat(), "sec": 0}
    return Counter(item["review_reason"] or "자동 승인" for item in fresh)


def more_sample(items: list[dict], seed: int, count: int) -> list[str]:
    """표본에서 오류가 2개 이상이면 테스트셋 자동 승인 문항에서 표본을 더 뽑는다."""
    candidates = sorted((item for item in items if item.get("part") == "test" and item.get("review_reason") is None
                         and (item.get("review") or {}).get("status") == "자동 승인"),
                        key=lambda entry: entry["id"])
    chosen = random.Random(seed).sample(candidates, min(count, len(candidates)))
    for item in chosen:
        item["review_reason"] = "표본"
        item["review"] = None
    return [item["id"] for item in chosen]


def sample_errors(items: list[dict]) -> tuple[int, int]:
    """(사람이 본 표본 수, 그중 고침·버림 수)."""
    checked = [item for item in items
               if item.get("review_reason") == "표본" and (item.get("review") or {}).get("status") in HUMAN_STATUSES]
    return len(checked), sum(1 for item in checked if item["review"]["status"] in ("고침", "버림"))


def freeze_text(items: list[dict], version: str, index_backup: str, seed: int, today: date) -> str:
    """버전 고정 기록. 사람이 볼 문항이 모두 판정되고(보류 없음), 버리지 않은 문항이 모두 자동 검증을 통과했고,
    모든 문항이 나뉘어 있어야 한다."""
    pending = [item["id"] for item in items if item.get("review_reason")
               and (item.get("review") or {}).get("status") not in HUMAN_STATUSES]
    if pending:
        raise ValueError(f"아직 판정하지 않았거나 보류인 문항: {', '.join(pending[:10])}")
    unchecked = [item["id"] for item in items if (item.get("review") or {}).get("status") != "버림"
                 and (not item.get("validation") or item["validation"].get("errors"))]
    if unchecked:
        raise ValueError(f"자동 검증을 다시 해야 하는 문항(고친 뒤 검사 전이거나 오류): {', '.join(unchecked[:10])}")
    unassigned = [item["id"] for item in items if item.get("part") not in schema.PARTS]
    if unassigned:
        raise ValueError(f"개발셋·테스트셋이 정해지지 않은 문항: {', '.join(unassigned[:10])}")
    kept = [item for item in items if (item.get("review") or {}).get("status") != "버림"]
    main = [item for item in kept if item["set"] == "본"]
    parts = Counter(item["part"] for item in main)
    shapes = Counter(item["shape"] for item in main)
    topics = Counter(item.get("topic") or "미정" for item in main)
    easy = [item for item in kept if item["set"] == "쉬운"]
    return "\n".join([
        f"version: {version}",
        f"date: {today.isoformat()}",
        f"evalset_sha256: {schema.fingerprint(items)}",
        f"index_backup: {index_backup}",
        f"split_seed: {seed}",
        f"counts: 본 {len(main)} (개발셋 {parts['dev']} / 테스트셋 {parts['test']}), 쉬운 {len(easy)}, 버림 {len(items) - len(kept)}",
        "by_shape: " + " · ".join(f"{shape} {shapes[shape]}" for shape in schema.SHAPES),
        "by_topic: " + " · ".join(f"{topic} {count}" for topic, count in sorted(topics.items())),
    ]) + "\n"
