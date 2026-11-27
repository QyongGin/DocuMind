"""정답 청크의 자리(#275): 예시마다 실제 검색인지 청크를 지정했는지, 정답 청크가 근거의 몇 번째 블록이 됐는지, 근거에 못
들었으면 어느 단계에서 밀렸는지.

정답 청크는 질문을 만든 청크(계획의 chunks)다. 순위는 AI 서버가 평가용 기록에 남긴 후보별 단계 순위(eval_trace.retrieval)를
그대로 옮긴다 — 도구가 검색을 다시 흉내 내지 않는다. 실제 검색과 지정의 비율은 단계 C에서 정하므로 여기서는 몫(share)을
설정으로만 받는다.
"""

from __future__ import annotations

import random
from collections import Counter

REAL, PINNED = "검색", "지정"
NOT_CANDIDATE, FUSION, RERANK = "검색 후보에 없음", "순위 융합에서 밀림", "재순위에서 밀림"
REASONS = (NOT_CANDIDATE, FUSION, RERANK)
RANK_KEYS = ("retrieval_methods", "vector_rank", "bm25_rank", "table_fact_rank", "fused_rank", "rerank_rank",
             "final_rank", "block")


def gold_chunks(record: dict) -> list[dict]:
    """질문을 만든 청크 중 청크 id가 있는 것(청크 id는 AI 서버의 원문 청크 id)."""
    return [chunk for chunk in record.get("chunks") or [] if chunk.get("id")]


def _rng(record: dict, seed: int) -> random.Random:
    # 예시 번호로 굴린다: 이어서 돌리거나 순서가 바뀌어도 같은 예시는 같은 값이 나온다
    return random.Random(f"{seed}:{record['id']}")


def pick_mode(record: dict, pinned_share: float, seed: int, answerable: bool) -> str:
    """실제 검색(REAL)인지 정답 청크를 지정(PINNED)할지. 지정은 답이 있는 종류이고 정답 청크가 있을 때만 한다
    (거절 + 확인처는 답이 든 청크를 빼서 만들고, 엉뚱한 근거는 청크가 없다)."""
    if not answerable or not gold_chunks(record) or pinned_share <= 0:
        return REAL
    return PINNED if _rng(record, seed).random() < pinned_share else REAL


def pinned_chunks(record: dict, top_k: int, seed: int) -> list[dict]:
    """지정 청크 요청 칸: 정답 청크마다 1~top_k 중 겹치지 않는 자리를 고르게 뽑는다(1차 학습은 정답이 늘 첫째였다).
    top_k는 서버 실행 설정의 근거 수다."""
    chunks = gold_chunks(record)
    rng = _rng(record, seed)
    rng.random()  # pick_mode가 쓴 첫 값을 건너뛴다(자리가 지정 여부와 엮이지 않게)
    ranks = rng.sample(range(1, top_k + 1), len(chunks))
    return [{"chunk_id": chunk["id"], "rank": rank} for chunk, rank in zip(chunks, ranks)]


def _same_table_block(chunk: dict, document_id, attached: dict) -> int | None:
    """같은 문서의 같은 표 번호를 가진 표 블록 번호. 청크의 표 번호를 모르면(옛 계획) None."""
    numbers = set(chunk.get("table_numbers") or [])
    if not numbers:
        return None
    for block in attached.get("table_blocks") or []:
        if (block.get("table_block") and str(block.get("document_id")) == str(document_id)
                and numbers & set(block.get("table_numbers") or [])):
            return block.get("block")
    return None


def chunk_status(chunk: dict, document_id, attached: dict) -> dict:
    """정답 청크 하나의 단계별 순위와 근거에 든 자리. 못 들었으면 밀린 단계(reason)와 같은 표의 다른 조각이 근거에
    들었는지(same_table, 청크의 표 번호를 모르면 None)를 남긴다.

    표 블록이 켜지면 같은 표의 뒤 순위 청크는 앞 블록에 합쳐져 자기 블록이 없다(dropped_chunk_ids). 그 표가 근거에 있으므로
    든 것으로 보고 합쳐진 블록 번호를 쓴다(merged)."""
    ranks = {str(entry.get("chunk_id")): entry for entry in attached.get("retrieval") or []}
    entry = ranks.get(str(chunk["id"])) or {}
    status = {"chunk_id": chunk["id"], **{key: entry.get(key) for key in RANK_KEYS}}
    sibling = _same_table_block(chunk, document_id, attached)
    if entry.get("block"):
        return {**status, "in_evidence": True}
    if str(chunk["id"]) in {str(chunk_id) for chunk_id in attached.get("dropped_chunk_ids") or []}:
        return {**status, "in_evidence": True, "merged": True, "block": sibling}
    if entry.get("fused_rank") is None:
        reason = NOT_CANDIDATE
    elif entry.get("rerank_rank") is not None and entry["fused_rank"] <= (attached.get("considered") or 0):
        reason = RERANK  # 순위 융합 순서였으면 근거에 들었다
    else:
        reason = FUSION
    has_numbers = bool(chunk.get("table_numbers"))
    return {**status, "in_evidence": False, "reason": reason, "same_table": (sibling is not None) if has_numbers else None}


def gold_record(record: dict, attached: dict, mode: str) -> dict:
    """예시의 정답 청크 기록: 실제 검색/지정, 청크마다 chunk_status, 모두 근거에 들었는지."""
    chunks = [chunk_status(chunk, record.get("document_id"), attached) for chunk in gold_chunks(record)]
    return {"mode": mode, "chunks": chunks, "in_evidence": bool(chunks) and all(chunk["in_evidence"] for chunk in chunks),
            "pinned": attached.get("pinned")}


def count_reasons(records: list[dict], answerable) -> dict:
    """정답 청크가 근거에 못 든 예시의 이유별 수. answerable(kind) → 답이 있는 종류인가.

    실제 검색이고 계획이 답 있는 종류인 예시만 센다(거절 + 확인처는 답이 든 청크를 일부러 뺀다). 이유는 못 든 정답 청크마다
    센다(여러 근거 합치기는 청크가 둘). 같은 표 조각은 못 든 청크 중 같은 표의 다른 조각이 근거에 든 수다."""
    counted = [record for record in records if (record.get("gold") or {}).get("mode") == REAL
               and answerable(record.get("kind_planned") or record["kind"]) and (record["gold"].get("chunks"))]
    missing = [chunk for record in counted for chunk in record["gold"]["chunks"] if not chunk["in_evidence"]]
    pinned = [record for record in records if (record.get("gold") or {}).get("mode") == PINNED]
    return {
        "실제 검색 예시": len(counted),
        "정답 청크가 근거에 듦": sum(record["gold"]["in_evidence"] for record in counted),
        "정답 청크가 근거에 못 듦": sum(not record["gold"]["in_evidence"] for record in counted),
        "못 든 청크의 이유": {reason: sum(chunk["reason"] == reason for chunk in missing) for reason in REASONS},
        "못 든 청크 중 같은 표의 다른 조각이 근거에 듦": {
            "예": sum(chunk["same_table"] is True for chunk in missing),
            "아니오": sum(chunk["same_table"] is False for chunk in missing),
            "표 번호 모름": sum(chunk["same_table"] is None for chunk in missing)},
        "거절로 둔 예시": sum(bool(record["gold"].get("refusal_target")) for record in counted),
        "지정 예시": len(pinned),
        "지정 예시의 정답 블록": dict(sorted(Counter(chunk.get("block") for record in pinned
                                             for chunk in record["gold"]["chunks"]).items(),
                                     key=lambda item: (item[0] is None, item[0] or 0))),
    }
