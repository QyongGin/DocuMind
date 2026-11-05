"""선호 쌍(4회차, ADR-0053): 판정을 통과한 목표 답을 선호 답, 3회차 모델이 같은 운영 프롬프트에 낸 틀린 답을 비선호 답으로
짝짓는다(설계 `docs/rag/m2/4회차-학습-설계-20261103.md` §5).

3회차 답(`probe --model`)은 먼저 규칙으로 가른다: 거절 문장으로 시작하는가, 목표 답의 값(날짜·금액·인원 등)을 말했는가,
말한 값이 근거에 있는가. 규칙으로 못 가른 답만 격리된 Claude 판정(`judge-probes`)에 넘긴다. 연락처는 값으로 세지 않는다 —
거절 뒤에 확인처만 붙인 답을 '거절한 뒤 답했다'로, 연락처만 말한 답을 '목표 답의 값을 말했다'로 잘못 가르지 않게.

답없음 사본(2026-11-05 ADR-0053 변경 메모): 3회차는 학습용으로 만든 질문을 거의 틀리지 않아 틀린 답만으로는 쌍이 모자랐다.
판정을 통과한 답 있는 예시마다 답 근거가 든 청크를 뺀 사본을 만들고(거절 + 확인처 종류와 같은 방법), 같은 질문으로
'근거가 있으면 답한다'(원본: 목표 답 대 사본에서 3회차가 한 거절)와 '근거가 없으면 거절한다'(사본: 거절 안내 목표 답 대
원본에서 3회차가 한 답 — 사본 근거로는 근거 없는 단정이다) 두 쌍을 짓는다. 비선호 답은 모두 3회차가 실제로 쓴 글이다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..evalset.scoring import normalize, numbers_with_units
from . import checks, judge, pipeline
from .evidence import CITE, evidence_blocks
from .plan import KINDS
from .prompts import REFUSAL, REFUSALS

# 쌍 종류(설계 §5). 한 문항에 해당하는 답이 여럿이면 순위가 앞선 종류부터 고른다: 과잉 거절·지어내기 → 틀린 값 → 거절 머리말
PAIR_TYPES = {"over_refusal": "과잉 거절", "wrong_value": "틀린 값", "fabrication": "지어내기", "refusal_preamble": "거절 머리말"}
RANK = {"over_refusal": 0, "fabrication": 0, "wrong_value": 1, "refusal_preamble": 2}
CORRECT = "correct"
UNDECIDED = "undecided"  # 규칙으로 못 가름 — Claude 판정에 넘긴다
INCOMPLETE = "incomplete"  # 결론은 맞고 값 일부가 빠진 답. 쌍 종류가 아니라 쓰지 않는다
CONFLICT = "conflict"  # Claude 판정이 목표 답과 어긋남(목표 답이나 종류가 틀렸을 수 있다) — 그 문항은 쓰지 않는다
# 답없음 사본을 만들 원본 종류(계획과 최종 모두). 일부만 있음은 이미 답 일부가 없고, 거절 종류는 뺄 답 근거가 없다
COPY_KINDS = ("fact", "procedure", "table", "multi")
COPY_PLAN_KEYS = ("user", "style", "seed", "group_id", "ledger_id", "document_id", "title", "topic", "format", "chunks",
                  "wording")
NATURAL = "3회차 답"  # 비선호 답이 그 입력에서 3회차가 실제로 낸 틀린 답


def verdict_step(model: str) -> str:
    """그 모델 답의 Claude 판정을 둘 단계 이름(예: 'probes-ax40light-r3-q4km-judged')."""
    return f"{pipeline.probe_step(model)}-judged"


def core_values(text: str, question: str = "") -> set[str]:
    """답이 말한 값 중 연락처를 뺀 것: 단위 붙은 숫자(질문에 있던 것은 뺌)."""
    return numbers_with_units(normalize(text)) - numbers_with_units(normalize(question))


def head_refusal(answer: str) -> str | None:
    """답 맨 앞의 운영 거절 문장(지난 문장 포함). 없으면 None."""
    text = answer.strip()
    return next((sentence for sentence in REFUSALS if text.startswith(sentence)), None)


def classify(record: dict, answer: str) -> str:
    """3회차 답 하나를 규칙으로 가른다. record는 자동 검사·판정을 마친 예시(종류는 받은 근거로 정한 종류)다.
    돌려주는 것: correct, over_refusal, wrong_value, fabrication, refusal_preamble, undecided."""
    question = record.get("question") or ""
    said = core_values(answer, question)
    refusal = head_refusal(answer)
    if not KINDS[record["kind"]].answerable:
        if refusal:
            return CORRECT
        if checks.refusal_like(answer):
            return UNDECIDED if said else CORRECT  # 다른 말투로 거절했다. 값도 말했으면 무엇을 단정했는지 Claude가 본다
        return "fabrication" if said else UNDECIDED
    expected = core_values(record.get("target_ga") or "", question)
    if refusal:
        rest = answer.strip()[len(refusal):]
        if not CITE.sub("", rest).strip():
            return "over_refusal"  # 거절 문장만 — 판정을 통과한 목표 답이 있으니 근거에 답이 있다
        if not expected:
            return UNDECIDED  # 값이 없는 목표 답(절차·설명)이면 거절 뒤의 글이 답인지 값으로 가를 수 없다
        return "refusal_preamble" if core_values(rest, question) & expected else "over_refusal"
    if not expected:
        return UNDECIDED
    context = normalize("\n".join(evidence_blocks(record.get("prompt") or "").values()))
    grounded = all(checks.value_in(value, context) for value in said)
    if said & expected and grounded:
        # 일부만 있음은 없는 쪽을 밝혔는지까지 봐야 맞다(없는 것에 값을 지어냈을 수 있다)
        return CORRECT if record["kind"] != "partial" or checks.refusal_like(answer) else UNDECIDED
    if said and not said & expected and not grounded:
        return "wrong_value"  # 목표 답의 값은 하나도 없고 근거에 없는 값을 말했다
    # 근거에 있는 다른 값(표의 다른 칸·행일 수 있다)이나 값 없는 답은 규칙으로 맞고 틀림을 가를 수 없다
    return UNDECIDED


def from_verdict(record: dict, answer: str, verdict: str) -> str:
    """Claude 판정 값을 쌍 종류로 바꾼다. 답 있는 문항에 '거절 맞음'처럼 목표 답과 어긋나는 판정은 conflict다."""
    if KINDS[record["kind"]].answerable:
        return {"맞음": CORRECT, "틀림": "wrong_value", "과잉 거절": "over_refusal",
                "일부": "refusal_preamble" if head_refusal(answer) else INCOMPLETE}.get(verdict, CONFLICT)
    return {"거절 맞음": CORRECT, "틀림": "fabrication"}.get(verdict, CONFLICT)


def assess(record: dict, answers: list[str], verdicts: dict[str, dict]) -> list[dict]:
    """문항의 답마다 번호(1부터)·결과·가른 곳(규칙·Claude). 규칙으로 못 가르고 Claude 판정도 없으면 결과가 undecided다."""
    results = []
    for number, answer in enumerate(answers, 1):
        outcome, by = classify(record, answer), "규칙"
        verdict = verdicts.get(judge.answer_id(record["id"], number)) if outcome == UNDECIDED else None
        if verdict:
            outcome, by = from_verdict(record, answer, verdict["verdict"]), "Claude"
        results.append({"sample": number, "answer": answer, "outcome": outcome, "by": by})
    return results


def candidates(batch_dir: Path, model: str) -> list[dict]:
    """쌍을 만들 수 있는 문항: 최종 판정 '통과'이고 결론 먼저 모양이 자동 검사를 통과했으며 그 모델의 답을 받은 문항.
    답은 answers, 그 답의 Claude 판정은 answer_verdicts 칸에 붙인다."""
    probes = pipeline.read(batch_dir, pipeline.probe_step(model))
    verdicts = pipeline.read(batch_dir, verdict_step(model))
    found = []
    for record in pipeline.merged(batch_dir):
        probe = probes.get(record["id"]) or {}
        if pipeline.final_verdict(record) == "통과" and (record.get("keep") or {}).get("ga") and probe.get("ax_samples"):
            found.append({**record, "answers": probe["ax_samples"], "answer_verdicts": verdicts})
    return found


def pending(batch_dir: Path, model: str) -> list[dict]:
    """Claude 판정이 필요한 답(규칙으로 못 가르고 아직 판정 전), judge.answer_example 모양으로."""
    return [judge.answer_example(record, result["sample"], result["answer"])
            for record in candidates(batch_dir, model)
            for result in assess(record, record["answers"], record["answer_verdicts"]) if result["outcome"] == UNDECIDED]


def pair_line(record: dict, rejected: dict, results: list[dict], model: str) -> dict:
    """선호 쌍 한 줄(TRL 대화 형식): 입력 = 운영 프롬프트, 선호 답 = 학습 파일과 같은 목표 답, 비선호 답 = 고른 3회차 답
    그대로(rejected는 assess 결과 하나). type_samples는 그 문항의 답 중 같은 종류로 틀린 답 수다. made_from은 비선호 답이
    어디서 왔는지(이 입력의 3회차 답, 답없음 사본이면 원본 답·사본 거절)다."""
    return {"id": record["id"],
            "prompt": [{"role": "user", "content": pipeline.current_rules(record["prompt"])}],
            "chosen": [{"role": "assistant", "content": pipeline.training_target(record["target_ga"])}],
            "rejected": [{"role": "assistant", "content": rejected["answer"]}],
            "meta": {key: record.get(key) for key in ("kind", "kind_planned", "user_actual", "style", "ledger_id", "group_id",
                                                      "source_id")}
                    | {"pair": rejected["outcome"], "sample": rejected["sample"], "judged_by": rejected["by"], "model": model,
                       "type_samples": sum(result["outcome"] == rejected["outcome"] for result in results),
                       "made_from": rejected.get("made_from", NATURAL)}}


def no_answer_copies(source_dirs: list[Path], batch: str) -> tuple[list[dict], list[dict]]:
    """답없음 사본의 계획 줄과 질문 줄. 원본은 판정 통과·자동 검사 통과이고 답 근거가 있는 답 있는 종류(계획과 최종 모두)다.
    사본은 같은 질문·답 근거를 거절 + 확인처 종류로 계획해, 근거를 붙일 때 답이 든 청크가 빠진다."""
    plans, questions = [], []
    for source_dir in source_dirs:
        for record in pipeline.merged(source_dir):
            planned = record.get("kind_planned") or record["kind"]
            if (pipeline.final_verdict(record) != "통과" or not (record.get("keep") or {}).get("ga")
                    or record["kind"] not in COPY_KINDS or planned not in COPY_KINDS or not record.get("hint")):
                continue
            copy_id = f"{batch}-{len(plans) + 1:04d}"
            plans.append({key: record[key] for key in COPY_PLAN_KEYS if key in record}
                         | {"id": copy_id, "batch": batch, "kind": "refuse_guide", "source_id": record["id"]})
            questions.append({"id": copy_id, "question": record["question"], "hint": record["hint"],
                              "user_actual": record.get("user_actual"), "possible": True,
                              "drafter": {"copied_from": record["id"]}})
    return plans, questions


def copy_lines(copy_dirs: list[Path], sources: dict[str, dict], model: str, used: set[str]) -> tuple[list[dict], Counter]:
    """답없음 사본마다 두 쌍. 사본 쌍(지어내기): 3회차가 사본에서 지어낸 답이 있으면 그것, 없으면 원본에서 맞힌 답.
    원본 쌍(과잉 거절): 원본에 이미 쌍이 있으면(used) 짓지 않고, 사본에서 3회차가 한 거절을 비선호 답으로 쓴다.
    사본 근거에서도 답이 나와 종류가 바뀐 사본, 원본이 쌍 후보가 아닌 사본(질문 중복 등)은 쓰지 않는다."""
    lines, counts = [], Counter()
    for copy_dir in copy_dirs:
        for copy in candidates(copy_dir, model):
            counts["copies"] += 1
            source = sources.get(copy.get("source_id"))
            if copy["kind"] != "refuse_guide":
                counts["copy_has_answer"] += 1
                continue
            if source is None:
                counts["no_source"] += 1
                continue
            copy_results = assess(copy, copy["answers"], copy["answer_verdicts"])
            source_results = assess(source, source["answers"], source["answer_verdicts"])
            outcomes = {result["outcome"] for result in copy_results + source_results}
            if UNDECIDED in outcomes:
                counts["unjudged"] += 1
                continue
            if CONFLICT in outcomes:
                counts["conflict"] += 1
                continue
            fabricated = [result for result in copy_results if result["outcome"] == "fabrication"]
            source_right = [result for result in source_results if result["outcome"] == CORRECT]
            if fabricated:
                rejected = fabricated[0]
            elif source_right:
                rejected = {**source_right[0], "outcome": "fabrication", "made_from": "원본 답"}
            else:
                counts["no_source_answer"] += 1
                continue
            lines.append(pair_line(copy, rejected, copy_results, model))
            counts["twins"] += 1
            if source["id"] in used:
                continue
            refused = [result for result in copy_results if result["outcome"] == CORRECT and head_refusal(result["answer"])]
            refusal = ({**refused[0], "outcome": "over_refusal", "made_from": "사본 거절"} if refused else
                       {"sample": 0, "answer": REFUSAL, "outcome": "over_refusal", "by": "규칙", "made_from": "거절 문장"})
            lines.append(pair_line(source, refusal, source_results, model))
            used.add(source["id"])
    return lines, counts


def build(batch_dirs: list[Path], model: str, copy_dirs: list[Path] = ()) -> tuple[list[dict], dict]:
    """선호 쌍과 기록(manifest). 문항마다 한 쌍이고, 비선호 답은 순위가 가장 앞선 종류의 첫 답이다. 3회차가 모두 맞힌 문항,
    Claude 판정이 목표 답과 어긋난 문항은 쓰지 않는다. 묶음을 넘어 질문이 겹치면 앞 묶음 것만 쓴다. copy_dirs(답없음 사본
    묶음)를 주면 사본마다 사본 쌍과 원본 쌍을 더한다(copy_lines).

    지어내기 쌍이 과잉 거절 쌍보다 적으면 과잉 거절 쌍을 지어내기 쌍 수까지만 남긴다(3회차가 같은 문항을 더 자주 거절한 쌍
    먼저). 과잉 거절만 많이 배우면 거절 기준이 단정 쪽으로 넘어가 답없음 거절이 떨어진다(설계 §5).
    """
    records = [record for batch_dir in batch_dirs for record in candidates(batch_dir, model)]
    duplicate_of = checks.duplicates(records)
    records = [record for record in records if record["id"] not in duplicate_of]
    lines, answers, items = [], Counter(), Counter(candidates=len(records))
    for record in records:
        results = assess(record, record["answers"], record["answer_verdicts"])
        answers.update(result["outcome"] for result in results)
        outcomes = {result["outcome"] for result in results}
        if UNDECIDED in outcomes:
            items["unjudged"] += 1
            continue
        if CONFLICT in outcomes:
            items["conflict"] += 1
            continue
        bad = [result for result in results if result["outcome"] in PAIR_TYPES]
        if not bad:
            items["no_bad_answer"] += 1
            continue
        lines.append(pair_line(record, min(bad, key=lambda result: (RANK[result["outcome"]], result["sample"])),
                               results, model))
    copies = Counter()
    if copy_dirs:
        more, copies = copy_lines(list(copy_dirs), {record["id"]: record for record in records}, model,
                                  {line["id"] for line in lines})
        lines += more
        if copies["unjudged"]:
            items["unjudged"] += copies["unjudged"]
    over = [line for line in lines if line["meta"]["pair"] == "over_refusal"]
    fabricated = sum(line["meta"]["pair"] == "fabrication" for line in lines)
    dropped = set()
    if len(over) > fabricated:
        order = {line["id"]: number for number, line in enumerate(lines)}
        kept = sorted(over, key=lambda line: (-line["meta"]["type_samples"], order[line["id"]]))[:fabricated]
        dropped = {line["id"] for line in over} - {line["id"] for line in kept}
        lines = [line for line in lines if line["id"] not in dropped]
    manifest = {"size": len(lines), "batches": [Path(batch_dir).name for batch_dir in batch_dirs], "model": model,
                "types": dict(Counter(line["meta"]["pair"] for line in lines)),
                "kinds": dict(Counter(line["meta"]["kind"] for line in lines)),
                "judged_by": dict(Counter(line["meta"]["judged_by"] for line in lines)),
                "made_from": dict(Counter(line["meta"]["made_from"] for line in lines)),
                "copy_batches": [Path(copy_dir).name for copy_dir in copy_dirs], "copies": dict(copies),
                "dropped_over_refusal": len(dropped), "items": dict(items), "answers": dict(answers),
                # 입력 규칙이 지난 글인 문항 수(0이어야 한다 — 3회차 답은 받은 입력 그대로라, 학습 입력만 바꾸면 둘이 어긋난다)와
                # 내보낸 입력·선호 답에 지난 거절 문장이나 '(없는 것)' 자리표시가 남은 줄 수
                "legacy_prompts": sum(pipeline.current_rules(record["prompt"]) != record["prompt"] for record in records),
                "old_refusal_left": sum(any(mark in json.dumps([line["prompt"], line["chosen"]], ensure_ascii=False)
                                            for mark in pipeline.LEFTOVERS) for line in lines),
                "ids": [line["id"] for line in lines]}
    return lines, manifest


def write(lines: list[dict], manifest: dict, out_dir: Path) -> None:
    """pairs.jsonl과 manifest.json을 쓴다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pairs.jsonl").open("w", encoding="utf-8") as out:
        for line in lines:
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
