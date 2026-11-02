"""단계 실행: 묶음 폴더의 앞 단계 JSONL을 읽고 다음 단계를 붙여 쓴다. 끝난 예시는 건너뛴다(이어서 돌리기).

같은 예시 번호가 한 파일에 여러 줄이면 뒤 줄을 쓴다. 실패한 줄(error)은 다음 실행에서 다시 한다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable

from . import checks, clients, prompts
from .plan import KINDS, ROUND1, USERS, scale

STEPS = ("plan", "questions", "attached", "targets", "checked", "judged", "human")
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


def run_attach(batch_dir: Path, session, ai_url: str, limit: int | None = None,
               log: Callable[[str], None] = print) -> Counter:
    """근거 붙이기: 데이터셋 AI 서버 /query(평가용 옵션)로 운영 프롬프트·근거 8개·학습 전 A.X 답을 받는다."""
    counts = Counter()
    for record in _todo(batch_dir, "attached", lambda r: r.get("possible") and r.get("question"), limit):
        try:
            result = {"id": record["id"], **clients.attach(session, ai_url, record["question"])}
            counts["attached"] += 1
        except (ValueError, KeyError, OSError) as error:
            result = {"id": record["id"], "error": str(error)}
            counts["error"] += 1
        write(batch_dir, "attached", [result])
        log(f"근거 {record['id']}: {'실패 ' + result['error'] if 'error' in result else '받음'}")
    return counts


def run_targets(batch_dir: Path, session, ollama_url: str, model: str, shapes: tuple[str, ...] = ("ga",),
                limit: int | None = None, log: Callable[[str], None] = print) -> Counter:
    """목표 답 초안. 답이 있는 종류에만 답 근거를 함께 준다(거절 종류는 근거만 보고 거절해야 한다)."""
    counts = Counter()
    for record in _todo(batch_dir, "targets", lambda r: bool(r.get("prompt")), limit):
        hint = record.get("hint") if KINDS[record["kind"]].answerable else ""
        result = {"id": record["id"], "target_generation": {"model": model, **TARGET_OPTIONS}}
        try:
            for shape in shapes:
                out = clients.generate(session, ollama_url, model, prompts.target_prompt(record, record["prompt"], hint, shape),
                                       **TARGET_OPTIONS)
                result[f"target_{shape}"] = out["text"].strip()
                result["target_generation"][shape] = out["generation"]
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
        result = {"id": record["id"], "duplicate_of": duplicate_of.get(record["id"]),
                  "result": {shape: checks.check(record, shape) for shape in shapes if record.get(f"target_{shape}")}}
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
    """단계별 개수와 종류별 통과 수."""
    records = merged(batch_dir)
    by_kind: dict[str, Counter] = {}
    for record in records:
        counter = by_kind.setdefault(record["kind"], Counter())
        counter["plan"] += 1
        counter["question"] += bool(record.get("possible") and record.get("question"))
        counter["attached"] += bool(record.get("prompt"))
        counter["target"] += bool(record.get("target_ga"))
        counter["keep"] += bool((record.get("keep") or {}).get("ga"))
    return {kind: dict(counter) for kind, counter in by_kind.items()}


def verdicts(batch_dir: Path) -> dict[str, str]:
    """예시마다 최종 판정: 사람 판정이 있으면 사람, 없으면 Claude(ADR-0037). 판정 전이면 빠진다."""
    return {record["id"]: record.get("human") or record["verdict"] for record in merged(batch_dir)
            if record.get("human") or record.get("verdict")}


def export(batch_dir: Path, out_file: Path, shape: str = "ga", verdicts: dict[str, str] | None = None) -> int:
    """학습 파일(A.X 채팅 형식): 사용자 = 운영 프롬프트, 답 = 목표 답. 자동 검사 통과(중복 아님)이고,
    판정(verdicts)을 주면 '통과'인 예시만. A.X는 시스템 메시지 없이 사용자 한 턴으로 답한다(deploy/models 틀)."""
    kept = 0
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as out:
        for record in merged(batch_dir):
            if not (record.get("keep") or {}).get(shape):
                continue
            if verdicts is not None and verdicts.get(record["id"]) != "통과":
                continue
            out.write(json.dumps({
                "id": record["id"],
                "messages": [{"role": "user", "content": record["prompt"]},
                             {"role": "assistant", "content": record[f"target_{shape}"]}],
                "meta": {key: record.get(key) for key in ("kind", "user_actual", "style", "ledger_id", "group_id")}
                        | {"drafter": (record.get("drafter") or {}).get("model"), "shape": shape},
            }, ensure_ascii=False) + "\n")
            kept += 1
    return kept
