"""사람 표본 화면과 판정 기록 합치기(ADR-0037: 첫 묶음에서 Claude 판정과 나란히 30개).

- 표본: Claude가 판정한 예시에서 종류를 고르게, 통과·탈락을 모두 담아 고른다.
- 화면: HTML 파일 하나(서버·인터넷 없음). 사람이 고른 뒤에야 Claude 판정이 보인다(판정에 끌리지 않게).
- 합치기: 화면이 내려받은 JSONL을 human.jsonl로 남기고 Claude와 어긋난 수를 센다. 2개 이상이면 판정 지침을 고친다.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

from . import checks
from .plan import KINDS

TEMPLATE = Path(__file__).with_name("review_template.html")
MAX_FAIL_SHARE = 0.5  # 표본의 절반까지는 Claude 탈락 예시로 채운다(탈락 쪽 오류도 보이게)
MIN_PHRASE = 4  # 공백 뺀 글자 수. 이보다 짧은 공통 글은 우연히 겹친다
MIN_DIGIT_PHRASE = 3  # 숫자가 든 글(50명, 3층)은 짧아도 값이다
MAX_QUESTION_HITS = 5  # 거절 답에서 질문 낱말을 표시할 때, 근거에 이보다 많이 나오면 빼는 수
COLORS = 4  # 목표 답의 문장마다 돌려 쓰는 칠 색 수(화면 CSS의 c0~c3)
SENTENCE_END = re.compile(r"(?<=[다요])[.!?](?=\s|$)|\n")
GENERIC = re.compile(r"(?:해야|할수|수|하시면|하면|있|없|합|됩|입|습|니다|\W)+")  # '있습니다.' 같은 말끝만인 글은 칠하지 않는다


def sample(records: list[dict], size: int, seed: int) -> list[dict]:
    """판정된 예시에서 표본을 고른다. 탈락을 먼저(표본의 절반까지), 나머지는 종류를 돌아가며 통과에서."""
    rng = random.Random(seed)
    judged = [record for record in records if record.get("verdict") in ("통과", "탈락")]
    failed = [record for record in judged if record["verdict"] == "탈락"]
    rng.shuffle(failed)
    chosen = failed[: int(size * MAX_FAIL_SHARE)]
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for record in judged:
        if record["verdict"] == "통과":
            by_kind[record["kind"]].append(record)
    for members in by_kind.values():
        rng.shuffle(members)
    kinds = sorted(by_kind)
    while len(chosen) < size and any(by_kind[kind] for kind in kinds):
        for kind in kinds:
            if by_kind[kind] and len(chosen) < size:
                chosen.append(by_kind[kind].pop())
    for record in failed:  # 통과가 모자라면 남은 탈락으로 채운다
        if len(chosen) >= size:
            break
        if record not in chosen:
            chosen.append(record)
    order = {record["id"]: number for number, record in enumerate(records)}
    return sorted(chosen, key=lambda record: order[record["id"]])


def _squeeze(text: str) -> tuple[str, list[int]]:
    """비교용으로 공백·굵게 표시(*)를 뺀 글과, 그 글자마다 원래 글에서의 자리."""
    kept = [(index, char) for index, char in enumerate(text) if not char.isspace() and char != "*"]
    return "".join(char for _, char in kept), [index for index, _ in kept]


def _sentences(text: str) -> list[tuple[int, int]]:
    """목표 답을 문장(…다. …요. 또는 줄)마다 나눈 자리. '8. 25.' 같은 날짜의 점에서는 나누지 않는다."""
    spans, start = [], 0
    for match in SENTENCE_END.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    spans.append((start, len(text)))
    return [(begin, end) for begin, end in spans if text[begin:end].strip()]


def _long_enough(piece: str) -> bool:
    return len(piece) >= (MIN_DIGIT_PHRASE if re.search(r"\d", piece) else MIN_PHRASE)


def _phrases(sentence: str, evidence: str) -> list[tuple[int, int]]:
    """문장(공백 뺀 글)에서 근거에 글자 그대로 있는 글을 긴 것부터 겹치지 않게 고른다.
    앞에서부터 고르면 '기간은 8월'의 '은8월'처럼 낱말 경계를 넘은 짧은 글이 먼저 잡혀 '8월29일까지'가 끊긴다."""
    found, runs = [], [(0, len(sentence))]
    while runs:
        best = None
        for run_start, run_end in runs:
            for start in range(run_start, run_end):
                length = 0
                while start + length < run_end and sentence[start:start + length + 1] in evidence:
                    length += 1
                if _long_enough(sentence[start:start + length]) and (best is None or length > best[1] - best[0]):
                    best = (start, start + length)
        if best is None:
            break
        found.append(best)
        runs = [piece for run in runs for piece in ((run[0], min(run[1], best[0])), (max(run[0], best[1]), run[1]))
                if piece[1] > piece[0]]
    return sorted(found)


def _split_lines(text: str, begin: int, end: int, tag: str) -> list[list]:
    """칠할 자리가 줄을 넘으면 줄마다 나눈다(화면이 줄 단위로 근거 줄을 표시하므로)."""
    pieces, start = [], begin
    for index in range(begin, end):
        if text[index] == "\n":
            if index > start:
                pieces.append([start, index, tag])
            start = index + 1
    if end > start:
        pieces.append([start, end, tag])
    return pieces


def _without_overlap(marks: list[list]) -> list[list]:
    kept = []
    for mark in sorted(marks):
        if not kept or mark[0] >= kept[-1][1]:
            kept.append(mark)
    return kept


def _paint_blocks(phrase: str, tag: str, blocks: dict[int, str], squeezed: dict, block_marks: dict) -> None:
    for number, (block_squeezed, block_where) in squeezed.items():
        for hit in re.finditer(re.escape(phrase), block_squeezed):
            block_marks[number] += _split_lines(blocks[number], block_where[hit.start()], block_where[hit.end() - 1] + 1, tag)


def highlight(target: str, question: str, blocks: dict[int, str]) -> dict:
    """목표 답의 문장마다 근거에 글자 그대로 있는 글을 찾아, 답과 근거에 같은 색으로 칠할 자리를 낸다.

    사람이 '이 근거 줄로 이 답을 썼구나'를 바로 보게 하려는 것이다. 질문을 되풀이한 글은 칠하지 않되,
    문장에 새 글이 없으면(예: "네, 받을 수 있습니다") 되풀이한 글이라도 칠한다. 거절 문장이 아닌데 근거에서
    같은 글을 하나도 못 찾은 문장은 'miss'로 둔다 — 바꿔 쓴 말이거나 근거에 없는 말이다.
    거절만 한 답이면 질문 낱말을 근거에서 'qw'로 표시해, 정말 답이 없는지 찾기 쉽게 한다.
    """
    question_squeezed, question_where = _squeeze(question)
    squeezed = {number: _squeeze(text) for number, text in blocks.items()}
    evidence = "\n".join(text for text, _ in squeezed.values())  # 줄 바꿈은 공백 뺀 답에 없어 블록을 넘는 글은 안 생긴다
    target_marks, block_marks, color = [], {number: [] for number in blocks}, 0
    for begin, end in _sentences(target):
        sentence = checks.CITE.sub(lambda match: " " * len(match.group(0)), target[begin:end])
        sentence_squeezed, where = _squeeze(sentence)
        if not sentence_squeezed or checks.refuses(sentence):
            continue
        phrases = [(start, stop) for start, stop in _phrases(sentence_squeezed, evidence)
                   if not GENERIC.fullmatch(sentence_squeezed[start:stop])]
        found = [(start, stop) for start, stop in phrases if sentence_squeezed[start:stop] not in question_squeezed] or phrases
        if not found:
            if len(sentence_squeezed) >= MIN_PHRASE:
                target_marks.append([begin + where[0], begin + where[-1] + 1, "miss"])
            continue
        tag = f"c{color % COLORS}"
        for start, stop in found:
            target_marks.append([begin + where[start], begin + where[stop - 1] + 1, tag])
            _paint_blocks(sentence_squeezed[start:stop], tag, blocks, squeezed, block_marks)
        color += 1
    question_marks = []
    if color == 0 and checks.refuses(target):
        for start, stop in _phrases(question_squeezed, evidence):
            phrase = question_squeezed[start:stop]
            # 근거 곳곳에 나오는 낱말(학과 이름 등)은 질문의 주제일 뿐 답을 찾는 실마리가 아니라 표시하지 않는다
            if not GENERIC.fullmatch(phrase) and evidence.count(phrase) <= MAX_QUESTION_HITS:
                question_marks.append([question_where[start], question_where[stop - 1] + 1, "qw"])
                _paint_blocks(phrase, "qw", blocks, squeezed, block_marks)
    return {"target": _without_overlap(target_marks), "question": question_marks,
            "blocks": {number: _without_overlap(marks) for number, marks in block_marks.items()}}


def page(records: list[dict], batch: str) -> str:
    """표본 화면 HTML. 목표 답의 글을 근거에서 찾아 같은 색으로 칠하고, 목표 답이 쓴 번호와 칠한 블록만 펼친다."""
    examples = []
    for record in records:
        target = record.get("target_ga") or ""
        cited = {int(number) for number in checks.CITE.findall(target)}
        blocks = {number: text.strip() for number, text in checks.evidence_blocks(record.get("prompt") or "").items()}
        marks = highlight(target, record.get("question") or "", blocks)
        examples.append({
            "id": record["id"], "kind": KINDS[record["kind"]].label, "user": record.get("user_actual") or record["user"],
            "question": record.get("question") or "", "question_marks": marks["question"],
            "target": target, "target_marks": marks["target"],
            "notes": (record.get("result") or {}).get("ga", {}).get("judge_notes") or [],
            "blocks": [{"n": number, "text": text, "cited": number in cited, "marks": marks["blocks"][number]}
                       for number, text in sorted(blocks.items())],
            "claude": {"verdict": record.get("verdict"), "category": record.get("category") or "",
                       "reason": record.get("reason") or ""},
        })
    data = json.dumps({"batch": batch, "examples": examples}, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)


def read_record(path: Path) -> dict[str, dict]:
    """화면이 내려받은 판정 기록(JSONL): {예시 번호: {human, memo}}."""
    records = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry.get("human") not in ("통과", "탈락"):
                raise ValueError(f"판정 값이 틀림: {entry}")
            records[entry["id"]] = {"human": entry["human"], "memo": entry.get("memo") or ""}
    return records


def agreement(records: list[dict], human: dict[str, dict]) -> dict:
    """사람과 Claude 판정이 어긋난 예시. 어긋남 2개 이상이면 판정 지침을 고치고 새 30개를 본다(ADR-0037)."""
    seen = [record for record in records if record["id"] in human]
    differ = [{"id": record["id"], "claude": record.get("verdict"), "human": human[record["id"]]["human"],
               "memo": human[record["id"]]["memo"], "reason": record.get("reason")}
              for record in seen if record.get("verdict") != human[record["id"]]["human"]]
    false_pass = sum(1 for entry in differ if entry["claude"] == "통과")
    return {"seen": len(seen), "differ": len(differ), "claude_pass_human_fail": false_pass,
            "claude_fail_human_pass": len(differ) - false_pass, "next": "나머지는 Claude 판정만" if len(differ) <= 1
            else "판정 지침을 고치고 새 30개", "examples": differ}
