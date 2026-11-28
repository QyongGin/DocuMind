"""학습 파일 대조(#275): 학습 파일의 프롬프트를 AI 서버에 같은 요청으로 다시 받아 글자까지 같은지 본다.

학습 입력은 서버가 준 프롬프트를 고치지 않고 쓴다. 학습 파일을 손으로 고쳤거나 서버의 입력 틀·색인·설정이 바뀌어 운영
입력과 학습 입력이 어긋났는지를 이 대조로 잡는다. 요청은 학습 파일 meta.request(근거를 붙일 때 보낸 그대로)를 쓴다.
서버 /query로 다시 받으므로 예시마다 학습 전 모델의 답 생성이 한 번 돈다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from . import clients


def first_difference(left: str, right: str) -> int:
    """두 글이 처음 달라지는 글자 위치(같으면 -1)."""
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return -1 if len(left) == len(right) else min(len(left), len(right))


def verify_file(path: Path, session, ai_url: str, limit: int | None = None,
                log: Callable[[str], None] = print) -> dict:
    """학습 파일 한 줄씩 서버에 다시 요청해 프롬프트를 대조한다. 돌려주는 것: 같음·다름·요청 기록 없음·실패 수와
    다른 줄마다 (예시 번호, 처음 달라진 위치, 그 앞뒤 글, 판 번호가 같은지)."""
    lines = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    lines = lines[:limit] if limit else lines
    result = {"lines": len(lines), "same": 0, "different": [], "no_request": [], "errors": []}
    for line in lines:
        meta = line.get("meta") or {}
        request = meta.get("request")
        if not request:
            result["no_request"].append(line["id"])
            continue
        prompt = line["messages"][0]["content"]
        try:
            again = clients.attach(session, ai_url, **{"question": request["question"],
                                                       **{key: value for key, value in request.items()
                                                          if key not in ("question", "system_prompt")}})
        except (ValueError, KeyError, OSError) as error:
            result["errors"].append({"id": line["id"], "error": str(error)})
            continue
        if again["prompt"] == prompt:
            result["same"] += 1
            continue
        at = first_difference(prompt, again["prompt"])
        result["different"].append({
            "id": line["id"], "at": at, "file": prompt[max(0, at - 20): at + 20], "server": again["prompt"][max(0, at - 20): at + 20],
            "same_template_version": again["runtime"].get("prompt_template_version") == meta.get("prompt_template_version")})
        log(f"다름 {line['id']}: {at}번째 글자부터")
    return result


def ok(result: dict) -> bool:
    return result["lines"] > 0 and result["same"] == result["lines"]
