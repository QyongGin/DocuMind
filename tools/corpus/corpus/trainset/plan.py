"""묶음 고르기: 데이터셋용 색인에 올라간 학습 몫 문서에서 예시 종류별 개수만큼 질문을 만들 청크를 고른다(설계 §2).

- 묶음은 주제·형식별로 고르게 돌려 고르고, 한 묶음에서 예시 하나만 만든다.
- 종류에 맞는 청크가 없는 묶음(표 값인데 표가 없음 등)은 건너뛰고 다음 묶음을 본다.
- 사용자 범주와 말투는 예시 순서대로 돌린다. 초안 모델이 그 문서를 물을 만하지 않다고 보면 다른 범주를 고를 수 있다.
- 여러 문서에 되풀이되는 줄(개인정보 수집 동의 같은 상투문)은 빼고 청크 길이를 재고, 초안 모델에도 뺀 글을 준다.
  2026-10-21 첫 시험 묶음에서 질문 34개 중 5개가 상투문에서 나왔다. 낱말 조건문이 아니라 '몇 문서에 나오나'로 가른다.
"""

from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


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
# 1회차 200개: 답 140 · 일부만 있음 20 · 거절 + 확인처 30 · 엉뚱한 근거 10 — 거절 20%(ADR-0043, 2026-10-26).
# 처음 설계(거절 30%)를 평가셋 답없음 비율(14.7%, 개발셋 본 18.8%)과 학습 전 A.X 과잉 거절(7.4%)을 보고 낮췄다. 표 값은 답의 29%
ROUND1 = {"fact": 40, "procedure": 35, "table": 40, "multi": 25, "partial": 20, "refuse_guide": 30, "refuse_offtopic": 10}
USERS = ("재학생", "예비 입학생·지원자", "교직원", "외국인", "업체")
# 말투(ADR-0044): 실제 사용자처럼 짧은 구어·검색어형을 더했다. 운영 질문 기록이 없어 비율은 고르게 돌린다
STYLES = ("짧은 구어", "검색어형", "정중체", "상황 설명형", "쉬운 한국어")
# 말 바꾸기 표시(4회차 설계 변경, 2026-11-05): 질문의 핵심 낱말을 글에 적힌 말 대신 묻는 사람이 평소 쓰는 말로 쓰게 한다.
# 개발셋에서 학습한 모델이 근거를 받고도 거절한 문항은 대부분 문서와 다른 말로 물은 질문이었다
REWORD = "다른 말"
MIN_CHUNK_CHARS = 200
TABLE_MIN_ROWS = 3
BOILERPLATE_MIN_DOCS = 5  # 이만큼 넘는 문서에 같은 줄이 있으면 상투문
BOILERPLATE_MIN_CHARS = 20  # 이보다 짧은 줄(연락처 한 줄·번호 등)은 상투문으로 세지 않는다


def scale(quotas: dict[str, int], total: int) -> dict[str, int]:
    """비율을 지켜 total개로 줄이거나 늘린다(최대 나머지 방식). 첫 묶음 40개면 1회차 200개의 1/5."""
    whole = sum(quotas.values())
    exact = {name: count * total / whole for name, count in quotas.items()}
    result = {name: int(value) for name, value in exact.items()}
    by_remainder = sorted(quotas, key=lambda name: (exact[name] - result[name], quotas[name]), reverse=True)
    for name in by_remainder[: total - sum(result.values())]:
        result[name] += 1
    return result


def parse_kinds(text: str) -> dict[str, int]:
    """'fact=10,table=40'처럼 쓴 종류별 개수(비율로 쓴다, 합이 100이면 퍼센트). 적지 않은 종류는 0개다.
    4회차는 표 근거와 답 없는 질문의 비중을 1회차 비율과 다르게 둔다(ADR-0053)."""
    counts = {}
    for item in text.split(","):
        if not item.strip():
            continue
        name, _, number = item.partition("=")
        name = name.strip()
        if name not in KINDS:
            raise ValueError(f"없는 예시 종류 {name!r} — {', '.join(KINDS)} 중에서 쓴다")
        if not number.strip().isdigit():
            raise ValueError(f"{name}의 개수 {number!r}는 0 이상의 정수여야 한다")
        counts[name] = int(number)
    if not sum(counts.values()):
        raise ValueError("종류별 개수의 합이 0이다")
    return counts


MIN_YIELD = 0.2  # 수율을 모르거나 아주 낮을 때 쓰는 바닥값(계획 5개에 통과 1개)


def fill_quotas(target: dict[str, int], passed: dict[str, int], planned: dict[str, int], planned_passed: dict[str, int],
                total: int) -> dict[str, int]:
    """다음 묶음의 종류별 개수: 1회차 목표(target)에서 이미 통과한 수(passed, 받은 근거로 정한 종류)를 빼고 모자란 종류만
    배정한다(ADR-0041 결정 6). 계획한 종류가 판정 통과로 이어진 비율(수율 = planned_passed / planned)이 낮은 종류는 그만큼
    더 계획한다. 모자란 종류가 없으면 빈 사전."""
    weights = {}
    for name, goal in target.items():
        lack = max(0, goal - passed.get(name, 0))
        if lack:
            rate = planned_passed.get(name, 0) / planned[name] if planned.get(name) else MIN_YIELD
            weights[name] = lack / max(rate, MIN_YIELD)
    return {name: count for name, count in scale(weights, total).items() if count} if weights else {}


def dataset_documents(con: sqlite3.Connection) -> list[dict]:
    """데이터셋용 색인에 올라간 문서(대장 uploads 표의 대상 dataset)와 대장 정보."""
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT l.doc_id, u.document_id, l.group_id, l.topic, l.format, l.title FROM uploads u "
        "JOIN ledger l USING(doc_id) WHERE u.target = 'dataset' AND u.status IN ('ready', 'exists') "
        "AND u.document_id IS NOT NULL ORDER BY l.doc_id")
    return [dict(row) for row in rows]


def document_family(con: sqlite3.Connection) -> dict[str, tuple[str, str | None]]:
    """문서마다 (게시글 번호, 묶음 번호). 첨부는 부모 게시글 번호를 쓴다. 답없음 예시의 확인처를 고를 근거 블록
    (재료 문서·같은 게시글·같은 묶음)을 가릴 때 쓴다(ADR-0048 결정 2)."""
    return {row[0]: (row[1] or row[0], row[2]) for row in con.execute("SELECT doc_id, parent_id, group_id FROM ledger")}


def _line_key(line: str) -> str:
    return " ".join(line.split())


def boilerplate_lines(chunks_by_document: dict[int, list[dict]], min_docs: int = BOILERPLATE_MIN_DOCS) -> set[str]:
    """여러 문서(min_docs 이상)에 되풀이되는 줄. 같은 문서 안에서 되풀이되는 것은 한 번으로 센다."""
    documents_with: dict[str, int] = defaultdict(int)
    for chunks in chunks_by_document.values():
        lines = {_line_key(line) for chunk in chunks for line in str(chunk.get("content") or "").splitlines()}
        for line in lines:
            # 표 줄(머리줄이 표의 뜻을 정함)과 제목 줄(맥락)은 되풀이돼도 남긴다 — 문장 줄만 상투문으로 센다
            if len(line) >= BOILERPLATE_MIN_CHARS and not line.startswith(("|", "#")):
                documents_with[line] += 1
    return {line for line, count in documents_with.items() if count >= min_docs}


def draft_text(text: str, boilerplate: set[str]) -> str:
    """상투문 줄을 뺀 글. 초안 모델에 주고, 청크 길이도 이것으로 잰다."""
    return "\n".join(line for line in str(text).splitlines() if _line_key(line) not in boilerplate).strip()


def is_table_chunk(text: str) -> bool:
    """마크다운 표 줄('|'로 시작)이 몇 줄 이상 있는 청크."""
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("|")) >= TABLE_MIN_ROWS


def pick_chunks(kind: Kind, chunks: list[dict], rng: random.Random, boilerplate: set[str] = frozenset()) -> list[dict] | None:
    """종류에 맞는 청크를 고른다. 여러 근거는 같은 문서의 이웃한 청크 둘. 맞는 청크가 없으면 None.
    길이는 상투문을 뺀 글로 잰다."""
    usable = [chunk for chunk in chunks if len(draft_text(chunk.get("content") or "", boilerplate)) >= MIN_CHUNK_CHARS]
    if kind.table:
        usable = [chunk for chunk in usable if is_table_chunk(draft_text(chunk["content"], boilerplate))]
    if kind.chunks == 2:
        ordered = sorted(usable, key=lambda chunk: int(chunk.get("chunk_index") or 0))
        pairs = [(first, second) for first, second in zip(ordered, ordered[1:])
                 if int(second.get("chunk_index") or 0) - int(first.get("chunk_index") or 0) == 1]
        return list(rng.choice(pairs)) if pairs else None
    return [rng.choice(usable)] if usable else None


def trained_groups(paths: Iterable[Path]) -> set[str]:
    """학습 파일(지도 학습 round-*.jsonl, 선호 쌍 pairs.jsonl)의 예시가 쓴 문서 묶음(meta.group_id).

    학습한 모델의 실패를 재는 질문은 그 모델이 학습에서 본 문서를 피한다(5회차, ADR-0055). 계획에만 쓰이고 학습 파일에
    들지 않은 묶음은 모델이 본 적이 없으니 다시 고를 수 있다. 엉뚱한 근거 종류처럼 문서가 없는 예시는 묶음이 없다.
    """
    groups = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                group_id = (json.loads(line).get("meta") or {}).get("group_id")
                if group_id:
                    groups.add(group_id)
    return groups


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
         seed: int, skip_groups: set[str] = frozenset(), boilerplate: set[str] = frozenset(),
         reword_share: float = 0.0) -> list[dict]:
    """예시 종류별 개수만큼 묶음과 청크를 고른다. fetch_chunks(문서 번호)는 그 문서의 청크 목록을 돌려준다.
    boilerplate는 상투문 줄(boilerplate_lines). reword_share만큼의 글 있는 예시에 말 바꾸기 표시(wording)를 단다."""
    rng = random.Random(seed)
    # 말 바꾸기 고르기는 따로 굴려 묶음·청크 고르기 순서를 바꾸지 않는다(0이면 예전 계획과 같다)
    reword_rng = random.Random(seed + 1)
    sequence = [name for name, count in quotas.items() for _ in range(count)]
    rng.shuffle(sequence)
    groups = ordered_groups(documents, rng, set(skip_groups))
    cache: dict[int, list[dict]] = {}
    used: set[str] = set()
    items = []
    for number, name in enumerate(sequence, 1):
        kind = KINDS[name]
        # 사용자와 말투 수가 같아도 짝이 고정되지 않게, 말투는 사용자를 한 바퀴 돌 때마다 하나씩 넘긴다
        item = {"id": f"{batch}-{number:04d}", "batch": batch, "kind": name, "user": USERS[(number - 1) % len(USERS)],
                "style": STYLES[((number - 1) // len(USERS)) % len(STYLES)], "seed": seed, "group_id": None, "ledger_id": None,
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
                chunks = pick_chunks(kind, cache[document["document_id"]], rng, boilerplate)
                if chunks:
                    used.add(group_id)
                    item.update(group_id=group_id, ledger_id=document["doc_id"], document_id=document["document_id"],
                                title=document.get("title"), topic=document.get("topic"), format=document.get("format"),
                                chunks=[{"id": chunk.get("id"), "chunk_index": chunk.get("chunk_index"),
                                         "content": chunk["content"],
                                         "draft_text": draft_text(chunk["content"], boilerplate)} for chunk in chunks])
                    break
            if item["chunks"]:
                break
        if item["chunks"]:
            if reword_share and reword_rng.random() < reword_share:
                item["wording"] = REWORD
            items.append(item)
    return items
