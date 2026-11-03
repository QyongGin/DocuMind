"""학습 예시 변환과 검증 몫 고르기(이슈 #223). 예시는 지어낸 가나대학이다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import load_examples, load_pairs, split_examples, to_preference, to_prompt_completion  # noqa: E402

KINDS = {"fact": 8, "table": 8, "procedure": 6, "refuse_guide": 6, "multi": 5, "partial": 4}


def example(number: int, kind: str, group: str) -> dict:
    return {
        "id": f"gana-{number:03d}",
        "messages": [
            {"role": "user", "content": f"[검색 근거]\n[출처 1]\n가나대학 공지 {number}\n\n[사용자 질문]\n질문 {number}"},
            {"role": "assistant", "content": f"가나대학 답 {number}입니다.\n\n[출처 1]"},
        ],
        "meta": {"kind": kind, "group_id": group},
    }


@pytest.fixture
def examples() -> list[dict]:
    rows, number = [], 0
    for kind, count in KINDS.items():
        for _ in range(count):
            number += 1
            rows.append(example(number, kind, f"공지:{number}"))
    # 범위 밖 거절은 문서와 상관없이 한 묶음이다
    for _ in range(3):
        number += 1
        rows.append(example(number, "refuse_offtopic", "범위밖"))
    return rows


def test_prompt_completion_keeps_prompt_and_answer(examples):
    converted = to_prompt_completion(examples[0])
    assert converted["prompt"] == [{"role": "user", "content": examples[0]["messages"][0]["content"]}]
    assert converted["completion"] == [{"role": "assistant", "content": "가나대학 답 1입니다.\n\n[출처 1]"}]


def test_split_follows_kind_ratio_and_is_repeatable(examples):
    train, valid = split_examples(examples, valid_size=10, seed=42)

    assert len(valid) == 10 and len(train) == len(examples) - 10
    assert {e["id"] for e in train}.isdisjoint({e["id"] for e in valid})
    kinds = sorted(e["meta"]["kind"] for e in valid)
    # 40개 중 10개: 종류마다 개수 비율대로(8 → 2, 6 → 1~2, 3 → 1)
    assert kinds.count("fact") == 2 and kinds.count("table") == 2
    assert split_examples(examples, valid_size=10, seed=42) == (train, valid)
    assert split_examples(examples, valid_size=10, seed=7)[1] != valid


def test_split_keeps_document_groups_together():
    rows = [example(n, "fact", "공지:같은글" if n <= 4 else f"공지:{n}") for n in range(1, 11)]
    train, valid = split_examples(rows, valid_size=2, seed=1)
    shared = {"gana-001", "gana-002", "gana-003", "gana-004"}
    # 같은 글로 만든 예시 넷은 혼자인 묶음이 충분하면 검증 몫에 들어가지 않는다
    assert shared.isdisjoint({e["id"] for e in valid})


def test_load_rejects_unexpected_turns(tmp_path):
    path = tmp_path / "bad.jsonl"
    bad = example(1, "fact", "공지:1")
    bad["messages"].append({"role": "user", "content": "또 질문"})
    path.write_text(json.dumps(bad, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="user, assistant"):
        load_examples(path)


REFUSAL = "학교 홈페이지 안내에서 찾지 못했습니다."


def preference(number: int, pair_type: str, group: str) -> dict:
    """4회차 선호 쌍 한 줄(trainset pairs 결과 모양)."""
    user, assistant = example(number, "fact", group)["messages"]
    return {"id": f"gana-{number:03d}", "prompt": [user], "chosen": [assistant],
            "rejected": [{"role": "assistant", "content": REFUSAL}],
            "meta": {"pair": pair_type, "kind": "fact", "group_id": group}}


def test_load_pairs_and_convert_to_preference_format(tmp_path):
    path = tmp_path / "pairs.jsonl"
    rows = [preference(1, "over_refusal", "공지:1"), preference(2, "fabrication", "공지:2")]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    pairs = load_pairs(path)
    assert [pair["id"] for pair in pairs] == ["gana-001", "gana-002"]
    assert to_preference(pairs[0]) == {"prompt": rows[0]["prompt"], "chosen": rows[0]["chosen"], "rejected": rows[0]["rejected"]}


@pytest.mark.parametrize("change, message", [
    (lambda row: row["rejected"].append({"role": "user", "content": "또 질문"}), "user, 두 답은 assistant"),
    (lambda row: row.update(prompt=[{"role": "assistant", "content": "답"}]), "user, 두 답은 assistant"),
    (lambda row: row.update(rejected=row["chosen"]), "선호 답과 비선호 답이 같다"),
])
def test_load_pairs_rejects_bad_lines(tmp_path, change, message):
    row = preference(1, "over_refusal", "공지:1")
    change(row)
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_pairs(path)


def test_split_pairs_by_pair_type_ratio():
    types = ["over_refusal"] * 10 + ["fabrication"] * 6 + ["wrong_value"] * 3 + ["refusal_preamble"] * 1
    rows = [preference(number, pair_type, f"공지:{number}") for number, pair_type in enumerate(types, 1)]
    train, valid = split_examples(rows, valid_size=4, seed=42, key="pair")
    # 20쌍 중 4쌍을 쌍 종류 비율(2 · 1.2 · 0.6 · 0.2)대로: 과잉 거절 2 · 지어내기 1 · 남은 한 자리는 나머지가 큰 틀린 값
    assert sorted(row["meta"]["pair"] for row in valid) == ["fabrication", "over_refusal", "over_refusal", "wrong_value"]
    assert len(train) == 16 and split_examples(rows, valid_size=4, seed=42, key="pair") == (train, valid)
