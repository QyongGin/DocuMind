"""자동 검사(설계 §6, ADR-0037): 사람 시간 없이 거를 수 있는 오류를 규칙으로 거른다.

검사마다 ok·why를 남긴다. 실패하면 그 예시는 버린다(drop). 단 '거절 확인'은 버리지 않고 Claude 판정에 메모로 넘긴다.
글자 비교는 채점기의 정규화(`evalset.scoring.normalize`)를 그대로 써서, 채점과 같은 기준으로 '근거에 있다'를 본다.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..evalset.scoring import REFUSAL_PHRASES, _number_in_context, normalize, numbers_with_units
from .plan import KINDS
from .prompts import REFUSAL

CITE = re.compile(r"\[출처\s*(\d+)\]")
PHONE = re.compile(r"(?<!\d)\d{2,4}-\d{3,4}-\d{4}(?!\d)")
RESIDENT_NUMBER = re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")
MOBILE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")
BLOCK_HEAD = re.compile(r"^\[출처 (\d+)\]\s*$", re.M)
TABLE_FACT = re.compile(r"^\s*\d+\.\s*(?P<table>[^:\n]+):\s*(?P<row>.+?) 행 정보는 (?P<rest>.+?)이다\.?\s*$", re.M)
MIN_OVERLAP = 0.6
MIN_QUESTION_CHARS = 5  # 글자·숫자만 셈. 2026-10-21 첫 묶음에서 초안 모델이 질문을 "..."로 낸 적이 있다


def evidence_blocks(prompt: str) -> dict[int, str]:
    """프롬프트의 [검색 근거]를 [출처 N] 블록마다 나눈다."""
    start = prompt.find("[검색 근거]")
    end = prompt.find("[사용자 질문]", start + 1)
    evidence = prompt[start:end] if start >= 0 else prompt
    heads = list(BLOCK_HEAD.finditer(evidence))
    return {int(head.group(1)): evidence[head.end(): heads[index + 1].start() if index + 1 < len(heads) else len(evidence)]
            for index, head in enumerate(heads)}


def table_facts(text: str) -> list[tuple[str, str, str, str]]:
    """표 검색 정보 문장 '표 이름: 행 이름 행 정보는 열=값; 열=값이다.'를 (표, 행, 열, 값)으로 푼다.
    PDF 칸 사실의 '(행 경로=…;)'는 행 이름에 붙인다."""
    facts = []
    for match in TABLE_FACT.finditer(text):
        row, rest = match.group("row").strip(), match.group("rest").strip()
        path = re.match(r"\(행 경로=([^)]*)\)\s*", rest)
        if path:
            row, rest = f"{row} {path.group(1).strip(' ;')}", rest[path.end():]
        for pair in rest.split(";"):
            if "=" in pair:
                column, value = pair.split("=", 1)
                facts.append((match.group("table").strip(), row, column.strip(), value.strip()))
    return facts


def values(text: str, question: str = "") -> set[str]:
    """답이 단정한 값: 단위 붙은 숫자(질문에 있던 것은 뺌)와 전화번호."""
    normalized = normalize(text)
    found = numbers_with_units(normalized) - numbers_with_units(normalize(question))
    return found | {normalize(phone) for phone in PHONE.findall(text)}


def value_in(value: str, normalized_text: str) -> bool:
    if re.fullmatch(r"[\d-]+", value):
        return value in normalized_text
    return _number_in_context(value, normalized_text)


def overlap(part: str, whole: str) -> float:
    """part의 글자 세 개 묶음 중 whole에 있는 비율(정규화 뒤)."""
    part, whole = normalize(part), normalize(whole)
    grams = {part[i:i + 3] for i in range(max(len(part) - 2, 0))}
    return sum(gram in whole for gram in grams) / len(grams) if grams else 0.0


def refuses(text: str) -> bool:
    normalized = normalize(text)
    return any(normalize(phrase) in normalized for phrase in REFUSAL_PHRASES)


def shape_check(kind: str, target: str, shape: str) -> tuple[bool, str]:
    """목표 답 모양(ADR-0039). 가: 끝 줄에 [출처 N], 거절은 운영 거절 문장. 나: '근거:' 줄 다음 '답:' 줄."""
    text = target.strip()
    answerable = KINDS[kind].answerable
    if shape == "na":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or not lines[0].startswith("근거:") or not any(line.startswith("답:") for line in lines):
            return False, "인용형은 '근거:' 줄과 '답:' 줄이 있어야 함"
        body = "\n".join(line for line in lines if not line.startswith("근거:"))
        if not answerable and not lines[0].replace(" ", "").startswith("근거:없음"):
            return False, "거절 예시인데 근거를 인용함"
        text = body.split("답:", 1)[1].strip()
    last_line = text.splitlines()[-1] if text else ""
    if not answerable:
        if not text.startswith(REFUSAL):
            return False, "거절 예시가 운영 거절 문장으로 시작하지 않음"
        if len(text) > len(REFUSAL) + 2 and not CITE.search(text):
            return False, "확인처를 덧붙였는데 근거 번호가 없음"
        return True, ""
    if not CITE.search(last_line):
        return False, "끝 줄에 [출처 N]이 없음"
    if kind == "partial" and not refuses(text):
        return False, "일부만 있음 예시에 없는 것을 밝히는 문장이 없음"
    if kind != "partial" and refuses(text):
        return False, "답 예시에 거절 문장이 섞임"
    return True, ""


def check(record: dict, shape: str = "ga") -> dict:
    """예시 하나를 검사한다. record에는 plan·questions·attached·targets의 칸이 합쳐져 있다."""
    kind, target = record["kind"], record.get(f"target_{shape}") or ""
    question, hint, prompt = record.get("question") or "", record.get("hint") or "", record.get("prompt") or ""
    blocks = evidence_blocks(prompt)
    context = normalize("\n".join(blocks.values()))
    answerable = KINDS[kind].answerable
    results: dict[str, dict] = {}

    def put(name: str, ok: bool, why: str = "") -> None:
        results[name] = {"ok": ok, "why": "" if ok else why}

    put("질문", len(re.sub(r"[\W_]", "", question)) >= MIN_QUESTION_CHARS, "질문이 비었거나 너무 짧음")
    ok, why = shape_check(kind, target, shape)
    put("모양", ok, why)
    cited = {int(number) for number in CITE.findall(target)}
    put("출처 번호 범위", cited <= set(blocks), f"없는 근거 번호 {sorted(cited - set(blocks))}")
    target_values = values(target, question)
    missing = sorted(value for value in target_values if not value_in(value, context))
    put("근거 대조", not missing, f"근거에 없는 값 {missing}")
    if answerable:
        cited_text = normalize("\n".join(blocks.get(number, "") for number in cited))
        outside = sorted(value for value in target_values if not value_in(value, cited_text))
        if target_values:
            put("출처 번호 대조", not outside, f"쓴 근거 번호의 글에 없는 값 {outside}")
        else:
            put("출처 번호 대조", overlap(hint, cited_text) >= MIN_OVERLAP, "쓴 근거 번호의 글에 답 근거가 없음")
        hint_values = values(hint)
        if hint_values:
            gone = sorted(value for value in hint_values if not value_in(value, context))
            put("지워진 정답", not gone, f"답 근거의 값이 프롬프트에 없음 {gone}")
        else:
            put("지워진 정답", overlap(hint, context) >= MIN_OVERLAP, "답 근거 글이 프롬프트에 없음")
        sources = {(str(record.get("document_id")), str(chunk.get("chunk_index"))) for chunk in record.get("chunks") or []}
        retrieved = {(str(item.get("document_id")), str(item.get("chunk_index"))) for item in record.get("retrieved") or []}
        put("왕복 검색", bool(sources & retrieved), "질문을 만든 청크가 근거 8개 안에 없음")
        put("모호한 표 근거", *ambiguous_table(target, prompt))
    # 질문과 답 사이에 줄을 넣는다 — 붙이면 질문 끝 숫자와 답 첫 숫자가 이어져 번호 경계를 못 찾는다
    both = f"{question}\n{target}"
    sensitive = RESIDENT_NUMBER.search(both) or MOBILE.search(both)
    put("개인정보", not sensitive, "주민등록번호·개인 휴대전화 형태")
    notes = []
    if not answerable:
        ax_answer = record.get("ax_answer") or ""
        found = sorted(value for value in values(ax_answer, question) if value_in(value, context))
        if ax_answer and not refuses(ax_answer) and found:
            notes.append(f"학습 전 A.X가 근거의 값 {found}로 답함 — 근거에 답이 있는지 확인")
    return {"checks": results, "drop": any(not result["ok"] for result in results.values()), "judge_notes": notes}


def ambiguous_table(target: str, prompt: str) -> tuple[bool, str]:
    """답이 쓴 표 값이 같은 표·행·열에 값이 여럿인 표 사실에서 왔으면 거른다(5단계 보고서 §8)."""
    by_key: dict[tuple, set[str]] = defaultdict(set)
    facts = table_facts(prompt)
    for table, row, column, value in facts:
        by_key[(table, row, column)].add(normalize(value))
    normalized_target = normalize(target)
    for table, row, column, value in facts:
        normalized_value = normalize(value)
        if len(by_key[(table, row, column)]) > 1 and len(normalized_value) >= 2 and normalized_value in normalized_target:
            return False, f"'{table}: {row} / {column}'에 값이 여럿({len(by_key[(table, row, column)])}개)"
    return True, ""


def duplicates(records: list[dict], threshold: float = 0.8) -> dict[str, str]:
    """질문이 앞 예시와 거의 같은 예시: {뒤 예시 번호: 앞 예시 번호}. 글자 세 개 묶음의 자카드 유사도로 본다."""
    seen: list[tuple[str, set[str]]] = []
    found = {}
    for record in records:
        text = normalize(record.get("question") or "")
        grams = {text[i:i + 3] for i in range(max(len(text) - 2, 0))}
        for earlier_id, earlier in seen:
            union = grams | earlier
            if union and len(grams & earlier) / len(union) >= threshold:
                found[record["id"]] = earlier_id
                break
        else:
            seen.append((record["id"], grams))
    return found
