"""개발셋·테스트셋 나누기(결정 ⑤), 휴먼 리뷰 대상 고르기(결정 ⑦), 표본 추가, 고정."""

from collections import Counter
from datetime import date

import pytest
from evalset_data import item, unanswerable_item

from corpus.evalset import split

TODAY = date(2026, 10, 5)


def many_items(groups: int = 30, per_group: int = 3, topic: str = "학사") -> list[dict]:
    """문서 하나에 문항 여러 개. 대장에 없는 문서는 문서 ID가 곧 묶음이다."""
    items = []
    for group in range(groups):
        for index in range(per_group):
            number = len(items) + 1
            items.append(item(f"ev-{number:04d}", question=f"질문 {number}", topic=topic,
                              evidence=[{"doc": f"gana/doc/{group}", "quote": "전형료 30,000원"}]))
    return items


def ready(items: list[dict], parts: dict[str, str]) -> list[dict]:
    for entry in items:
        entry.update(part=parts[entry["id"]], validation={"errors": [], "warnings": []}, second_annotation={"verdict": "일치"})
    return items


def test_same_seed_same_parts_and_groups_stay_together(ledger):
    items = many_items()
    first = split.assign_parts(items, ledger, seed=7)
    assert first == split.assign_parts(many_items(), ledger, seed=7)
    assert first != split.assign_parts(many_items(), ledger, seed=8)
    by_doc = {}
    for entry in items:
        by_doc.setdefault(entry["evidence"][0]["doc"], set()).add(first[entry["id"]])
    assert all(len(parts) == 1 for parts in by_doc.values())  # 같은 문서의 문항은 한쪽에만
    held = sum(1 for part in first.values() if part == "test")
    assert abs(held - round(len(items) * 0.4)) <= 3


def test_held_share_is_per_topic(ledger):
    items = many_items(20, 2, "학사") + many_items(20, 2, "입시")
    for index, entry in enumerate(items, 1):  # ID·문서가 겹치지 않게 다시 붙인다
        entry["id"] = f"ev-{index:04d}"
        entry["evidence"][0]["doc"] += f"/{entry['topic']}"
    parts = split.assign_parts(items, ledger, seed=1)
    for topic in ("학사", "입시"):
        held = sum(1 for entry in items if entry["topic"] == topic and parts[entry["id"]] == "test")
        assert 14 <= held <= 18  # 주제마다 40개의 40% 안팎


def test_big_document_is_split_by_section(ledger):
    items = [item(f"ev-{number:04d}", question=f"요강 질문 {number}", topic="입시",
                  evidence=[{"doc": "gana/viewer/guide", "quote": "q", "section": f"장{number % 4}"}])
             for number in range(1, 25)]
    parts = split.assign_parts(items, ledger, seed=3)
    assert set(parts.values()) == {"dev", "test"}  # 한 문서라도 장 단위로 갈린다
    by_section = {}
    for entry in items:
        by_section.setdefault(entry["evidence"][0]["section"], set()).add(parts[entry["id"]])
    assert all(len(found) == 1 for found in by_section.values())


def test_select_for_review_and_auto_approve(ledger):
    items = many_items(20, 2)
    parts = {entry["id"]: ("test" if index % 2 else "dev") for index, entry in enumerate(items)}
    ready(items, parts)
    items[0]["second_annotation"] = {"verdict": "불일치"}
    items[2]["second_annotation"] = {"verdict": "애매"}
    items[4]["validation"]["warnings"] = ["부재 확인에 걸린 글 1건"]
    held_unanswerable = unanswerable_item("ev-0900", part="test", validation={"errors": [], "warnings": []}, second_annotation={"verdict": "일치"})
    items.append(held_unanswerable)
    counts = split.select_for_review(items, seed=5, today=TODAY, sample_size=10)
    assert (items[0]["review_reason"], items[2]["review_reason"], items[4]["review_reason"], held_unanswerable["review_reason"]) == ("불일치", "불일치", "경고", "테스트셋 답없음")
    samples = [entry for entry in items if entry["review_reason"] == "표본"]
    assert len(samples) == 10 and all(entry["part"] == "test" for entry in samples)
    auto = [entry for entry in items if entry["review_reason"] is None]
    assert all(entry["review"]["status"] == "자동 승인" for entry in auto)
    assert counts["자동 승인"] == len(auto)
    before = [dict(entry) for entry in items]
    split.select_for_review(items, seed=99, today=TODAY)  # 이미 정한 문항은 다시 고르지 않는다
    assert [entry.get("review_reason") for entry in items] == [entry.get("review_reason") for entry in before]


def test_select_for_review_requires_validation_annotation_and_parts(ledger):
    items = many_items(2, 1)
    ready(items, {entry["id"]: "dev" for entry in items})
    items[1]["validation"]["errors"] = ["인용이 원문에 없음"]
    with pytest.raises(ValueError, match="ev-0002"):
        split.select_for_review(items, seed=1, today=TODAY)
    assert all("review_reason" not in entry for entry in items)  # 막히면 어느 문항도 바꾸지 않는다
    items[1]["validation"]["errors"] = []
    del items[1]["second_annotation"]
    with pytest.raises(ValueError):
        split.select_for_review([items[1]], seed=1, today=TODAY)


def test_more_sample_and_sample_errors(ledger):
    items = many_items(10, 2)
    ready(items, {entry["id"]: "test" for entry in items})
    split.select_for_review(items, seed=2, today=TODAY, sample_size=4)
    for entry, status in zip([entry for entry in items if entry["review_reason"] == "표본"], ["승인", "고침", "버림", "승인"]):
        entry["review"] = {"status": status}
    assert split.sample_errors(items) == (4, 2)
    added = split.more_sample(items, seed=3, count=5)
    assert len(added) == 5 and all(entry["review"] is None for entry in items if entry["id"] in added)
    assert Counter(entry["review_reason"] for entry in items)["표본"] == 9


def test_freeze_requires_all_reviews_and_reports_counts():
    passed = {"errors": [], "warnings": []}
    items = [item("ev-0001", part="dev", review_reason="불일치", review={"status": "보류"}, validation=passed),
             item("ev-0002", question="둘", part="test", review_reason=None, review={"status": "자동 승인"}, validation=passed),
             item("ev-0003", question="셋", part="test", review_reason="표본", review={"status": "버림"})]  # 버린 문항은 검사 없어도 됨
    with pytest.raises(ValueError, match="ev-0001"):
        split.freeze_text(items, "v1", "20261004-201713", 7, TODAY)
    items[0]["review"] = {"status": "고침"}
    items[0]["validation"] = None  # 고친 뒤 자동 검증 전
    with pytest.raises(ValueError, match="자동 검증을 다시 해야 하는 문항.*ev-0001"):
        split.freeze_text(items, "v1", "20261004-201713", 7, TODAY)
    items[0]["validation"] = {"errors": ["인용 없음"], "warnings": []}
    with pytest.raises(ValueError, match="ev-0001"):
        split.freeze_text(items, "v1", "20261004-201713", 7, TODAY)
    items[0]["validation"] = passed
    text = split.freeze_text(items, "v1", "20261004-201713", 7, TODAY)
    assert "본 2 (개발셋 1 / 테스트셋 1), 쉬운 0, 버림 1" in text
    assert "evalset_sha256: " in text and "split_seed: 7" in text
