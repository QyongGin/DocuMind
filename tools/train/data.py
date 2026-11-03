"""학습 예시를 TRL이 받는 대화형 프롬프트·답 형식으로 바꾸고 검증 몫을 고른다(이슈 #223).

학습 파일 한 줄은 `{"id", "messages": [user, assistant], "meta": {"kind", "group_id", ...}}`이다. user는 운영 프롬프트
전체(AI 서버 `_build_rag_prompt`가 만든 글), assistant는 목표 답이다. 무거운 학습 라이브러리 없이 돌아가 CI에서 시험한다.
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def load_examples(path: str | Path) -> list[dict]:
    """학습 파일(JSONL)을 읽는다. 대화가 user 한 번, assistant 한 번이 아니면 멈춘다."""
    examples = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        example = json.loads(line)
        roles = [message["role"] for message in example["messages"]]
        if roles != ["user", "assistant"]:
            raise ValueError(f"{number}번째 줄: 대화는 user, assistant 한 번씩이어야 한다(지금 {roles})")
        examples.append(example)
    return examples


def to_prompt_completion(example: dict) -> dict:
    """대화형 프롬프트·답 형식. TRL은 이 형식이면 채팅 틀을 씌우고 답(completion) 부분만 학습한다."""
    user, assistant = example["messages"]
    return {
        "prompt": [{"role": "user", "content": user["content"]}],
        "completion": [{"role": "assistant", "content": assistant["content"]}],
    }


def split_examples(examples: list[dict], valid_size: int, seed: int) -> tuple[list[dict], list[dict]]:
    """검증 몫을 예시 종류 비율대로 고른다. 같은 문서 묶음이 학습 몫과 검증 몫에 갈라지지 않게 혼자인 묶음에서 먼저 고른다.

    범위 밖 거절처럼 한 종류가 모두 같은 묶음이면(문서와 상관없는 묶음) 그 종류 안에서 그냥 고른다.
    같은 입력과 seed면 늘 같은 결과다.
    """
    if not 0 <= valid_size < len(examples):
        raise ValueError(f"검증 몫 {valid_size}개는 0 이상, 예시 수({len(examples)}) 미만이어야 한다")
    group_size = Counter(example["meta"]["group_id"] for example in examples)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for example in examples:
        by_kind[example["meta"]["kind"]].append(example)

    quotas = _quotas({kind: len(items) for kind, items in by_kind.items()}, valid_size)
    rng = random.Random(seed)
    valid_ids: set[str] = set()
    for kind in sorted(by_kind):
        items = sorted(by_kind[kind], key=lambda example: example["id"])
        singles = [example for example in items if group_size[example["meta"]["group_id"]] == 1]
        pool = singles if len(singles) >= quotas[kind] else items
        valid_ids.update(example["id"] for example in rng.sample(pool, quotas[kind]))
    train = [example for example in examples if example["id"] not in valid_ids]
    valid = [example for example in examples if example["id"] in valid_ids]
    return train, valid


def _quotas(counts: dict[str, int], total: int) -> dict[str, int]:
    """종류별 개수 비율로 total을 나눈다(큰 나머지 순). 합은 늘 total이다."""
    whole = sum(counts.values())
    exact = {kind: total * count / whole for kind, count in counts.items()}
    quotas = {kind: int(value) for kind, value in exact.items()}
    left = total - sum(quotas.values())
    for kind in sorted(exact, key=lambda kind: (-(exact[kind] - quotas[kind]), kind))[:left]:
        quotas[kind] += 1
    return quotas
