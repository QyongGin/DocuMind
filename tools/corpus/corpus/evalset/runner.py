"""평가 실행기(M1 11번): 평가셋 질문을 AI 서버 `/query`(평가용 옵션 `include_eval_trace`)에 묻고 실행 폴더에 쌓는다.

실행 폴더
    manifest.json   실행 기록: 평가셋 지문·버전, 색인, top_k, 시스템 프롬프트(지문 포함), 코드 커밋, 서버 설정, 시각
    answers.jsonl   문항마다 한 줄: 답·출처·평가용 기록(단계별 후보·문맥·프롬프트·생성 종료 이유)·걸린 초, 실패면 error

같은 폴더로 다시 실행하면 이미 받은 문항은 건너뛰고 실패한 문항만 다시 묻는다(데스크탑이 꺼져도 이어서). 평가셋·색인·
top_k·시스템 프롬프트가 실행 기록과 다르면 거부한다 — 한 실행 폴더에 다른 조건의 답이 섞이지 않게.
백엔드 채팅 API를 거치지 않는 이유(채팅 기록 오염, 단계별 후보 없음)는 `docs/rag/m1/채점기-설계-20261012.md` §4.
"""

import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests

from . import schema

MANIFEST = "manifest.json"
ANSWERS = "answers.jsonl"
DEFAULT_TOP_K = 5  # 백엔드·프론트·AI 서버 운영 기본값(.env.example)
FIXED = ("evalset_sha256", "index", "top_k", "system_prompt_sha256")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_commit(repo: Path) -> dict:
    """실행 기록용 코드 커밋. git이 없거나 저장소가 아니면 비워 둔다."""
    try:
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True,
                                    check=True).stdout.strip())
        return {"git_commit": commit, "git_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None}


def targets(items: list[dict], ids: list[str] | None = None, limit: int | None = None) -> list[dict]:
    """물을 문항: 버린 문항은 빼고 ID 순. ids를 주면 그 문항만, limit을 주면 앞에서부터 그만큼."""
    chosen = sorted((item for item in items if not schema.dropped(item)), key=lambda item: item["id"])
    if ids:
        wanted = set(ids)
        chosen = [item for item in chosen if item["id"] in wanted]
    return chosen[:limit] if limit else chosen


def read_answers(run_dir: Path) -> dict[str, dict]:
    """문항마다 마지막 줄(다시 물은 결과가 앞의 실패를 덮는다)."""
    path = Path(run_dir) / ANSWERS
    latest: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                latest[record["id"]] = record
    return latest


def new_manifest(evalset_path: Path, items: list[dict], index: str, top_k: int, system_prompt: str | None,
                 ai_url: str, version: str | None, repo: Path, started_at: str) -> dict:
    return {
        "evalset": str(evalset_path),
        "evalset_version": version,
        "evalset_sha256": schema.fingerprint(items),
        "index": index,
        "top_k": top_k,
        "system_prompt": system_prompt,  # None이면 AI 서버 기본 프롬프트(백엔드 기본값과 같음)
        "system_prompt_sha256": sha256(system_prompt or ""),
        "ai_url": ai_url,
        **git_commit(repo),
        "runtime": None,  # 첫 응답의 eval_trace.runtime(모델·온도·문맥·출력 상한)
        "started_at": started_at,
        "finished_at": None,
        "counts": None,
    }


def run(evalset_path: str | Path, run_dir: str | Path, ai_url: str, index: str, top_k: int = DEFAULT_TOP_K,
        system_prompt: str | None = None, version: str | None = None, ids: list[str] | None = None,
        limit: int | None = None, session=None, timeout: float = 600.0, repo: str | Path | None = None,
        now=lambda: datetime.now().isoformat(timespec="seconds"), clock=time.perf_counter, log=print) -> dict:
    """질문을 차례로 묻는다(동시에 묻지 않음: GPU 하나, 같은 순서·같은 조건). 돌려주는 것: 물음·건너뜀·실패 수."""
    evalset_path, run_dir = Path(evalset_path), Path(run_dir)
    items = schema.load(evalset_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / MANIFEST
    fresh = new_manifest(evalset_path, items, index, top_k, system_prompt, ai_url.rstrip("/"), version,
                         Path(repo) if repo else evalset_path.parent, now())
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        different = [key for key in FIXED if manifest.get(key) != fresh[key]]
        if different:
            raise ValueError(f"실행 기록과 조건이 다르다({', '.join(different)}). 새 실행 폴더를 쓴다")
    else:
        manifest = fresh
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    session = session or requests.Session()
    done = {item_id for item_id, record in read_answers(run_dir).items() if "error" not in record}
    todo = [item for item in targets(items, ids, limit) if item["id"] not in done]
    errors = 0
    with (run_dir / ANSWERS).open("a", encoding="utf-8") as out:
        for number, item in enumerate(todo, 1):
            started = clock()
            record = {"id": item["id"], "rev": item.get("rev", 1), "question": item["question"]}
            try:
                response = session.post(f"{manifest['ai_url']}/query", timeout=timeout, json={
                    "question": item["question"], "top_k": top_k, "system_prompt": system_prompt,
                    "include_eval_trace": True})
                response.raise_for_status()
                body = response.json()
                if "eval_trace" not in body:
                    raise ValueError("AI 서버가 평가용 기록(eval_trace)을 돌려주지 않는다 — PR #156 이후 판인지 본다")
                record.update(answer=body.get("answer"), sources=body.get("sources") or [], eval_trace=body["eval_trace"])
                if manifest["runtime"] is None:
                    manifest["runtime"] = body["eval_trace"].get("runtime")
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            except (requests.RequestException, ValueError) as error:
                record["error"] = str(error)
                errors += 1
            record["elapsed"] = round(clock() - started, 3)
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            if log and (number % 10 == 0 or number == len(todo)):
                log(f"{number}/{len(todo)} · 실패 {errors}")
    latest = read_answers(run_dir)
    manifest["finished_at"] = now()
    manifest["counts"] = {"answered": sum(1 for record in latest.values() if "error" not in record),
                          "errors": sum(1 for record in latest.values() if "error" in record)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"asked": len(todo), "skipped": len(done), "errors": errors}
