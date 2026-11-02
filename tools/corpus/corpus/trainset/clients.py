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


def attach(session, ai_url: str, question: str, top_k: int = 8, timeout: float = 600.0) -> dict:
    """데이터셋 AI 서버에 질문을 묻고 운영 프롬프트·근거 8개·학습 전 A.X 답을 받는다.

    평가 실행기와 같은 요청이다(`evalset run`). 모델을 거치지 않는 우선 경로 답이면 프롬프트가 없어 실패로 돌려준다.
    """
    response = session.post(f"{ai_url.rstrip('/')}/query", timeout=timeout,
                            json={"question": question, "top_k": top_k, "system_prompt": None, "include_eval_trace": True})
    response.raise_for_status()
    body = response.json()
    trace = body.get("eval_trace")
    if not trace:
        raise ValueError("AI 서버가 평가용 기록(eval_trace)을 돌려주지 않는다")
    if trace.get("answer_path") != "llm" or not trace.get("prompt"):
        raise ValueError(f"생성 모델을 거치지 않은 답(answer_path={trace.get('answer_path')})")
    final = (trace.get("stages") or {}).get("final") or []
    return {"prompt": trace["prompt"], "context": trace.get("context") or "",
            "retrieved": [{key: candidate.get(key) for key in ("chunk_id", "document_id", "ledger_id", "chunk_index",
                                                                 "chunk_role")} for candidate in final],
            "ax_answer": body.get("answer"), "runtime": trace.get("runtime")}
