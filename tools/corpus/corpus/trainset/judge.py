"""Claude 판정(ADR-0037): 자동 검사를 통과한 예시마다 통과·탈락과 이유 한 줄만 받는다. 글은 고치지 않는다.
4회차 선호 쌍(ADR-0053)에서는 규칙으로 못 가른 3회차 답도 같은 방식으로 판정한다(run_answers).

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
from .evidence import evidence_section
from .plan import KINDS
from .prompts import AMBIGUOUS_RULE

PER_PACKET = 8
VERDICTS = ("통과", "탈락")
CATEGORIES = ("값 틀림", "근거 없음", "거절 오류", "확인처 오류", "일부 구분 오류", "질문 어색", "안내 빠짐", "기타")

# 판정 지침. 바꾸면 이전 판정과 나란히 비교할 수 없으니 판을 올리고 기록에 남긴다
GUIDE_VERSION = "2026-11-01"
PROMPT = f"""너는 대학 안내 챗봇이 배울 학습 예시를 판정한다. 이 폴더 밖의 파일은 읽지 않는다. 예시를 고쳐 쓰지 않는다.

examples.json의 예시마다 '챗봇 입력'(챗봇이 받는 글: 답변 규칙·[검색 근거]·[사용자 질문])과 '목표 답'(챗봇이 배울 답)이 있다.
아래를 모두 지키면 "통과", 하나라도 어기면 "탈락"이다.

1. 목표 답의 결론이 질문이 묻는 것(대상·학년도·학기·표의 행과 열)에 맞는 근거에서 왔다.
2. 목표 답의 날짜·숫자·금액·연락처·방법이 모두 [검색 근거]에 있고, 끝의 [출처 N]이 그 내용이 있는 근거 번호다.
3. 종류가 '답'이나 '일부만 있음'인데 근거에 답이 없으면 탈락. 종류가 '거절'인데 근거에 질문의 답이 있으면 탈락.
4. 거절에 덧붙인 부서·연락처·사이트는 근거에 있고 질문한 일과 관련 있다.
5. '일부만 있음'은 근거에 있는 것과 없는 것을 맞게 갈랐다.
6. 질문은 그 사용자가 챗봇 입력창에 실제로 쓸 만한 말이다. 검색어처럼 낱말만 쓰거나 줄임말·반말이어도 된다. 문서 문장을 그대로 베꼈거나 묻는 사람이 모를 공식 명칭을 그대로 옮긴 질문은 탈락.
7. 근거에 그 일의 신청 방법·기한·문의처가 있는데 목표 답이 빠뜨렸으면 탈락(안내 빠짐). 질문과 상관없는 안내는 빠져도 된다.
8. 목표 답이 이 규칙을 지켰다: {AMBIGUOUS_RULE} 오늘 유효한 판이 있는데 지난 판으로 답했거나, 다른 대상의 근거로 답했거나, 밝혀야 할 기준·이름을 밝히지 않았거나, 근거 문서에 없는 학년도·학기를 기준으로 썼으면 탈락. 잘 바뀌지 않는 사실에 기준이 없는 것은 탈락 사유가 아니다.
'자동 검사 메모'가 있으면 그 점을 먼저 확인한다.

출력은 JSON 하나만 쓴다: {{"verdicts": [{{"id": "예시 번호", "verdict": "통과" 또는 "탈락", "category": "{'·'.join(CATEGORIES)} 중 하나(통과면 빈 글)", "reason": "판단 근거 한 줄"}}]}}. 모든 예시를 판정한다.
"""


# 3회차 답 판정(4회차 선호 쌍, ADR-0053). 새 평가 데이터 판정과 같은 판정 값·기준으로, 정답 자리에 판정을 통과한 목표 답을
# 준다. 규칙(pairs.classify)으로 못 가른 답만 받는다
ANSWER_GUIDE_VERSION = "2026-11-03"
ANSWER_VERDICTS = ("맞음", "일부", "틀림", "거절 맞음", "과잉 거절", "근거 있음")
ANSWER_PROMPT = """너는 대학 안내 챗봇의 답을 목표 답과 비교해 판정한다. 이 폴더 밖의 파일은 읽지 않는다. 답을 고쳐 쓰지 않는다.

examples.json의 답마다 '종류'(답·일부만 있음·답 없음), '질문', '목표 답'(판정을 통과한 모범 답), '검색 근거'(챗봇이 받은 근거), '챗봇 답'이 있다.
- 맞음: 결론이 목표 답과 같고 목표 답의 핵심 값이 모두 맞다(표기가 조금 달라도 같은 값이면 맞음). 종류가 일부만 있음이면 있는 것은 답하고 없는 것은 찾지 못했다고 했다.
- 일부: 결론은 맞지만 핵심 값 일부가 빠졌다. 또는 찾지 못했다고 먼저 말하고 뒤에 목표 답의 결론을 붙였다.
- 틀림: 목표 답과 다른 값·다른 대상·지어낸 내용을 결론으로 단정했다. 종류가 답 없음인데 값을 단정하거나, 일부만 있음에서 없는 것에 값을 단정해도 틀림.
- 거절 맞음: 종류가 답 없음이고 찾지 못했다고 거절했다(다른 정보를 다른 것이라고 밝혀 덧붙여도 거절 맞음).
- 과잉 거절: 종류가 답이나 일부만 있음인데 찾지 못했다고만 했다.
- 근거 있음: 종류가 답 없음인데 검색 근거에 질문의 답이 분명히 있다. 챗봇 답과 상관없이 근거만 보고 정한다.

출력은 JSON 하나만 쓴다: {"verdicts": [{"id": "답 번호", "verdict": "맞음·일부·틀림·거절 맞음·과잉 거절·근거 있음 중 하나", "reason": "판단 근거 한 줄"}]}. 모든 답을 판정한다.
"""


class JudgeError(Exception):
    """작업 단위를 만들거나 판정 결과를 읽지 못함."""


def example(record: dict) -> dict:
    """판정 세션에 주는 예시 하나. 답 근거·학습 전 A.X 답은 주지 않는다(판정이 거기에 끌리지 않게)."""
    return {"id": record["id"], "종류": KINDS[record["kind"]].label, "사용자": record.get("user_actual") or record["user"],
            "챗봇 입력": record["prompt"], "목표 답": record["target_ga"],
            "자동 검사 메모": (record.get("result") or {}).get("ga", {}).get("judge_notes") or []}


def answer_example(record: dict, number: int, answer: str) -> dict:
    """답 판정 세션에 주는 답 하나. 번호는 '<예시 번호>#<몇 번째 답>'이다. 근거는 운영 프롬프트의 [검색 근거]만 준다."""
    kind = ("일부만 있음" if record["kind"] == "partial" else "답") if KINDS[record["kind"]].answerable else "답 없음"
    return {"id": answer_id(record["id"], number), "종류": kind, "질문": record.get("question") or "",
            "목표 답": record["target_ga"], "검색 근거": evidence_section(record["prompt"]), "챗봇 답": answer}


def answer_id(item_id: str, number: int) -> str:
    return f"{item_id}#{number}"


def packets(records: list[dict], per_packet: int = PER_PACKET) -> list[list[dict]]:
    return [records[start:start + per_packet] for start in range(0, len(records), per_packet)]


def parse_output(stdout: str, ids: list[str], allowed: tuple[str, ...] = VERDICTS) -> list[dict]:
    """`claude -p --output-format json` 출력에서 판정 목록을 꺼내고, 모든 예시를 정해진 값(allowed)으로 판정했는지 본다."""
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
    bad = [item_id for item_id, entry in by_id.items() if item_id in ids and entry.get("verdict") not in allowed]
    if missing or bad:
        raise JudgeError(f"판정이 빠짐 {missing} · 값이 틀림 {bad}")
    return [{"id": item_id, "verdict": by_id[item_id]["verdict"], "category": str(by_id[item_id].get("category") or ""),
             "reason": str(by_id[item_id].get("reason") or "")} for item_id in ids]


def run(records: list[dict], work: Path, model: str = DEFAULT_MODEL, runner: Callable = run_claude,
        jobs: int = 2, per_packet: int = PER_PACKET) -> tuple[list[dict], list[tuple[str, str]]]:
    """자동 검사를 통과한 예시를 판정한다. 돌려주는 것: 판정 목록, 실패한 작업 단위(이름, 이유). work는 저장소 밖이어야 한다."""
    return _run([example(record) for record in records], work, PROMPT, GUIDE_VERSION, VERDICTS, model, runner, jobs,
                per_packet)


def run_answers(items: list[dict], work: Path, model: str = DEFAULT_MODEL, runner: Callable = run_claude,
                jobs: int = 2, per_packet: int = PER_PACKET) -> tuple[list[dict], list[tuple[str, str]]]:
    """3회차 답을 판정한다. items는 answer_example로 만든 답이다. 돌려주는 것은 run과 같다."""
    return _run(items, work, ANSWER_PROMPT, ANSWER_GUIDE_VERSION, ANSWER_VERDICTS, model, runner, jobs, per_packet)


def _run(items: list[dict], work: Path, prompt: str, version: str, allowed: tuple[str, ...], model: str,
         runner: Callable, jobs: int, per_packet: int) -> tuple[list[dict], list[tuple[str, str]]]:
    """작업 단위마다 판정 세션을 돌린다. items는 세션에 줄 글(id 칸이 있어야 한다)이다."""
    work = Path(work)
    marker = repo_marker(work)
    if marker:
        raise JudgeError(f"작업 폴더가 저장소 안이다({marker}) — 저장소의 CLAUDE.md가 읽힌다")
    label = f"{model} · Claude Code {claude_version(runner)} · 판정 지침 {version}"
    command = claude_command(model, prompt)
    groups = packets(items, per_packet)
    for number, group in enumerate(groups, 1):
        folder = work / f"packet-{number:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "examples.json").write_text(json.dumps(group, ensure_ascii=False, indent=1), encoding="utf-8")

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
                verdicts = parse_output(completed.stdout or "", [item["id"] for item in group], allowed)
            except JudgeError as problem:
                failed.append((name, str(problem)))
                continue
            results += [{**verdict, "judge": label, "packet": name} for verdict in verdicts]
    return results, failed
