"""목표 답이 떨어진 문항은 학습한 모델이 낸 답을 목표 답 후보로 쓴다(ADR-0056).

목표 답(Gemma)이 답 탓으로 떨어진 문항은 Gemma가 어려워하는 문항이라 다시 만들어도 같은 실수를 한다(5회차 시험 묶음).
그 문항에서 학습한 모델이 이미 낸 답(probe)을 하나씩 목표 답 자리에 넣어, 목표 답과 같은 자동 검사와 같은 Claude 판정을
거친다. 둘 다 통과한 답 중 번호가 가장 앞선 답을 그 문항의 목표 답으로 올린다. Claude는 판정만 하고 글은 쓰지 않는다
(ADR-0010·0040). 올린 뒤에는 지금 흐름 그대로 나머지 답을 새 목표 답과 비교해 판정하고(judge-probes) 쌍을 만든다(pairs).

목표 답 후보는 다른 초안 모델이 다시 쓴 목표 답일 수도 있다(ADR-0057 결정 3, rewrite). 떨어진 목표 답과 같은 지시문으로
다시 쓰고 모델별 단계 파일에 두었다가, 같은 자동 검사와 같은 Claude 판정을 통과한 답만 목표 답으로 올린다. 다시 쓴 답으로
목표 답을 바로 덮지 않는 것은, 그 답도 떨어지면 문항에 처음 목표 답과 그 탈락 이유가 그대로 남게 하려는 것이다.
함수의 rewritten이 참이면 다시 쓴 목표 답을, 거짓이면 학습한 모델의 답을 후보로 본다.

후보의 종류는 그 후보 답으로 다시 정한다(ADR-0041). 문항의 종류는 떨어진 목표 답의 행동으로 정해진 값이라, 그대로 두면
거절해야 맞는 문항에서 거절한 후보가 판정자에게 '답' 종류로 보인다. 판정 기록에는 판정자에게 보인 종류를 남긴다.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable

from . import checks, judge, pipeline

# 목표 답과 상관없이 질문·답 근거·받은 근거로 정해지는 검사. 이것으로 떨어진 문항은 질문이나 근거 탓이라 쓰지 않는다
QUESTION_CHECKS = frozenset({"질문", "지워진 정답", "왕복 검색", "답 근거 없음"})
QUESTION_CATEGORY = "질문 어색"


def rewrite_step(model: str) -> str:
    """그 모델이 다시 쓴 목표 답을 둘 단계 이름(예: 'targets-gemma4-26b-a4b-it-qat')."""
    return f"targets-{pipeline.model_slug(model)}"


def verdict_step(model: str, rewritten: bool = False) -> str:
    """후보 답의 목표 답 판정을 둘 단계 이름(예: 'probes-ax40light-r4-q4km-as-target', 다시 쓴 목표 답이면
    'targets-gemma4-26b-a4b-it-qat-judged')."""
    return f"{rewrite_step(model)}-judged" if rewritten else f"{pipeline.probe_step(model)}-as-target"


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


def rewrite(batch_dir: Path, session, ollama_url: str, model: str, limit: int | None = None,
            log: Callable[[str], None] = print) -> Counter:
    """대상 문항의 목표 답을 그 모델로 다시 써서 rewrite_step 파일에 둔다. 지시문과 생성 설정은 처음 쓸 때와 같고
    (pipeline.draft_target), 떨어진 목표 답을 쓴 모델을 replaces에 남긴다. 이미 다시 쓴 문항은 건너뛰고 실패한 줄은 다음
    실행에서 다시 한다."""
    step = rewrite_step(model)
    done = {item for item, row in pipeline.read(batch_dir, step).items() if "error" not in row}
    todo = [record for record in _targeted(batch_dir) if record["id"] not in done]
    counts = Counter()
    for record in todo[:limit] if limit else todo:
        try:
            result = pipeline.draft_target(record, session, ollama_url, model, counts=counts)
            previous = record.get("target_generation") or {}
            result["target_generation"]["replaces"] = previous.get("from") or previous.get("model")
            counts["made"] += 1
        except (ValueError, KeyError, OSError) as error:
            result = {"id": record["id"], "error": str(error)}
            counts["error"] += 1
        pipeline.write(batch_dir, step, [result])
        log(f"목표 답 다시 쓰기 {record['id']}: {'실패 ' + result['error'] if 'error' in result else '만듦'}")
    return counts


def _answers(batch_dir: Path, model: str, rewritten: bool) -> dict[str, list[tuple[int, str, dict]]]:
    """문항별 후보 답: (번호, 글, 목표 답으로 올릴 때 남길 생성 기록). 학습한 모델의 답은 받은 순서대로 여럿이고,
    다시 쓴 목표 답은 문항마다 하나다."""
    if rewritten:
        return {item: [(1, row["target_ga"], row["target_generation"])]
                for item, row in pipeline.read(batch_dir, rewrite_step(model)).items() if row.get("target_ga")}
    return {item: [(number, answer, {"from": model, "sample": number})
                   for number, answer in enumerate(row.get("ax_samples") or [], 1)]
            for item, row in pipeline.read(batch_dir, pipeline.probe_step(model)).items()}


def candidates(batch_dir: Path, model: str, rewritten: bool = False) -> list[dict]:
    """목표 답 후보: 대상 문항마다 그 모델의 답을 목표 답 자리에 넣은 예시. 번호는 '<문항>#<몇 번째 답>'이고, 목표 답과 같은
    자동 검사를 통과한 답만 담는다. 글이 같은 답은 앞 번호 하나만 둔다(같은 판정을 두 번 받지 않게).
    종류(kind)는 후보 답으로 다시 정한 종류이고, 문항의 종류는 item_kind에 남긴다."""
    answers = _answers(batch_dir, model, rewritten)
    found = []
    for record in _targeted(batch_dir):
        seen: set[str] = set()
        for number, answer, generation in answers.get(record["id"], []):
            if answer.strip() in seen:
                continue
            seen.add(answer.strip())
            candidate = {**record, "id": judge.answer_id(record["id"], number), "target_ga": answer,
                         "target_generation": generation}
            result = checks.check(candidate)
            if not result["drop"]:
                found.append({**candidate, "kind": result["kind"], "item_kind": record["kind"], "item": record["id"],
                              "sample": number, "result": {"ga": result}})
    return found


def judged(candidate: dict, verdicts: dict[str, dict]) -> dict | None:
    """그 후보의 판정. 판정자에게 보인 종류가 지금 후보의 종류와 다른 판정은 쓰지 않는다(다시 판정한다).
    종류를 남기지 않은 지난 판정은 문항의 종류로 받은 판정이다."""
    verdict = verdicts.get(candidate["id"])
    if verdict and (verdict.get("judged_kind") or candidate["item_kind"]) == candidate["kind"]:
        return verdict
    return None


def pending(batch_dir: Path, model: str, rewritten: bool = False) -> list[dict]:
    """아직 판정 전인 후보."""
    verdicts = pipeline.read(batch_dir, verdict_step(model, rewritten))
    return [candidate for candidate in candidates(batch_dir, model, rewritten) if judged(candidate, verdicts) is None]


def record_verdicts(batch_dir: Path, model: str, judged_candidates: list[dict], results: list[dict],
                    rewritten: bool = False) -> None:
    """후보 판정을 판정자에게 보인 종류(judged_kind)와 함께 남긴다. 칸 이름을 kind로 두지 않는 것은, 올린 후보의 판정이
    문항의 판정 줄이 될 때(promote) 자동 검사가 정한 문항의 종류를 덮지 않게 하려는 것이다."""
    kinds = {candidate["id"]: candidate["kind"] for candidate in judged_candidates}
    pipeline.write(batch_dir, verdict_step(model, rewritten),
                   [{**result, "judged_kind": kinds[result["id"]]} for result in results])


def promote(batch_dir: Path, model: str, rewritten: bool = False) -> Counter:
    """판정을 통과한 후보 중 번호가 가장 앞선 답을 그 문항의 목표 답으로 올린다. targets·judged에 줄을 더하고 자동 검사를 다시
    매긴다(pipeline.run_checks — 같은 입력이면 같은 결과). 돌려주는 것: 대상·올림·통과한 후보 없음·자동 검사를 통과한 후보
    없음(다시 쓴 목표 답이 아직 없는 문항 포함)·판정 전 문항 수."""
    targeted = [record["id"] for record in _targeted(batch_dir)]
    verdicts = pipeline.read(batch_dir, verdict_step(model, rewritten))
    by_item: dict[str, list[dict]] = {}
    for candidate in candidates(batch_dir, model, rewritten):
        by_item.setdefault(candidate["item"], []).append(candidate)
    counts, targets, item_verdicts = Counter(대상=len(targeted)), [], []
    for item in targeted:
        found = by_item.get(item, [])
        passed = [candidate for candidate in found if (judged(candidate, verdicts) or {}).get("verdict") == "통과"]
        if passed:
            chosen = passed[0]  # 후보는 답 번호 순서다
            targets.append({"id": item, "target_ga": chosen["target_ga"], "target_generation": chosen["target_generation"]})
            item_verdicts.append({**verdicts[chosen["id"]], "id": item, "from": model, "sample": chosen["sample"]})
            counts["올림"] += 1
        elif not found:
            counts["자동 검사를 통과한 후보 없음"] += 1
        elif any(judged(candidate, verdicts) is None for candidate in found):
            counts["판정 전"] += 1
        else:
            counts["통과한 후보 없음"] += 1
    if targets:
        pipeline.write(batch_dir, "targets", targets)
        pipeline.write(batch_dir, "judged", item_verdicts)
        pipeline.run_checks(batch_dir)
    return counts
