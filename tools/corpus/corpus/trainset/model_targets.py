"""목표 답이 떨어진 문항은 학습한 모델이 낸 답을 목표 답 후보로 쓴다(ADR-0056).

목표 답(Gemma)이 답 탓으로 떨어진 문항은 Gemma가 어려워하는 문항이라 다시 만들어도 같은 실수를 한다(5회차 시험 묶음).
그 문항에서 학습한 모델이 이미 낸 답(probe)을 하나씩 목표 답 자리에 넣어, 목표 답과 같은 자동 검사와 같은 Claude 판정을
거친다. 둘 다 통과한 답 중 번호가 가장 앞선 답을 그 문항의 목표 답으로 올린다. Claude는 판정만 하고 글은 쓰지 않는다
(ADR-0010·0040). 올린 뒤에는 지금 흐름 그대로 나머지 답을 새 목표 답과 비교해 판정하고(judge-probes) 쌍을 만든다(pairs).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import checks, judge, pipeline

# 목표 답과 상관없이 질문·답 근거·받은 근거로 정해지는 검사. 이것으로 떨어진 문항은 질문이나 근거 탓이라 쓰지 않는다
QUESTION_CHECKS = frozenset({"질문", "지워진 정답", "왕복 검색", "답 근거 없음"})
QUESTION_CATEGORY = "질문 어색"


def verdict_step(model: str) -> str:
    """후보 답의 목표 답 판정을 둘 단계 이름(예: 'probes-ax40light-r4-q4km-as-target')."""
    return f"{pipeline.probe_step(model)}-as-target"


def answer_side_failure(record: dict) -> bool:
    """목표 답이 답 탓으로 떨어졌다: 자동 검사에서 답 쪽 이유로만 떨어졌거나, Claude 판정에서 '질문 어색'이 아닌 이유로 떨어졌다."""
    result = (record.get("result") or {}).get("ga")
    if not result or record.get("duplicate_of"):
        return False
    if not (record.get("keep") or {}).get("ga"):
        failed = {name for name, check in result["checks"].items() if not check["ok"]}
        return bool(failed) and not failed & QUESTION_CHECKS
    return pipeline.final_verdict(record) == "탈락" and record.get("category") != QUESTION_CATEGORY


def _targeted(batch_dir: Path) -> list[dict]:
    """대상 문항. 답을 올린 문항은 판정 '통과'와 다시 매긴 자동 검사 통과로 바뀌어 저절로 빠진다."""
    return [record for record in pipeline.merged(batch_dir) if answer_side_failure(record)]


def candidates(batch_dir: Path, model: str) -> list[dict]:
    """목표 답 후보: 대상 문항마다 그 모델의 답을 목표 답 자리에 넣은 예시. 번호는 '<문항>#<몇 번째 답>'이고, 목표 답과 같은
    자동 검사를 통과한 답만 담는다. 글이 같은 답은 앞 번호 하나만 둔다(같은 판정을 두 번 받지 않게)."""
    probes = pipeline.read(batch_dir, pipeline.probe_step(model))
    found = []
    for record in _targeted(batch_dir):
        seen: set[str] = set()
        for number, answer in enumerate((probes.get(record["id"]) or {}).get("ax_samples") or [], 1):
            if answer.strip() in seen:
                continue
            seen.add(answer.strip())
            candidate = {**record, "id": judge.answer_id(record["id"], number), "target_ga": answer}
            result = checks.check(candidate)
            if not result["drop"]:
                found.append({**candidate, "item": record["id"], "sample": number, "result": {"ga": result}})
    return found


def pending(batch_dir: Path, model: str) -> list[dict]:
    """아직 판정 전인 후보."""
    judged = pipeline.read(batch_dir, verdict_step(model))
    return [candidate for candidate in candidates(batch_dir, model) if candidate["id"] not in judged]


def promote(batch_dir: Path, model: str) -> Counter:
    """판정을 통과한 후보 중 번호가 가장 앞선 답을 그 문항의 목표 답으로 올린다. targets·judged에 줄을 더하고 자동 검사를 다시
    매긴다(pipeline.run_checks — 같은 입력이면 같은 결과). 돌려주는 것: 대상·올림·통과한 후보 없음·자동 검사를 통과한 후보
    없음·판정 전 문항 수."""
    targeted = [record["id"] for record in _targeted(batch_dir)]
    verdicts = pipeline.read(batch_dir, verdict_step(model))
    by_item: dict[str, list[dict]] = {}
    for candidate in candidates(batch_dir, model):
        by_item.setdefault(candidate["item"], []).append(candidate)
    counts, targets, judged = Counter(대상=len(targeted)), [], []
    for item in targeted:
        found = by_item.get(item, [])
        passed = [candidate for candidate in found if (verdicts.get(candidate["id"]) or {}).get("verdict") == "통과"]
        if passed:
            chosen = passed[0]  # 후보는 답 번호 순서다
            targets.append({"id": item, "target_ga": chosen["target_ga"],
                            "target_generation": {"from": model, "sample": chosen["sample"]}})
            judged.append({**verdicts[chosen["id"]], "id": item, "from": model, "sample": chosen["sample"]})
            counts["올림"] += 1
        elif not found:
            counts["자동 검사를 통과한 후보 없음"] += 1
        elif any(candidate["id"] not in verdicts for candidate in found):
            counts["판정 전"] += 1
        else:
            counts["통과한 후보 없음"] += 1
    if targets:
        pipeline.write(batch_dir, "targets", targets)
        pipeline.write(batch_dir, "judged", judged)
        pipeline.run_checks(batch_dir)
    return counts
