"""초안 모델(Ollama 생성 API)과 데이터셋 AI 서버(/query 평가용 옵션)를 부른다."""

from __future__ import annotations

import json
import re


def generate(session, ollama_url: str, model: str, prompt: str, *, temperature: float, num_ctx: int,
             num_predict: int, json_mode: bool = False, timeout: float = 600.0, keep_alive: str = "30m") -> dict:
    """Ollama 생성 API를 한 번 부른다. 사고 모드는 끈다. 돌려주는 것: 글과 생성 기록(종료 이유·토큰 수)."""
    body = {"model": model, "prompt": prompt, "stream": False, "think": False, "keep_alive": keep_alive,
            "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict}}
    if json_mode:
        body["format"] = "json"
    response = session.post(f"{ollama_url.rstrip('/')}/api/generate", json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return {"text": data.get("response") or "",
            "generation": {key: data.get(key) for key in ("model", "done_reason", "eval_count", "prompt_eval_count")}}


def parse_json(text: str) -> dict:
    """모델이 JSON 앞뒤에 글을 붙여도 첫 JSON 객체를 꺼낸다."""
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def server_runtime(session, ai_url: str, question: str, timeout: float = 600.0) -> dict:
    """AI 서버의 실행 설정(근거 수, 문맥 길이, 답 상한, 입력 틀 판 번호 등). 답을 만들지 않는 검색 추적(/debug/rag-trace)으로
    받는다(#275) — 도구 쪽에 근거 수 같은 숫자를 따로 두지 않는다. question은 검색에만 쓰는 아무 질문이다."""
    response = session.post(f"{ai_url.rstrip('/')}/debug/rag-trace", timeout=timeout, json={"question": question})
    response.raise_for_status()
    runtime = response.json().get("runtime")
    if not runtime or runtime.get("prompt_template_version") is None or not runtime.get("default_top_k"):
        raise ValueError("AI 서버가 실행 설정(입력 틀 판 번호·근거 수)을 주지 않는다 — #275 이후 판인지 본다")
    return runtime


def attach(session, ai_url: str, question: str, timeout: float = 600.0,
           exclude_ledger_ids: list[str] | None = None, exclude_chunk_ids: list[str] | None = None,
           as_of: str | None = None, require_rerank: bool = False,
           pinned_chunks: list[dict] | None = None) -> dict:
    """데이터셋 AI 서버에 질문을 묻고 운영 프롬프트·근거·학습 전 A.X 답을 받는다.

    평가 실행기와 같은 요청이다(`evalset run`). 프롬프트는 서버가 준 글 그대로 쓰고 고치지 않는다(#275). 근거 수는 보내지
    않아 서버 기본값을 쓰고, 문맥 길이·답 상한·근거 수·입력 틀 판 번호는 응답의 실행 설정(runtime)에 있다.
    모델을 거치지 않는 우선 경로 답이면 프롬프트가 없어 실패로 돌려준다.
    뺄 문서(대장 번호)·뺄 원문 청크·기준 날짜·지정 청크(청크 id와 자리)는 AI 서버의 평가 전용 칸이다(ADR-0047·0048, #275).
    주지 않으면 보내지 않는다. 보낸 요청(request)을 함께 돌려줘, 학습 파일의 프롬프트를 서버에 다시 요청해 대조할 수 있게 한다.
    재순위 기록(켜짐·사용 여부·실패 이유)을 함께 돌려준다. require_rerank면 재순위가 실제로 쓰이지 않은 근거를 실패로
    돌려준다: 재순위 서버가 답하지 않으면 AI 서버는 순위 융합 순서 그대로 답하기 때문이다(ADR-0055 결정 1).
    후보별 단계 순위(retrieval)와 표 블록 목록(table_blocks), 조립에 넣은 후보 수(considered)도 돌려준다(#275).
    프롬프트 길이 상한 때문에 뺀 청크(limit_dropped_chunk_ids, 그 블록에 합쳐져 있던 청크는
    limit_dropped_merged_chunk_ids)와 블록 하나만 남아 끝 줄을 자른 줄 수(truncated_lines, 안 잘랐으면 None)도 옮긴다.
    """
    request = {"question": question, "system_prompt": None}
    for key, value in (("exclude_ledger_ids", exclude_ledger_ids), ("exclude_chunk_ids", exclude_chunk_ids),
                       ("as_of", as_of), ("pinned_chunks", pinned_chunks)):
        if value:
            request[key] = value
    response = session.post(f"{ai_url.rstrip('/')}/query", timeout=timeout, json={**request, "include_eval_trace": True})
    response.raise_for_status()
    body = response.json()
    trace = body.get("eval_trace")
    if not trace:
        raise ValueError("AI 서버가 평가용 기록(eval_trace)을 돌려주지 않는다")
    if trace.get("answer_path") != "llm" or not trace.get("prompt"):
        raise ValueError(f"생성 모델을 거치지 않은 답(answer_path={trace.get('answer_path')})")
    runtime = trace.get("runtime") or {}
    if runtime.get("prompt_template_version") is None:
        raise ValueError("AI 서버가 입력 틀 판 번호를 주지 않는다 — #275 이후 판인지 본다")
    rerank = trace.get("rerank")
    if require_rerank and not (rerank or {}).get("used"):
        raise ValueError(f"재순위가 쓰이지 않은 근거(rerank={rerank})")
    stages = trace.get("stages") or {}
    table_stage = stages.get("table_block") or {}
    final = stages.get("final") or []
    documents = {str(candidate.get("chunk_id")): str(candidate.get("document_id")) for candidate in final}
    table_blocks = [{"block": block.get("block"), "chunk_id": block.get("chunk_id"),
                     "document_id": documents.get(str(block.get("chunk_id"))),
                     "table_numbers": block.get("table_numbers") or [], "table_block": bool(block.get("table_block"))}
                    for block in table_stage.get("blocks") or []]
    retrieved = [{key: candidate.get(key) for key in ("chunk_id", "document_id", "ledger_id", "chunk_index", "chunk_role")}
                 for candidate in final]
    # 근거 블록 [출처 N]마다 그 블록이 된 청크. 표 블록이 켜지면 같은 표의 뒤 순위 청크가 앞 블록에 합쳐져 빠지므로
    # retrieved의 N번째가 [출처 N]이 아니다. 서버가 후보마다 남긴 블록 번호로 잇는다
    block_of = {str(entry.get("chunk_id")): entry.get("block") for entry in trace.get("retrieval") or [] if entry.get("block")}
    blocks = sorted(({**entry, "block": block_of[str(entry["chunk_id"])]} for entry in retrieved
                     if block_of.get(str(entry["chunk_id"]))), key=lambda entry: entry["block"])
    return {"prompt": trace["prompt"], "context": trace.get("context") or "", "rerank": rerank,
            "retrieved": retrieved, "blocks": blocks,
            "retrieval": trace.get("retrieval") or [], "pinned": trace.get("pinned"), "table_blocks": table_blocks,
            "dropped_chunk_ids": table_stage.get("dropped_chunk_ids") or [],
            # 프롬프트 길이 상한 때문에 뺀 블록의 청크, 그 블록에 합쳐져 있던 청크, 블록 하나만 남아 자른 줄 수
            "limit_dropped_chunk_ids": table_stage.get("limit_dropped_chunk_ids") or [],
            "limit_dropped_merged_chunk_ids": table_stage.get("limit_dropped_merged_chunk_ids") or [],
            "truncated_lines": table_stage.get("truncated_lines"),
            "considered": len(final), "ax_answer": body.get("answer"), "runtime": runtime, "request": request}
