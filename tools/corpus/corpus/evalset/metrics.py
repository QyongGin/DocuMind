"""실행 채점과 지표(M1 11번): 실행 폴더의 답을 평가셋으로 채점하고 지표·실패 위치를 낸다.

문항마다
    정확·안내   scoring.score — 프롬프트를 근거 글로 줘서 지어낸 숫자도 본다. 규칙이 '맞음'으로 봤어도 의심할 두 경우
                (우선 경로 답, 값 문항의 다른 값)는 '애매'로 보낸다(ADR-0028). '애매'는 판정 파일에서
                같은 (문항, 개정 번호, 답) 판정을 찾아 다시 쓴다
    실패 위치   허용 근거 문서(근거 + 허용 근거)의 후보가 핵심 사실을 모두 담았나를 단계(검색 → 최종 후보 → 문맥)마다 본다
    출처        최종 후보(=화면 출처)에 허용 근거 문서가 있나, 출처 중 몇 %가 허용 근거 문서인가
    답 잘림     Ollama 생성 종료 이유가 length

지표(설계 결정 ②-7, ADR-0023): 정답률·일부율·과잉 거절률(답 있는 문항), 환각률(전체), 답없음 거절 정확도, 출처 정확도,
안내 충실도. 비율마다 95% 신뢰구간(Wilson). 본·쉬운 문항, 개발셋·테스트셋을 따로 낸다.
테스트셋은 합계만 보여 준다: 문항별 결과는 봉인 파일에만 쓰고 화면·보고에 내지 않는다(ADR-0018).
"""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import schema
from .runner import ANSWERS, MANIFEST, read_answers
from .scoring import contains, normalize, numbers_with_units, score

RETRIEVAL_STAGES = ("vector", "bm25", "table_fact", "expanded")
DEV_RESULTS = "results_dev.jsonl"
TEST_RESULTS = "results_test.sealed.jsonl"
AMBIGUOUS = "ambiguous.jsonl"
METRICS = "metrics.json"
LABELS = ("맞음", "일부", "모름", "틀림", "애매", "빈 답")
JUDGED_LABELS = ("맞음", "일부", "모름", "틀림", "빈 답")


def judgment_key(item: dict, answer: str | None) -> str:
    """사람 판정 재사용 열쇠: 문항 ID + 개정 번호 + 정규화한 답. 문항을 고치면 개정 번호가 올라 옛 판정이 붙지 않는다."""
    digest = hashlib.sha256(normalize(answer or "").encode("utf-8")).hexdigest()[:16]
    return f"{item['id']}@{item.get('rev', 1)}#{digest}"


def load_judgments(path: str | Path | None) -> dict[str, dict]:
    """사람 판정 파일(JSONL: key, label, reason, by, at). 같은 열쇠는 뒤의 줄이 이긴다.
    판정은 맞음·일부·모름·틀림, 또는 생성이 멈춘 답(한두 글자에서 끝남)이면 빈 답."""
    if not path or not Path(path).exists():
        return {}
    judged = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("label") not in JUDGED_LABELS:
                raise ValueError(f"사람 판정은 {'·'.join(JUDGED_LABELS)} 중 하나: {record}")
            judged[record["key"]] = record
    return judged


def allowed_docs(item: dict) -> set[str]:
    return {entry["doc"] for entry in item.get("evidence") or []} | set(item.get("also") or [])


def _covers(item: dict, texts: list[str]) -> bool:
    """핵심 사실마다 허용 표기 하나라도 글 중 어딘가에 있나."""
    normalized = [normalize(text) for text in texts]
    return all(any(contains(text, value) for text in normalized for value in fact["values"])
               for fact in schema.core_facts(item))


def stage_hits(item: dict, trace: dict) -> dict[str, bool]:
    """단계마다 허용 근거 문서의 후보가 핵심 사실을 모두 담았나. 문맥은 프롬프트에 들어간 근거 글 전체."""
    allowed = allowed_docs(item)
    stages = trace.get("stages") or {}

    def texts(names):
        return [entry.get("text") or "" for name in names for entry in stages.get(name) or []
                if entry.get("ledger_id") in allowed]

    return {"retrieved": _covers(item, texts(RETRIEVAL_STAGES)), "final": _covers(item, texts(("final",))),
            "context": _covers(item, [trace.get("context") or ""])}


def failure_location(item: dict, label: str, hits: dict | None) -> str | None:
    if item["shape"] == "답없음":
        return "지어낸 답" if label == "틀림" else None
    if label == "맞음":
        return "통과" if hits["retrieved"] else "외운 답 의심"
    if not hits["retrieved"]:
        return "검색 실패"
    if not hits["final"]:
        return "후보 탈락"
    if not hits["context"]:
        return "문맥 탈락"
    return "생성 실패"


def source_accuracy(item: dict, trace: dict) -> tuple[bool, float]:
    """최종 후보(=화면 출처, 같은 실행)에 허용 근거 문서가 있나, 그 비율."""
    final = [entry.get("ledger_id") for entry in (trace.get("stages") or {}).get("final") or []]
    if not final:
        return False, 0.0
    allowed = allowed_docs(item)
    inside = sum(1 for ledger_id in final if ledger_id in allowed)
    return inside > 0, inside / len(final)


def doubt(item: dict, answer: str | None, trace: dict) -> str | None:
    """규칙이 '맞음'으로 본 답 중 판정으로 보낼 것(ADR-0028). 규칙은 정답 표기가 답 어딘가에 있으면 맞음을 준다.

    - 우선 경로: 모델을 거치지 않고 표 사실·근거 글을 그대로 붙인 답. 값을 나열만 해도 정답 값이 들어 있으면 맞음이 된다
    - 다른 값: 값 문항에서 정답 값과 단위가 같은 다른 값이 답에 함께 있다(30,000원 문항에 50,000원). 다른 값을 결론으로
      내세워도 맞음이 된다. 단위가 다른 숫자(연도·날짜 등)는 보지 않는다
    """
    if trace.get("answer_path") not in (None, "llm"):
        return "우선 경로"
    if item["shape"] == "값":
        expected = {number for fact in schema.core_facts(item) for value in fact["values"]
                    for number in numbers_with_units(normalize(value))}
        units = {_unit(number) for number in expected}
        others = numbers_with_units(normalize(answer or "")) - expected - numbers_with_units(normalize(item.get("question", "")))
        if any(_unit(number) in units for number in others):
            return "다른 값"
    return None


def _unit(number_with_unit: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)?", "", number_with_unit)


def score_record(item: dict, record: dict | None, judgments: dict[str, dict]) -> dict:
    """문항 하나의 결과 행. 답을 아직 못 받았으면 status '미실행'·'실패'."""
    row = {"id": item["id"], "rev": item.get("rev", 1), "set": item["set"], "part": item.get("part"),
           "shape": item["shape"], "topic": item.get("topic"), "tags": item.get("tags") or []}
    if record is None or "error" in record:
        row["status"] = "미실행" if record is None else "실패"
        return row
    trace = record.get("eval_trace") or {}
    answer = record.get("answer")
    result = score(item, answer, context=trace.get("prompt") or trace.get("context") or "")
    label, judged = result["label"], None
    doubted = doubt(item, answer, trace) if label == "맞음" else None
    if doubted:
        label = "애매"
    if label == "애매":
        judged = judgments.get(judgment_key(item, answer))
        if judged:
            label = judged["label"]
    hits = stage_hits(item, trace) if item["shape"] != "답없음" else None
    source_any, source_share = source_accuracy(item, trace)
    row.update(
        status="채점", question=item["question"], answer=answer, label=label, rule_label=result["label"],
        judged=bool(judged), doubt=doubted, guidance=result["guidance"]["label"], appended_refusal=result["appended_refusal"],
        invented=result["invented"], missing=list(result["missing"]),
        location=failure_location(item, label, hits), stages=hits, source_any=source_any,
        source_share=round(source_share, 3), truncated=(trace.get("generation") or {}).get("done_reason") == "length",
        answer_path=trace.get("answer_path"), elapsed=record.get("elapsed"), key=judgment_key(item, answer))
    return row


def wilson(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    """비율의 95% 신뢰구간(Wilson). 문항 수가 적을 때도 0~1 밖으로 나가지 않는다."""
    if total == 0:
        return None
    rate = successes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [round(centre - margin, 4), round(centre + margin, 4)]


def _rate(successes: int, total: int) -> dict:
    return {"k": successes, "n": total, "rate": round(successes / total, 4) if total else None,
            "ci95": wilson(successes, total)}


def aggregate(rows: list[dict]) -> dict:
    scored = [row for row in rows if row.get("status") == "채점"]
    answerable = [row for row in scored if row["shape"] != "답없음"]
    unanswerable = [row for row in scored if row["shape"] == "답없음"]
    labels = Counter(row["label"] for row in scored)
    with_guidance = [row for row in scored if row["guidance"] != "해당 없음"]
    count = lambda rows_, label: sum(1 for row in rows_ if row["label"] == label)  # noqa: E731
    return {
        "items": len(rows), "scored": len(scored),
        "not_run": sum(1 for row in rows if row.get("status") == "미실행"),
        "failed": sum(1 for row in rows if row.get("status") == "실패"),
        "labels": {label: labels.get(label, 0) for label in LABELS},
        "accuracy": _rate(count(answerable, "맞음"), len(answerable)),
        "partial": _rate(count(answerable, "일부"), len(answerable)),
        "over_refusal": _rate(count(answerable, "모름"), len(answerable)),
        "hallucination": _rate(count(scored, "틀림"), len(scored)),
        "unanswerable_refusal": _rate(count(unanswerable, "맞음"), len(unanswerable)),
        "source_hit": _rate(sum(1 for row in answerable if row["source_any"]), len(answerable)),
        "source_share": round(sum(row["source_share"] for row in answerable) / len(answerable), 4) if answerable else None,
        "guidance": _rate(sum(1 for row in with_guidance if row["guidance"] == "충족"), len(with_guidance)),
        "ambiguous_open": sum(1 for row in scored if row["label"] == "애매"),
        "judged": sum(1 for row in scored if row["judged"]),
        "doubted": sum(1 for row in scored if row.get("doubt")),
        "appended_refusal": sum(1 for row in scored if row["appended_refusal"]),
        "invented_numbers": sum(1 for row in scored if row["invented"]),
        "truncated": sum(1 for row in scored if row["truncated"]),
        "locations": dict(Counter(row["location"] for row in scored if row["location"])),
    }


def breakdown(rows: list[dict], key: str) -> dict:
    """답 유형·주제·태그별 정답률(답 있는 문항)과 문항 수. 테스트셋도 이 합계는 보인다(설계 ⑤-3)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("status") != "채점" or row["shape"] == "답없음" and key != "shape":
            continue
        for value in (row[key] if key == "tags" else [row[key]]):
            groups[value or "미정"].append(row)
    return {value: _rate(sum(1 for row in members if row["label"] == "맞음"), len(members))
            for value, members in sorted(groups.items())}


def score_run(evalset_path: str | Path, run_dir: str | Path, judgments_path: str | Path | None = None) -> dict:
    """실행 폴더를 채점해 결과 파일과 지표를 쓴다. 돌려주는 것: 지표(테스트셋은 합계만)."""
    run_dir = Path(run_dir)
    items = [item for item in schema.load(evalset_path) if not schema.dropped(item)]
    manifest = json.loads((run_dir / MANIFEST).read_text(encoding="utf-8"))
    if manifest["evalset_sha256"] != schema.fingerprint(schema.load(evalset_path)):
        raise ValueError("실행에 쓴 평가셋과 지금 평가셋 파일의 지문이 다르다 — 그 버전의 평가셋 파일로 채점한다")
    answers = read_answers(run_dir)
    judgments = load_judgments(judgments_path)
    rows = [score_record(item, answers.get(item["id"]), judgments) for item in items]

    def write(name, chosen):
        (run_dir / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in chosen),
                                    encoding="utf-8")

    write(DEV_RESULTS, [row for row in rows if row["part"] != "test"])
    write(TEST_RESULTS, [row for row in rows if row["part"] == "test"])
    write(AMBIGUOUS, [{"key": row["key"], "id": row["id"], "part": row["part"], "question": row["question"],
                       "answer": row["answer"], "rule_label": row["rule_label"], "doubt": row.get("doubt")}
                      for row in rows if row.get("status") == "채점" and row["label"] == "애매"])
    metrics = {"manifest": {key: manifest.get(key) for key in ("evalset_version", "evalset_sha256", "index", "top_k",
                                                               "system_prompt_sha256", "git_commit", "runtime")},
               "groups": {}}
    for set_name in ("본", "쉬운"):
        for part in ("dev", "test"):
            chosen = [row for row in rows if row["set"] == set_name and row["part"] == part]
            if not chosen:
                continue
            metrics["groups"][f"{set_name}/{part}"] = {
                **aggregate(chosen), "by_shape": breakdown(chosen, "shape"), "by_topic": breakdown(chosen, "topic"),
                "by_tag": breakdown(chosen, "tags")}
    (run_dir / METRICS).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def summary_lines(metrics: dict) -> list[str]:
    """화면용 요약. 문항별 결과는 넣지 않는다(테스트셋 봉인)."""

    def pct(entry):
        if not entry or entry["rate"] is None:
            return "—"
        low, high = entry["ci95"]
        return f"{entry['rate'] * 100:.1f}% ({entry['k']}/{entry['n']}, 95% {low * 100:.0f}~{high * 100:.0f}%)"

    lines = []
    for name, group in metrics["groups"].items():
        lines.append(f"[{name}] 채점 {group['scored']}/{group['items']} · 미실행 {group['not_run']} · 실패 {group['failed']}")
        lines.append(f"  정답률 {pct(group['accuracy'])} · 일부 {pct(group['partial'])} · 과잉 거절 {pct(group['over_refusal'])}")
        lines.append(f"  환각률 {pct(group['hallucination'])} · 답없음 거절 {pct(group['unanswerable_refusal'])}")
        lines.append(f"  출처 정확도 {pct(group['source_hit'])} · 출처 중 허용 근거 {group['source_share']}"
                     f" · 안내 충실도 {pct(group['guidance'])}")
        lines.append(f"  애매(사람 판정 대기) {group['ambiguous_open']} · 사람 판정 재사용 {group['judged']}"
                     f" · 규칙 맞음 중 판정으로 보냄 {group['doubted']} · 덧붙인 거절 {group['appended_refusal']} · 지어낸 숫자 {group['invented_numbers']}"
                     f" · 답 잘림 {group['truncated']}")
        lines.append("  실패 위치 " + " · ".join(f"{key} {value}" for key, value in sorted(group["locations"].items())))
    return lines
