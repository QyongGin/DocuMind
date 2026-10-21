"""묶음 고르기: 데이터셋용 색인에 올라간 학습 몫 문서에서 예시 종류별 개수만큼 질문을 만들 청크를 고른다(설계 §2).

- 묶음은 주제·형식별로 고르게 돌려 고르고, 한 묶음에서 예시 하나만 만든다.
- 종류에 맞는 청크가 없는 묶음(표 값인데 표가 없음 등)은 건너뛰고 다음 묶음을 본다.
- 사용자 범주와 말투는 예시 순서대로 돌린다. 초안 모델이 그 문서를 물을 만하지 않다고 보면 다른 범주를 고를 수 있다.
"""

from __future__ import annotations

import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Kind:
    """예시 종류. answerable은 근거에 답이 있어야 하는 종류, chunks는 질문을 만들 청크 수(엉뚱한 근거는 0)."""
    name: str
    label: str
    answerable: bool
    chunks: int
    table: bool = False


KINDS = {kind.name: kind for kind in (
    Kind("fact", "답 · 사실 하나", True, 1),
    Kind("procedure", "답 · 절차·방법", True, 1),
    Kind("table", "답 · 표 값", True, 1, table=True),
    Kind("multi", "답 · 여러 근거 합치기", True, 2),
    Kind("partial", "일부만 있음", True, 1),
    Kind("refuse_guide", "거절 + 확인처", False, 1),
    Kind("refuse_offtopic", "거절 · 엉뚱한 근거", False, 0),
)}
# 1회차 200개(설계 §2): 답 120 · 일부만 있음 20 · 거절 + 확인처 40 · 엉뚱한 근거 20
ROUND1 = {"fact": 35, "procedure": 30, "table": 35, "multi": 20, "partial": 20, "refuse_guide": 40, "refuse_offtopic": 20}
USERS = ("재학생", "예비 입학생·지원자", "교직원", "외국인", "업체")
STYLES = ("짧은 구어체", "정중체", "상황 설명형", "쉬운 한국어")
MIN_CHUNK_CHARS = 200
TABLE_MIN_ROWS = 3


def scale(quotas: dict[str, int], total: int) -> dict[str, int]:
    """비율을 지켜 total개로 줄이거나 늘린다(최대 나머지 방식). 첫 묶음 40개면 1회차 200개의 1/5."""
    whole = sum(quotas.values())
    exact = {name: count * total / whole for name, count in quotas.items()}
    result = {name: int(value) for name, value in exact.items()}
    by_remainder = sorted(quotas, key=lambda name: (exact[name] - result[name], quotas[name]), reverse=True)
    for name in by_remainder[: total - sum(result.values())]:
        result[name] += 1
    return result


def dataset_documents(con: sqlite3.Connection) -> list[dict]:
    """데이터셋용 색인에 올라간 문서(대장 uploads 표의 대상 dataset)와 대장 정보."""
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT l.doc_id, u.document_id, l.group_id, l.topic, l.format, l.title FROM uploads u "
        "JOIN ledger l USING(doc_id) WHERE u.target = 'dataset' AND u.status IN ('ready', 'exists') "
        "AND u.document_id IS NOT NULL ORDER BY l.doc_id")
    return [dict(row) for row in rows]


def is_table_chunk(text: str) -> bool:
    """마크다운 표 줄('|'로 시작)이 몇 줄 이상 있는 청크."""
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("|")) >= TABLE_MIN_ROWS


def pick_chunks(kind: Kind, chunks: list[dict], rng: random.Random) -> list[dict] | None:
    """종류에 맞는 청크를 고른다. 여러 근거는 같은 문서의 이웃한 청크 둘. 맞는 청크가 없으면 None."""
    usable = [chunk for chunk in chunks if len(str(chunk.get("content") or "").strip()) >= MIN_CHUNK_CHARS]
    if kind.table:
        usable = [chunk for chunk in usable if is_table_chunk(str(chunk["content"]))]
    if kind.chunks == 2:
        ordered = sorted(usable, key=lambda chunk: int(chunk.get("chunk_index") or 0))
        pairs = [(first, second) for first, second in zip(ordered, ordered[1:])
                 if int(second.get("chunk_index") or 0) - int(first.get("chunk_index") or 0) == 1]
        return list(rng.choice(pairs)) if pairs else None
    return [rng.choice(usable)] if usable else None


def ordered_groups(documents: list[dict], rng: random.Random, skip: set[str] = frozenset()) -> list[list[dict]]:
    """묶음을 주제·형식 칸마다 섞은 뒤 칸을 돌아가며 하나씩 꺼낸 순서로 늘어놓는다(고르게 뽑기)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for document in documents:
        groups[document.get("group_id") or document["doc_id"]].append(document)
    strata: dict[tuple, list[str]] = defaultdict(list)
    for group_id, members in sorted(groups.items()):
        if group_id in skip:
            continue
        strata[(members[0].get("topic") or "", members[0].get("format") or "")].append(group_id)
    for group_ids in strata.values():
        rng.shuffle(group_ids)
    keys = sorted(strata)
    rng.shuffle(keys)
    ordered = []
    while any(strata[key] for key in keys):
        for key in keys:
            if strata[key]:
                ordered.append(groups[strata[key].pop()])
    return ordered


def plan(documents: list[dict], quotas: dict[str, int], fetch_chunks: Callable[[int], list[dict]], batch: str,
         seed: int, skip_groups: set[str] = frozenset()) -> list[dict]:
    """예시 종류별 개수만큼 묶음과 청크를 고른다. fetch_chunks(문서 번호)는 그 문서의 청크 목록을 돌려준다."""
    rng = random.Random(seed)
    sequence = [name for name, count in quotas.items() for _ in range(count)]
    rng.shuffle(sequence)
    groups = ordered_groups(documents, rng, set(skip_groups))
    cache: dict[int, list[dict]] = {}
    used: set[str] = set()
    items = []
    for number, name in enumerate(sequence, 1):
        kind = KINDS[name]
        item = {"id": f"{batch}-{number:04d}", "batch": batch, "kind": name, "user": USERS[(number - 1) % len(USERS)],
                "style": STYLES[(number - 1) % len(STYLES)], "seed": seed, "group_id": None, "ledger_id": None,
                "document_id": None, "title": None, "topic": None, "format": None, "chunks": []}
        if kind.chunks == 0:
            items.append(item)
            continue
        for members in groups:
            group_id = members[0].get("group_id") or members[0]["doc_id"]
            if group_id in used:
                continue
            for document in rng.sample(members, len(members)):
                if document["document_id"] not in cache:
                    cache[document["document_id"]] = fetch_chunks(document["document_id"])
                chunks = pick_chunks(kind, cache[document["document_id"]], rng)
                if chunks:
                    used.add(group_id)
                    item.update(group_id=group_id, ledger_id=document["doc_id"], document_id=document["document_id"],
                                title=document.get("title"), topic=document.get("topic"), format=document.get("format"),
                                chunks=[{"id": chunk.get("id"), "chunk_index": chunk.get("chunk_index"),
                                         "content": chunk["content"]} for chunk in chunks])
                    break
            if item["chunks"]:
                break
        if item["chunks"]:
            items.append(item)
    return items
