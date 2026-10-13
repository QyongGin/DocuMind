"""생성만 다시 돌리기(M1 13번 2단계 평가, ADR-0004): 기준 실행에 기록된 프롬프트를 다른 생성 모델에 그대로 넣는다.

검색·프롬프트 조립은 기준 실행과 같고 생성 모델(과 문맥 길이)만 바뀐다. AI 서버는 모델 답을 고치지 않고 돌려주므로
(`ai-server/main.py` `_generate_answer`), Ollama 생성 API에 같은 프롬프트·같은 옵션(온도·출력 상한, 사고 모드 끔)을
주면 서버가 그 모델로 답한 것과 같다. 모델을 거치지 않는 우선 경로 답(표 사실·질문 맞춤 근거)은 모델과 무관해 그대로 옮긴다.

결과 폴더는 실행 폴더와 같은 모양이라 `score-run`(평가셋 판이 다르면 `--rescore`)과 `compare-runs`를 그대로 쓴다.
실행 기록에는 어느 실행에서 프롬프트를 가져왔는지(`generated_from`)와 바꾼 생성 설정을 남긴다. 같은 폴더로 다시 실행하면
이미 받은 문항은 건너뛴다.
"""

import copy
import json
import time
from datetime import datetime
from pathlib import Path

import requests

from .runner import ANSWERS, MANIFEST, read_answers

LLM_PATH = "llm"
FIXED = ("generated_from", "evalset_sha256", "llm_model", "num_ctx", "num_predict", "llm_temperature")


def regenerate(base_dir: str | Path, out_dir: str | Path, ollama_url: str, model: str, num_ctx: int,
               num_predict: int | None = None, ids: list[str] | None = None, limit: int | None = None,
               session=None, timeout: float = 600.0, keep_alive: str = "30m",
               now=lambda: datetime.now().isoformat(timespec="seconds"), clock=time.perf_counter, log=print) -> dict:
    """기준 실행의 문항을 차례로 다시 생성한다. 돌려주는 것: 생성·옮김(우선 경로)·건너뜀·실패 수, 잘린 프롬프트 수."""
    base_dir, out_dir = Path(base_dir), Path(out_dir)
    if base_dir.resolve() == out_dir.resolve():
        raise ValueError("결과는 기준 실행 폴더 밖에 쓴다")
    base_manifest = json.loads((base_dir / MANIFEST).read_text(encoding="utf-8"))
    base_runtime = base_manifest.get("runtime") or {}
    temperature = base_runtime.get("llm_temperature", 0.0)
    num_predict = num_predict or base_runtime.get("num_predict") or 512
    runtime = {**base_runtime, "llm_model": model, "num_ctx": num_ctx, "num_predict": num_predict}

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / MANIFEST
    fresh = {**base_manifest, "mode": "생성만", "generated_from": base_dir.name, "ollama_url": ollama_url.rstrip("/"),
             "runtime": runtime, "started_at": now(), "finished_at": None, "counts": None}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        different = [key for key in FIXED if _fixed(manifest, key) != _fixed(fresh, key)]
        if different:
            raise ValueError(f"결과 폴더의 실행 기록과 조건이 다르다({', '.join(different)}). 새 결과 폴더를 쓴다")
    else:
        manifest = fresh
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    base = read_answers(base_dir)
    chosen = sorted(item_id for item_id, record in base.items() if "error" not in record)
    if ids:
        chosen = [item_id for item_id in chosen if item_id in set(ids)]
    chosen = chosen[:limit] if limit else chosen
    done = {item_id for item_id, record in read_answers(out_dir).items() if "error" not in record}
    todo = [item_id for item_id in chosen if item_id not in done]
    session = session or requests.Session()
    counts = {"generated": 0, "copied": 0, "skipped": len(chosen) - len(todo), "errors": 0, "truncated": 0}
    with (out_dir / ANSWERS).open("a", encoding="utf-8") as out:
        for number, item_id in enumerate(todo, 1):
            record = copy.deepcopy(base[item_id])
            trace = record.get("eval_trace") or {}
            if trace.get("answer_path") != LLM_PATH:
                counts["copied"] += 1  # 우선 경로 답은 모델을 거치지 않는다
            else:
                started = clock()
                try:
                    response = session.post(f"{manifest['ollama_url']}/api/generate", timeout=timeout, json={
                        "model": model, "prompt": trace["prompt"], "stream": False, "think": False,
                        "keep_alive": keep_alive,
                        "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict}})
                    response.raise_for_status()
                    body = response.json()
                    generation = {key: body.get(key) for key in ("done_reason", "eval_count", "prompt_eval_count",
                                                                 "eval_duration", "prompt_eval_duration")}
                    # 프롬프트가 문맥을 다 채우면 Ollama가 앞을 잘라 낸다 — 큰 문맥 비교에서는 0이어야 한다
                    generation["prompt_truncated"] = (body.get("prompt_eval_count") or 0) >= num_ctx - 1
                    counts["truncated"] += generation["prompt_truncated"]
                    record.update(answer=body.get("response"),
                                  eval_trace={**trace, "generation": generation, "runtime": runtime})
                    record.pop("error", None)
                    counts["generated"] += 1
                except (requests.RequestException, ValueError, KeyError) as error:
                    record = {"id": item_id, "rev": record.get("rev"), "question": record.get("question"),
                              "error": str(error)}
                    counts["errors"] += 1
                record["elapsed"] = round(clock() - started, 3)
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            if log and (number % 10 == 0 or number == len(todo)):
                log(f"{number}/{len(todo)} · 실패 {counts['errors']} · 잘림 {counts['truncated']}")
    latest = read_answers(out_dir)
    manifest["finished_at"] = now()
    manifest["counts"] = {"answered": sum(1 for record in latest.values() if "error" not in record),
                          "errors": sum(1 for record in latest.values() if "error" in record)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts


def _fixed(manifest: dict, key: str):
    return (manifest.get("runtime") or {}).get(key) if key in ("llm_model", "num_ctx", "num_predict", "llm_temperature") \
        else manifest.get(key)
