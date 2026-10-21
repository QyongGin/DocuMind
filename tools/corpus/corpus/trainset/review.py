"""사람 표본 화면과 판정 기록 합치기(ADR-0037: 첫 묶음에서 Claude 판정과 나란히 30개).

- 표본: Claude가 판정한 예시에서 종류를 고르게, 통과·탈락을 모두 담아 고른다.
- 화면: HTML 파일 하나(서버·인터넷 없음). 사람이 고른 뒤에야 Claude 판정이 보인다(판정에 끌리지 않게).
- 합치기: 화면이 내려받은 JSONL을 human.jsonl로 남기고 Claude와 어긋난 수를 센다. 2개 이상이면 판정 지침을 고친다.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

from . import checks
from .plan import KINDS

TEMPLATE = Path(__file__).with_name("review_template.html")
MAX_FAIL_SHARE = 0.5  # 표본의 절반까지는 Claude 탈락 예시로 채운다(탈락 쪽 오류도 보이게)


def sample(records: list[dict], size: int, seed: int) -> list[dict]:
    """판정된 예시에서 표본을 고른다. 탈락을 먼저(표본의 절반까지), 나머지는 종류를 돌아가며 통과에서."""
    rng = random.Random(seed)
    judged = [record for record in records if record.get("verdict") in ("통과", "탈락")]
    failed = [record for record in judged if record["verdict"] == "탈락"]
    rng.shuffle(failed)
    chosen = failed[: int(size * MAX_FAIL_SHARE)]
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for record in judged:
        if record["verdict"] == "통과":
            by_kind[record["kind"]].append(record)
    for members in by_kind.values():
        rng.shuffle(members)
    kinds = sorted(by_kind)
    while len(chosen) < size and any(by_kind[kind] for kind in kinds):
        for kind in kinds:
            if by_kind[kind] and len(chosen) < size:
                chosen.append(by_kind[kind].pop())
    for record in failed:  # 통과가 모자라면 남은 탈락으로 채운다
        if len(chosen) >= size:
            break
        if record not in chosen:
            chosen.append(record)
    order = {record["id"]: number for number, record in enumerate(records)}
    return sorted(chosen, key=lambda record: order[record["id"]])


def page(records: list[dict], batch: str) -> str:
    """표본 화면 HTML. 근거 블록은 목표 답이 쓴 번호만 펼치고, 목표 답의 값을 근거에서 칠한다."""
    examples = []
    for record in records:
        target = record.get("target_ga") or ""
        cited = {int(number) for number in checks.CITE.findall(target)}
        blocks = checks.evidence_blocks(record.get("prompt") or "")
        # 목표 답의 전화번호·숫자를 근거에서 칠해 찾기 쉽게 한다(출처 번호 숫자는 빼고)
        raw_values = checks.PHONE.findall(target)
        raw_values += [match.group(0) for match in re.finditer(r"\d[\d,.]*\s*[가-힣%]?", checks.CITE.sub("", target))]
        examples.append({
            "id": record["id"], "kind": KINDS[record["kind"]].label, "user": record.get("user_actual") or record["user"],
            "question": record.get("question") or "", "target": target,
            "notes": (record.get("result") or {}).get("ga", {}).get("judge_notes") or [],
            "blocks": [{"n": number, "text": text.strip(), "cited": number in cited} for number, text in sorted(blocks.items())],
            "values": sorted({value.strip() for value in raw_values if value.strip()}, key=len, reverse=True),
            "claude": {"verdict": record.get("verdict"), "category": record.get("category") or "",
                       "reason": record.get("reason") or ""},
        })
    data = json.dumps({"batch": batch, "examples": examples}, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)


def read_record(path: Path) -> dict[str, dict]:
    """화면이 내려받은 판정 기록(JSONL): {예시 번호: {human, memo}}."""
    records = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry.get("human") not in ("통과", "탈락"):
                raise ValueError(f"판정 값이 틀림: {entry}")
            records[entry["id"]] = {"human": entry["human"], "memo": entry.get("memo") or ""}
    return records


def agreement(records: list[dict], human: dict[str, dict]) -> dict:
    """사람과 Claude 판정이 어긋난 예시. 어긋남 2개 이상이면 판정 지침을 고치고 새 30개를 본다(ADR-0037)."""
    seen = [record for record in records if record["id"] in human]
    differ = [{"id": record["id"], "claude": record.get("verdict"), "human": human[record["id"]]["human"],
               "memo": human[record["id"]]["memo"], "reason": record.get("reason")}
              for record in seen if record.get("verdict") != human[record["id"]]["human"]]
    false_pass = sum(1 for entry in differ if entry["claude"] == "통과")
    return {"seen": len(seen), "differ": len(differ), "claude_pass_human_fail": false_pass,
            "claude_fail_human_pass": len(differ) - false_pass, "next": "나머지는 Claude 판정만" if len(differ) <= 1
            else "판정 지침을 고치고 새 30개", "examples": differ}
