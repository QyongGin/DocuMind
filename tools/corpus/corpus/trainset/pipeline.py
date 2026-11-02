"""단계 실행: 묶음 폴더의 앞 단계 JSONL을 읽고 다음 단계를 붙여 쓴다. 끝난 예시는 건너뛴다(이어서 돌리기).

같은 예시 번호가 한 파일에 여러 줄이면 뒤 줄을 쓴다. 실패한 줄(error)은 다음 실행에서 다시 한다.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Callable

from . import checks, clients, evidence, prompts, timeline
from .plan import KINDS, ROUND1, USERS, scale

STEPS = ("plan", "questions", "attached", "probes", "targets", "checked", "judged", "human")
QUESTION_OPTIONS = {"temperature": 0.7, "num_ctx": 4096, "num_predict": 400}
TARGET_OPTIONS = {"temperature": 0.2, "num_ctx": 12288, "num_predict": 700}


def path(batch_dir: Path, step: str) -> Path:
    return Path(batch_dir) / f"{step}.jsonl"


def read(batch_dir: Path, step: str) -> dict[str, dict]:
    file = path(batch_dir, step)
    if not file.exists():
        return {}
    records = {}
    for line in file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["id"]] = record
    return records


def write(batch_dir: Path, step: str, records: list[dict], mode: str = "a") -> None:
    Path(batch_dir).mkdir(parents=True, exist_ok=True)
    with path(batch_dir, step).open(mode, encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")


def merged(batch_dir: Path) -> list[dict]:
    """계획 순서대로 단계별 칸을 합친 예시. 실패한 단계의 칸은 합치지 않는다."""
    steps = {step: read(batch_dir, step) for step in STEPS}
    records = []
    for item_id, item in steps["plan"].items():
        record = dict(item)
        for step in STEPS[1:]:
            part = steps[step].get(item_id)
            if part and "error" not in part:
                record.update(part)
        records.append(record)
    return records


USER_WORDS = {"예비 입학생·지원자": ("입학", "지원", "수험", "학부모"), "재학생": ("재학", "학생"),
              "교직원": ("교직원", "직원", "교수", "강사"), "외국인": ("외국",), "업체": ("업체", "기업", "회사")}


def user_category(text: str, planned: str) -> str:
    """초안 모델이 적은 '묻는 사람'을 사용자 범주(USERS) 하나로 맞춘다. 범주 이름의 낱말로 가르고, 못 가르면 계획한 범주."""
    text = str(text or "").strip()
    if text in USERS:
        return text
    for category in ("외국인", "업체", "교직원", "예비 입학생·지원자", "재학생"):  # 더 좁은 범주를 먼저 본다
        if any(word in text for word in USER_WORDS[category]):
            return category
    return planned


def _todo(batch_dir: Path, step: str, ready: Callable[[dict], bool], limit: int | None) -> list[dict]:
    done = {item_id for item_id, record in read(batch_dir, step).items() if "error" not in record}
    todo = [record for record in merged(batch_dir) if record["id"] not in done and ready(record)]
    return todo[:limit] if limit else todo


def run_questions(batch_dir: Path, session, ollama_url: str, model: str, limit: int | None = None,
                  log: Callable[[str], None] = print) -> Counter:
    """질문 초안(초안 모델, JSON). 모델이 이 글로 그 종류의 질문을 만들 수 없다고 하면 possible=false로 남긴다."""
    counts = Counter()
    for record in _todo(batch_dir, "questions", lambda r: True, limit):
        try:
            out = clients.generate(session, ollama_url, model, prompts.question_prompt(record), json_mode=True,
                                   **QUESTION_OPTIONS)
            data = clients.parse_json(out["text"])
            result = {"id": record["id"], "question": str(data.get("질문") or "").strip(),
                      "hint": str(data.get("답 근거") or "").strip(),
                      "user_actual": user_category(data.get("묻는 사람"), record["user"]),
                      "possible": bool(data.get("가능", True)) and bool(str(data.get("질문") or "").strip()),
                      "drafter": {**QUESTION_OPTIONS, **out["generation"], "model": model}}
            counts["made" if result["possible"] else "impossible"] += 1
        except (ValueError, KeyError, OSError) as error:
            result = {"id": record["id"], "error": str(error)}
            counts["error"] += 1
        write(batch_dir, "questions", [result])
        log(f"질문 {record['id']} {record['kind']}: {result.get('question') or result.get('error')}")
    return counts


REFUSAL_ROUNDS = 3  # 답이 든 청크를 빼고 다시 붙이는 최대 횟수(빼면 다른 청크의 같은 답이 올라올 수 있다)


def _construct_refusal(session, ai_url: str, record: dict, attached: dict, options: dict) -> tuple[dict, dict]:
    """답없음 예시(ADR-0048 결정 2): 답 근거가 든 근거 블록의 청크를 빼고 다시 붙여, 근거 8개에 답이 없게 만든다.
    빼도 답이 남으면 실패로 돌려준다(그 예시는 버린다)."""
    hint = (record.get("hint") or "").strip()
    if not hint:
        raise ValueError("답 근거가 없어 답없음 예시를 만들 수 없음")
    removed: list[str] = []
    for _ in range(REFUSAL_ROUNDS):
        blocks = checks.hint_blocks(hint, attached["prompt"])
        if not blocks:
            return attached, {"removed_chunks": removed}
        for number in blocks:
            entry = attached["retrieved"][number - 1] if number - 1 < len(attached["retrieved"]) else {}
            chunk_id = str(entry.get("chunk_id") or "")
            if chunk_id and chunk_id not in removed:
                removed.append(chunk_id)
        attached = clients.attach(session, ai_url, record["question"], exclude_chunk_ids=removed, **options)
    if checks.hint_blocks(hint, attached["prompt"]):
        raise ValueError(f"답이 든 청크 {len(removed)}개를 빼도 근거에 답이 남음")
    return attached, {"removed_chunks": removed}


def refusal_contact_blocks(record: dict, retrieved: list[dict], family: dict | None) -> list[int]:
    """답없음 예시의 확인처를 고를 근거 블록 번호: 재료 문서의 다른 청크, 같은 게시글(본문·첨부), 같은 묶음의 문서.
    family(문서 → (게시글, 묶음))가 없으면 재료 문서만 본다."""
    family = family or {}
    material = str(record.get("ledger_id") or "")
    post, group = family.get(material, (material, None))
    blocks = []
    for number, entry in enumerate(retrieved, 1):
        ledger_id = str(entry.get("ledger_id") or "")
        other_post, other_group = family.get(ledger_id, (ledger_id, None))
        if ledger_id and (ledger_id == material or other_post == post or (group and other_group == group)):
            blocks.append(number)
    return blocks


def run_attach(batch_dir: Path, session, ai_url: str, limit: int | None = None,
               log: Callable[[str], None] = print, dates: dict[str, timeline.Dates] | None = None,
               today: str | None = None, family: dict | None = None) -> Counter:
    """근거 붙이기: 데이터셋 AI 서버 /query(평가용 옵션)로 운영 프롬프트·근거 8개·학습 전 A.X 답을 받는다.

    dates(문서 대장의 게시일·유효 기간)를 주면 예시마다 그날의 서비스 색인 모양으로 근거를 붙인다(ADR-0047):
    그날 없던 문서를 검색 후보에서 빼고 프롬프트의 기준 날짜를 그날로 준다. 어떻게 붙였는지 예시의 timeline에 남긴다.
    거절 + 확인처 종류는 답이 든 청크를 빼서 근거에 답이 없게 만들고(ADR-0048 결정 2), 확인처를 고를 블록을 refusal에 남긴다.
    """
    counts = Counter()
    today = today or date.today().isoformat()
    for record in _todo(batch_dir, "attached", lambda r: r.get("possible") and r.get("question"), limit):
        try:
            options, info = {}, {}
            if dates is not None:
                day = timeline.the_day(record.get("ledger_id"), dates, today)
                keep_old = timeline.keeps_old_versions(record["id"])
                excluded = timeline.excluded_ledger_ids(day, dates, keep_old)
                options = {"exclude_ledger_ids": excluded, "as_of": day}
                info = {"timeline": {"as_of": day, "old_versions": keep_old, "excluded_ledgers": len(excluded)}}
            attached = clients.attach(session, ai_url, record["question"], **options)
            if record["kind"] == "refuse_guide":
                attached, refusal = _construct_refusal(session, ai_url, record, attached, options)
                info["refusal"] = {**refusal,
                                   "contact_blocks": refusal_contact_blocks(record, attached["retrieved"], family)}
            result = {"id": record["id"], **attached, **info}
            counts["attached"] += 1
        except (ValueError, KeyError, OSError) as error:
            result = {"id": record["id"], "error": str(error)}
            counts["error"] += 1
        write(batch_dir, "attached", [result])
        log(f"근거 {record['id']}: {'실패 ' + result['error'] if 'error' in result else '받음'}")
    return counts


# 학습 전 A.X를 같은 운영 프롬프트로 여러 번 답하게 해 예시마다 아는 정도를 잰다(ADR-0042).
# 운영 설정은 temperature 0이라 같은 답만 나와, 표본 추출로 받는다. 0.7은 판단값이다(높으면 엉뚱한 답, 낮으면 같은 답이 많음)
PROBE_SAMPLES = 4
PROBE_TEMPERATURE = 0.7


def run_probe(batch_dir: Path, session, ollama_url: str, samples: int = PROBE_SAMPLES,
              temperature: float = PROBE_TEMPERATURE, limit: int | None = None,
              log: Callable[[str], None] = print) -> Counter:
    """학습 전 A.X 답을 운영 프롬프트로 여러 번 받는다. 모델·문맥 길이·답 길이는 근거를 붙일 때 AI 서버가 알려 준 운영값을 쓴다."""
    counts = Counter()
    for record in _todo(batch_dir, "probes", lambda r: bool(r.get("prompt")), limit):
        runtime = record.get("runtime") or {}
        model = runtime.get("llm_model") or "ax40light:q4km"
        options = {"temperature": temperature, "num_ctx": runtime.get("num_ctx") or 12288,
                   "num_predict": runtime.get("num_predict") or 512}
        try:
            outs = [clients.generate(session, ollama_url, model, record["prompt"], **options) for _ in range(samples)]
            result = {"id": record["id"], "ax_samples": [out["text"].strip() for out in outs],
                      "probe_generation": {"model": model, **options, "samples": samples}}
            counts["probed"] += 1
        except (ValueError, KeyError, OSError) as error:
            result = {"id": record["id"], "error": str(error)}
            counts["error"] += 1
        write(batch_dir, "probes", [result])
        log(f"A.X 표본 {record['id']}: {'실패 ' + result['error'] if 'error' in result else len(result['ax_samples'])}")
    return counts


def run_targets(batch_dir: Path, session, ollama_url: str, model: str, shapes: tuple[str, ...] = ("ga",),
                limit: int | None = None, log: Callable[[str], None] = print) -> Counter:
    """목표 답 초안. 답이 있는 종류에만 답 근거를 함께 준다(거절 종류는 근거만 보고 거절해야 한다)."""
    counts = Counter()
    for record in _todo(batch_dir, "targets", lambda r: bool(r.get("prompt")), limit):
        hint = record.get("hint") if KINDS[record["kind"]].answerable else ""
        # 답 근거가 든 블록 번호는 코드가 짚어 준다(ADR-0048 결정 3) — 초안 모델이 번호를 찾다 틀리던 출처 번호 오류를 줄인다
        sources = checks.hint_blocks(hint, record["prompt"]) if hint else []
        # 답없음 예시는 코드가 고른 블록의 연락처·사이트만 확인처 후보로 보인다(ADR-0048 결정 2)
        refusal = record.get("refusal") if (record.get("kind_planned") or record["kind"]) == "refuse_guide" else None
        guidance_blocks = refusal.get("contact_blocks") or [] if refusal is not None else None
        result = {"id": record["id"], "target_generation": {"model": model, **TARGET_OPTIONS}}
        try:
            for shape in shapes:
                task = prompts.target_prompt(record, record["prompt"], hint, shape, hint_sources=sources,
                                             guidance_blocks=guidance_blocks)
                out = clients.generate(session, ollama_url, model, task, **TARGET_OPTIONS)
                text, generation = out["text"].strip(), out["generation"]
                # 답이 쓴 근거의 안내 줄이 빠졌으면 검사 결과를 주고 한 번 다시 쓴다(ADR-0046). 엉뚱한 근거 종류는
                # 질문이 문서에서 오지 않아 근거의 확인처가 질문과 무관하다
                planned = record.get("kind_planned") or record["kind"]
                refusal = checks.answer_body(text, shape).startswith(prompts.REFUSAL)
                missing = [] if planned == "refuse_offtopic" else evidence.missing_guidance(text, record["prompt"], refusal)
                if missing:
                    fixed = clients.generate(session, ollama_url, model, prompts.guidance_fix_prompt(task, text, missing),
                                             **TARGET_OPTIONS)
                    generation = {**generation, "guidance_fix": {
                        "draft": text, "missing": [f"[출처 {number}] {', '.join(lost)}" for number, _, lost in missing],
                        "generation": fixed["generation"]}}
                    text = fixed["text"].strip()
                    counts["guidance_fix"] += 1
                result[f"target_{shape}"] = text
                result["target_generation"][shape] = generation
            counts["made"] += 1
        except (ValueError, KeyError, OSError) as error:
            result = {"id": record["id"], "error": str(error)}
            counts["error"] += 1
        write(batch_dir, "targets", [result])
        log(f"목표 답 {record['id']}: {'실패 ' + result['error'] if 'error' in result else '만듦'}")
    return counts


def run_checks(batch_dir: Path, shapes: tuple[str, ...] = ("ga",)) -> Counter:
    """자동 검사를 다시 처음부터 매겨 checked.jsonl을 새로 쓴다(규칙이 바뀌어도 같은 입력이면 같은 결과)."""
    records = [record for record in merged(batch_dir) if any(record.get(f"target_{shape}") for shape in shapes)]
    duplicate_of = checks.duplicates(records)
    results, counts = [], Counter()
    for record in records:
        # 종류는 계획이 아니라 받은 근거로 정해 덮어쓴다(ADR-0041). 계획은 kind_planned에 남겨 다시 돌려도 같은 결과가 나오게 한다
        planned = record.get("kind_planned") or record["kind"]
        kind, _ = checks.decide_kind(record)
        result = {"id": record["id"], "kind": kind, "kind_planned": planned, "duplicate_of": duplicate_of.get(record["id"]),
                  "result": {shape: checks.check(record, shape) for shape in shapes if record.get(f"target_{shape}")},
                  "probe": checks.probe_score(record, kind)}
        counts["종류 바꿈"] += kind != planned
        # 모양마다 따로 남긴다: 중복이 아니고 그 모양의 자동 검사를 모두 통과
        result["keep"] = {shape: result["duplicate_of"] is None and not shape_result["drop"]
                          for shape, shape_result in result["result"].items()}
        counts["keep" if result["keep"].get("ga") else "drop"] += 1
        for shape_result in result["result"].values():
            for name, check_result in shape_result["checks"].items():
                if not check_result["ok"]:
                    counts[f"실패:{name}"] += 1
        results.append(result)
    write(batch_dir, "checked", results, mode="w")
    return counts


def pick_for_judge(records: list[dict], size: int) -> list[dict]:
    """판정할 예시를 종류별 개수(1회차 비율)를 지켜 고른다. 자동 검사를 통과하고 아직 판정 전인 예시에서 계획 순서대로.
    한 종류가 모자라면 남은 자리는 다른 종류의 남은 예시로 채운다."""
    ready = [record for record in records if (record.get("keep") or {}).get("ga") and record.get("verdict") is None]
    quotas = scale(ROUND1, size)
    chosen = []
    for kind, count in quotas.items():
        chosen += [record for record in ready if record["kind"] == kind][:count]
    for record in ready:
        if len(chosen) >= size:
            break
        if record not in chosen:
            chosen.append(record)
    order = {record["id"]: number for number, record in enumerate(records)}
    return sorted(chosen[:size], key=lambda record: order[record["id"]])


def status(batch_dir: Path) -> dict:
    """단계별 개수와 종류별 통과 수. 종류는 자동 검사 뒤에는 받은 근거로 정한 종류다(ADR-0041)."""
    records = merged(batch_dir)
    by_kind: dict[str, Counter] = {}
    for record in records:
        counter = by_kind.setdefault(record["kind"], Counter())
        counter["plan"] += 1
        counter["question"] += bool(record.get("possible") and record.get("question"))
        counter["attached"] += bool(record.get("prompt"))
        counter["target"] += bool(record.get("target_ga"))
        counter["keep"] += bool((record.get("keep") or {}).get("ga"))
        counter["종류 바꿈"] += bool(record.get("kind_planned")) and record["kind"] != record["kind_planned"]
    return {kind: dict(counter) for kind, counter in by_kind.items()}


def final_verdict(record: dict) -> str | None:
    """예시의 최종 판정: 사람 판정이 있으면 사람, 없으면 Claude(ADR-0037). 판정 전이면 None."""
    return record.get("human") or record.get("verdict")


def verdicts(batch_dir: Path) -> dict[str, str]:
    """묶음의 예시별 최종 판정. 판정 전이면 빠진다."""
    return {record["id"]: final_verdict(record) for record in merged(batch_dir) if final_verdict(record)}


def yields(batch_dirs: list[Path]) -> tuple[Counter, Counter, Counter]:
    """판정한 묶음들에서 종류별 통과 수(받은 근거로 정한 종류), 계획 수, 계획한 종류별 통과 수. 다음 묶음 계획(plan.fill_quotas)에 쓴다.
    판정 전인 묶음을 넣으면 수율이 낮게 잡히므로 판정을 마친 묶음만 넣는다."""
    passed, planned, planned_passed = Counter(), Counter(), Counter()
    for batch_dir in batch_dirs:
        for record in merged(batch_dir):
            kind_planned = record.get("kind_planned") or record["kind"]
            planned[kind_planned] += 1
            if final_verdict(record) == "통과":
                passed[record["kind"]] += 1
                planned_passed[kind_planned] += 1
    return passed, planned, planned_passed


def known_rate(record: dict) -> float:
    """학습 전 A.X가 여러 번 받은 답 중 맞힌 비율(ADR-0042). 값으로 하나도 가르지 못했으면 0.5(모름)."""
    probe = record.get("probe") or {}
    return probe["correct"] / probe["decided"] if probe.get("decided") else 0.5


def pick_round(batch_dirs: list[Path], size: int, shapes: tuple[str, ...] = ("ga", "na")) -> list[dict]:
    """1회차 학습 예시 고르기. 최종 판정 '통과'이고 모든 모양이 자동 검사를 통과한 예시에서 종류 비율(ROUND1)대로 고른다.
    종류 안에서는 학습 전 A.X가 틀리던 예시를 먼저 넣고(ADR-0042 쓰임 ①), 모자란 종류의 자리는 남은 예시로 같은 순서로 채운다.
    묶음을 넘어 질문이 겹치면 앞 묶음 것만 쓴다. 모든 모양에 같은 예시를 써서 모양 비교를 같은 문항 짝으로 한다(ADR-0039)."""
    candidates = [record for batch_dir in batch_dirs for record in merged(batch_dir)
                  if final_verdict(record) == "통과" and all((record.get("keep") or {}).get(shape) for shape in shapes)]
    duplicate_of = checks.duplicates(candidates)
    candidates = [record for record in candidates if record["id"] not in duplicate_of]
    order = {record["id"]: number for number, record in enumerate(candidates)}

    def priority(record: dict) -> tuple[float, int]:
        return known_rate(record), order[record["id"]]

    chosen = []
    for kind, count in scale(ROUND1, size).items():
        chosen += sorted((record for record in candidates if record["kind"] == kind), key=priority)[:count]
    picked = {record["id"] for record in chosen}
    chosen += sorted((record for record in candidates if record["id"] not in picked), key=priority)[:size - len(chosen)]
    return sorted(chosen, key=lambda record: order[record["id"]])


def training_line(record: dict, shape: str) -> dict:
    """학습 파일 한 줄(A.X 채팅 형식): 사용자 = 운영 프롬프트, 답 = 목표 답. A.X는 시스템 메시지 없이 사용자 한 턴으로 답한다
    (deploy/models 틀)."""
    return {"id": record["id"],
            "messages": [{"role": "user", "content": record["prompt"]},
                         {"role": "assistant", "content": record[f"target_{shape}"]}],
            "meta": {key: record.get(key) for key in ("kind", "kind_planned", "user_actual", "style", "ledger_id", "group_id")}
                    | {"drafter": (record.get("drafter") or {}).get("model"), "shape": shape}}


def export_round(batch_dirs: list[Path], out_dir: Path, size: int, shapes: tuple[str, ...] = ("ga", "na")) -> dict:
    """1회차 학습 파일: 모양마다 round-<모양>.jsonl(같은 예시), 고른 예시의 종류·A.X 아는 정도를 manifest.json에 남긴다."""
    chosen = pick_round(batch_dirs, size, shapes)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for shape in shapes:
        with (out_dir / f"round-{shape}.jsonl").open("w", encoding="utf-8") as out:
            for record in chosen:
                out.write(json.dumps(training_line(record, shape), ensure_ascii=False) + "\n")

    def known(record: dict) -> str:
        probe = record.get("probe") or {}
        if not probe.get("decided"):
            return "모름"
        return "다 맞힘" if probe["correct"] == probe["decided"] else ("못 맞힘" if probe["correct"] == 0 else "가끔")

    manifest = {"size": len(chosen), "batches": [Path(batch_dir).name for batch_dir in batch_dirs], "shapes": list(shapes),
                "kinds": dict(Counter(record["kind"] for record in chosen)),
                "known": dict(Counter(known(record) for record in chosen)), "ids": [record["id"] for record in chosen]}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def export(batch_dir: Path, out_file: Path, shape: str = "ga", verdicts: dict[str, str] | None = None) -> int:
    """한 묶음의 학습 파일(training_line 형식). 자동 검사 통과(중복 아님)이고, 판정(verdicts)을 주면 '통과'인 예시만."""
    kept = 0
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as out:
        for record in merged(batch_dir):
            if not (record.get("keep") or {}).get(shape):
                continue
            if verdicts is not None and verdicts.get(record["id"]) != "통과":
                continue
            out.write(json.dumps(training_line(record, shape), ensure_ascii=False) + "\n")
            kept += 1
    return kept
