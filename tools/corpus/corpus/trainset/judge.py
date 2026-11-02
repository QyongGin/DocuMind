"""Claude 판정(ADR-0037): 자동 검사를 통과한 예시마다 통과·탈락과 이유 한 줄만 받는다. 글은 고치지 않는다.

평가셋 이중 라벨링과 같은 격리 실행을 쓴다(`evalset.double_annotation`): 저장소 밖 임시 폴더의 작업 단위 안에서
`claude -p`를 읽기 도구만 주고, 사용자 맞춤·MCP·대화 저장 없이 돌린다. Claude가 쓴 글은 학습 데이터에 들어가지 않는다(ADR-0010).
"""

from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..evalset.double_annotation import DEFAULT_MODEL, claude_command, claude_version, repo_marker, run_claude
from .plan import KINDS

PER_PACKET = 8
VERDICTS = ("통과", "탈락")
CATEGORIES = ("값 틀림", "근거 없음", "거절 오류", "확인처 오류", "일부 구분 오류", "질문 어색", "안내 빠짐", "기타")

# 판정 지침. 바꾸면 이전 판정과 나란히 비교할 수 없으니 판을 올리고 기록에 남긴다
GUIDE_VERSION = "2026-10-21"
PROMPT = f"""너는 대학 안내 챗봇이 배울 학습 예시를 판정한다. 이 폴더 밖의 파일은 읽지 않는다. 예시를 고쳐 쓰지 않는다.

examples.json의 예시마다 '챗봇 입력'(챗봇이 받는 글: 답변 규칙·[검색 근거]·[사용자 질문])과 '목표 답'(챗봇이 배울 답)이 있다.
아래를 모두 지키면 "통과", 하나라도 어기면 "탈락"이다.

1. 목표 답의 결론이 질문이 묻는 것(대상·학년도·학기·표의 행과 열)에 맞는 근거에서 왔다.
2. 목표 답의 날짜·숫자·금액·연락처·방법이 모두 [검색 근거]에 있고, 끝의 [출처 N]이 그 내용이 있는 근거 번호다.
3. 종류가 '답'이나 '일부만 있음'인데 근거에 답이 없으면 탈락. 종류가 '거절'인데 근거에 질문의 답이 있으면 탈락.
4. 거절에 덧붙인 부서·연락처·사이트는 근거에 있고 질문한 일과 관련 있다.
5. '일부만 있음'은 근거에 있는 것과 없는 것을 맞게 갈랐다.
6. 질문은 그 사용자가 챗봇에 실제로 쓸 만한 자연스러운 한국어다. 문서 문장을 그대로 베낀 질문은 탈락.
7. 근거에 그 일의 신청 방법·기한·문의처가 있는데 목표 답이 빠뜨렸으면 탈락(안내 빠짐). 질문과 상관없는 안내는 빠져도 된다.
'자동 검사 메모'가 있으면 그 점을 먼저 확인한다.

출력은 JSON 하나만 쓴다: {{"verdicts": [{{"id": "예시 번호", "verdict": "통과" 또는 "탈락", "category": "{'·'.join(CATEGORIES)} 중 하나(통과면 빈 글)", "reason": "판단 근거 한 줄"}}]}}. 모든 예시를 판정한다.
"""


class JudgeError(Exception):
    """작업 단위를 만들거나 판정 결과를 읽지 못함."""


def example(record: dict) -> dict:
    """판정 세션에 주는 예시 하나. 답 근거·학습 전 A.X 답은 주지 않는다(판정이 거기에 끌리지 않게)."""
    return {"id": record["id"], "종류": KINDS[record["kind"]].label, "사용자": record.get("user_actual") or record["user"],
            "챗봇 입력": record["prompt"], "목표 답": record["target_ga"],
            "자동 검사 메모": (record.get("result") or {}).get("ga", {}).get("judge_notes") or []}


def packets(records: list[dict], per_packet: int = PER_PACKET) -> list[list[dict]]:
    return [records[start:start + per_packet] for start in range(0, len(records), per_packet)]


def parse_output(stdout: str, ids: list[str]) -> list[dict]:
    """`claude -p --output-format json` 출력에서 판정 목록을 꺼내고, 모든 예시를 정해진 값으로 판정했는지 본다."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise JudgeError(f"Claude Code 출력이 JSON이 아님: {stdout[:200]!r}") from error
    if envelope.get("is_error"):
        raise JudgeError(f"Claude Code 오류: {envelope.get('result')}")
    match = re.search(r"\{.*\}", str(envelope.get("result") or ""), re.S)
    if not match:
        raise JudgeError("판정에 JSON이 없음")
    try:
        verdicts = json.loads(match.group(0)).get("verdicts")
    except (json.JSONDecodeError, AttributeError) as error:
        raise JudgeError("판정 JSON을 읽지 못함") from error
    if not isinstance(verdicts, list):
        raise JudgeError("verdicts는 목록이어야 함")
    by_id = {entry.get("id"): entry for entry in verdicts if isinstance(entry, dict)}
    missing = [item_id for item_id in ids if item_id not in by_id]
    bad = [item_id for item_id, entry in by_id.items() if item_id in ids and entry.get("verdict") not in VERDICTS]
    if missing or bad:
        raise JudgeError(f"판정이 빠짐 {missing} · 값이 틀림 {bad}")
    return [{"id": item_id, "verdict": by_id[item_id]["verdict"], "category": str(by_id[item_id].get("category") or ""),
             "reason": str(by_id[item_id].get("reason") or "")} for item_id in ids]


def run(records: list[dict], work: Path, model: str = DEFAULT_MODEL, runner: Callable = run_claude,
        jobs: int = 2, per_packet: int = PER_PACKET) -> tuple[list[dict], list[tuple[str, str]]]:
    """작업 단위마다 판정 세션을 돌린다. 돌려주는 것: 판정 목록, 실패한 작업 단위(이름, 이유). work는 저장소 밖이어야 한다."""
    work = Path(work)
    marker = repo_marker(work)
    if marker:
        raise JudgeError(f"작업 폴더가 저장소 안이다({marker}) — 저장소의 CLAUDE.md가 읽힌다")
    label = f"{model} · Claude Code {claude_version(runner)} · 판정 지침 {GUIDE_VERSION}"
    command = claude_command(model, PROMPT)
    groups = packets(records, per_packet)
    for number, group in enumerate(groups, 1):
        folder = work / f"packet-{number:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "examples.json").write_text(json.dumps([example(record) for record in group], ensure_ascii=False,
                                                         indent=1), encoding="utf-8")

    def execute(numbered):
        number, group = numbered
        try:
            return number, group, runner(command, work / f"packet-{number:03d}"), None
        except (OSError, subprocess.SubprocessError) as error:
            return number, group, None, str(error)

    results, failed = [], []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for number, group, completed, error in pool.map(execute, enumerate(groups, 1)):
            name = f"packet-{number:03d}"
            try:
                if error:
                    raise JudgeError(error)
                verdicts = parse_output(completed.stdout or "", [record["id"] for record in group])
            except JudgeError as problem:
                failed.append((name, str(problem)))
                continue
            results += [{**verdict, "judge": label, "packet": name} for verdict in verdicts]
    return results, failed
