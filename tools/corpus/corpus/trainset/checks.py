"""자동 검사(설계 §6, ADR-0037): 사람 시간 없이 거를 수 있는 오류를 규칙으로 거른다.

검사마다 ok·why를 남긴다. 실패하면 그 예시는 버린다(drop). 단 '거절 확인'은 버리지 않고 Claude 판정에 메모로 넘긴다.
글자 비교는 채점기의 정규화(`evalset.scoring.normalize`)를 그대로 써서, 채점과 같은 기준으로 '근거에 있다'를 본다.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..evalset.scoring import REFUSAL_PHRASES, _number_in_context, normalize, numbers_with_units
from .evidence import CITE, PHONE, evidence_blocks, missing_guidance  # noqa: F401 (review가 checks.evidence_blocks·PHONE을 씀)
from .plan import KINDS
from .prompts import REFUSAL

RESIDENT_NUMBER = re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")
MOBILE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")
TABLE_FACT = re.compile(r"^\s*\d+\.\s*(?P<table>[^:\n]+):\s*(?P<row>.+?) 행 정보는 (?P<rest>.+?)이다\.?\s*$", re.M)
MIN_OVERLAP = 0.6
MIN_QUESTION_CHARS = 5  # 글자·숫자만 셈. 2026-10-21 첫 묶음에서 초안 모델이 질문을 "..."로 낸 적이 있다


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


def answer_body(target: str, shape: str = "ga") -> str:
    """목표 답에서 챗봇이 말하는 부분. 인용형(나)은 '답:' 줄 뒤만 본다."""
    text = target.strip()
    if shape == "na" and "답:" in text:
        text = text.split("답:", 1)[1]
    return text.strip()


# 운영 거절 문장이 아닌 말투의 거절. 채점기의 거절 목록(REFUSAL_PHRASES)에 없어 답으로 잘못 보지 않도록 행동 판단에만 더한다
REFUSAL_LIKE = ("확인이 어렵", "안내가 어렵", "알기 어렵", "파악이 어렵", "말씀드리기 어렵", "모르겠")


def refusal_like(text: str) -> bool:
    normalized = normalize(text)
    return refuses(text) or any(normalize(phrase) in normalized for phrase in REFUSAL_LIKE)


def _behavior(kind: str) -> str:
    return "partial" if kind == "partial" else ("answer" if KINDS[kind].answerable else "refuse")


def hint_in_prompt(hint: str, context: str) -> bool:
    """질문을 만든 글의 답 근거가 프롬프트(근거 8개)에 남았는가. 값이 있으면 값으로, 없으면 글자 겹침으로 본다."""
    hint_values = values(hint)
    if hint_values:
        return all(value_in(value, context) for value in hint_values)
    return overlap(hint, context) >= MIN_OVERLAP


def hint_blocks(hint: str, prompt: str) -> list[int]:
    """질문을 만든 글의 답 근거(hint)가 든 근거 블록 번호(ADR-0048 결정 3). 값이 있으면 그 값이 모두 든 블록,
    값이 없으면 글자 겹침이 MIN_OVERLAP 이상인 블록. 학과마다 같은 페이지처럼 거의 같은 문서면 여러 번호가 나온다."""
    if not (hint or "").strip():
        return []
    hint_values = values(hint)
    found = []
    for number, text in evidence_blocks(prompt).items():
        if hint_values:
            normalized = normalize(text)
            if all(value_in(value, normalized) for value in hint_values):
                found.append(number)
        elif overlap(hint, text) >= MIN_OVERLAP:
            found.append(number)
    return found


def source_retrieved(record: dict) -> bool:
    """질문을 만든 청크가 검색된 근거 8개 안에 있는가."""
    sources = {(str(record.get("document_id")), str(chunk.get("chunk_index"))) for chunk in record.get("chunks") or []}
    retrieved = {(str(item.get("document_id")), str(item.get("chunk_index"))) for item in record.get("retrieved") or []}
    return bool(sources & retrieved)


def decide_kind(record: dict) -> tuple[str, str]:
    """예시 종류를 계획이 아니라 챗봇이 받은 근거 8개로 정한다(ADR-0041). (종류, 바꾼 이유)를 돌려준다.

    계획(질문 재료 청크 하나로 정함)과 목표 답(근거 8개를 보고 씀)의 행동이 다르면 목표 답을 따른다.
    단, 답 계획을 거절 쪽으로 바꾸는 것은 계획한 답 근거가 프롬프트에 오지 않았을 때만 한다 —
    그 청크가 검색됐고 답 근거도 남았는데 거절했다면 목표 답이 틀린 것이라 바꾸지 않고 검사에서 떨어뜨린다.
    목표 답이 맞는지는 이어지는 자동 검사와 Claude 판정이 다시 본다. 판단은 주 모양(가)의 목표 답으로 한다.
    """
    planned = record.get("kind_planned") or record["kind"]
    body = answer_body(record.get("target_ga") or "", "ga")
    if not body:
        return planned, ""
    behavior = "refuse" if body.startswith(REFUSAL) else ("partial" if refusal_like(body) else "answer")
    planned_behavior = _behavior(planned)
    if behavior == planned_behavior:
        return planned, ""
    if planned_behavior != "refuse" and behavior != "answer":
        context = normalize("\n".join(evidence_blocks(record.get("prompt") or "").values()))
        if source_retrieved(record) and hint_in_prompt(record.get("hint") or "", context):
            return planned, ""
    if behavior == "answer":
        cited = set(CITE.findall(body))
        kind = "multi" if len(cited) >= 2 else "fact"
    else:
        kind = "partial" if behavior == "partial" else "refuse_guide"
    return kind, f"계획 {planned} → 받은 근거 기준 {kind}"


def check(record: dict, shape: str = "ga") -> dict:
    """예시 하나를 검사한다. record에는 plan·questions·attached·targets의 칸이 합쳐져 있다.
    종류는 먼저 받은 근거 8개 기준으로 정하고(decide_kind) 그 종류로 검사한다."""
    planned = record.get("kind_planned") or record["kind"]
    kind, kind_why = decide_kind(record)
    target = record.get(f"target_{shape}") or ""
    question, hint, prompt = record.get("question") or "", record.get("hint") or "", record.get("prompt") or ""
    blocks = evidence_blocks(prompt)
    context = normalize("\n".join(blocks.values()))
    answerable = KINDS[kind].answerable
    # 질문 재료 청크에 답이 있도록 계획한 예시만 답 근거·왕복 검색이 뜻이 있다(거절 계획에서 바뀐 예시는 답 근거가 없다)
    planned_answer = KINDS[planned].answerable
    results: dict[str, dict] = {}
    notes = [f"{kind_why} — 받은 근거에 정말 그 답이 있는지(없는지) 확인"] if kind_why else []

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
        # 답 근거가 든 블록 번호(ADR-0048 결정 3). 왕복 검사에만 쓰고 출처 번호 대조에는 쓰지 않는다 — 공고와 재공고처럼
        # 같은 값이 든 다른 블록을 인용한 정상 답이 떨어졌다(기존 묶음에서 판정 통과 4개, ADR-0048 결과)
        sources = hint_blocks(hint, prompt) if planned_answer else []
        if target_values:
            put("출처 번호 대조", not outside, f"쓴 근거 번호의 글에 없는 값 {outside}")
        elif hint:
            put("출처 번호 대조", overlap(hint, cited_text) >= MIN_OVERLAP, "쓴 근거 번호의 글에 답 근거가 없음")
        else:
            # 값도 답 근거도 없는 답(거절 계획에서 바뀐 말글 답)은 글자 겹침으로 가를 수 없어 Claude 판정에 맡긴다
            notes.append("값이 없는 답 — 쓴 근거 번호의 글에 그 내용이 있는지 확인")
        if planned_answer:
            hint_values = values(hint)
            if hint_values:
                gone = sorted(value for value in hint_values if not value_in(value, context))
                put("지워진 정답", not gone, f"답 근거의 값이 프롬프트에 없음 {gone}")
            else:
                put("지워진 정답", overlap(hint, context) >= MIN_OVERLAP, "답 근거 글이 프롬프트에 없음")
            # 질문을 만든 청크가 근거 8개 밖이어도 답 근거가 다른 블록(거의 같은 문서·다른 청크)에 있으면 통과(ADR-0048 결정 3)
            put("왕복 검색", source_retrieved(record) or bool(sources),
                "질문을 만든 청크도, 답 근거가 든 근거 블록도 근거 8개 안에 없음")
        put("모호한 표 근거", *ambiguous_table(target, prompt))
    refusal_info = record.get("refusal")
    if planned == "refuse_guide" and refusal_info is not None:
        # 답이 든 청크를 빼서 만든 답없음 예시(ADR-0048 결정 2): 근거에 답이 없음을 확인하고, 거절했는지,
        # 확인처를 코드가 고른 블록(재료 문서·같은 게시글·같은 묶음)에서만 붙였는지 본다
        put("답 근거 없음", not hint_blocks(hint, prompt), "답이 든 청크를 뺐는데 근거에 답 근거가 남음")
        put("거절함", answer_body(target, shape).startswith(REFUSAL), "답이 없게 만든 근거인데 거절하지 않음")
        allowed = set(refusal_info.get("contact_blocks") or [])
        put("확인처 출처", cited <= allowed, f"재료·같은 게시글·같은 묶음 밖의 근거 {sorted(cited - allowed)}를 확인처로 붙임")
    # 질문과 답 사이에 줄을 넣는다 — 붙이면 질문 끝 숫자와 답 첫 숫자가 이어져 번호 경계를 못 찾는다
    both = f"{question}\n{target}"
    sensitive = RESIDENT_NUMBER.search(both) or MOBILE.search(both)
    put("개인정보", not sensitive, "주민등록번호·개인 휴대전화 형태")
    if kind != "refuse_offtopic":
        # 목표 답 단계에서 한 번 다시 쓴 뒤에도 쓴 근거의 안내 줄(연락처·사이트·기간)이 빠졌으면 안내 빠짐을 의심한다(ADR-0046).
        # 질문한 일과 관계있는 안내인지는 규칙으로 가를 수 없어 떨어뜨리지 않고 Claude 판정에 메모로 넘긴다
        left = missing_guidance(target, prompt, refusal=answer_body(target, shape).startswith(REFUSAL))
        if left:
            listed = [f"[출처 {number}] {', '.join(lost)}" for number, _, lost in left[:3]]
            notes.append(f"근거의 안내 {listed}가 목표 답에 없음 — 질문한 일과 관계있으면 안내 빠짐")
    if not answerable:
        ax_answer = record.get("ax_answer") or ""
        found = sorted(value for value in values(ax_answer, question) if value_in(value, context))
        if ax_answer and not refuses(ax_answer) and found:
            notes.append(f"학습 전 A.X가 근거의 값 {found}로 답함 — 근거에 답이 있는지 확인")
    return {"kind": kind, "checks": results, "drop": any(not result["ok"] for result in results.values()),
            "judge_notes": notes}


def probe_score(record: dict, kind: str) -> dict:
    """학습 전 A.X 답(운영 설정 1번 + 표본 추출)이 이 예시에서 맞는지 센다(ADR-0042, Meta Llama 3 §4.3.6의 knowledge probing).

    규칙 채점이다. 거절 종류면 거절했으면 맞음. 답 종류면 거절하지 않고, 목표 답의 값(날짜·금액·연락처 등)을 하나 이상 말하고,
    말한 값이 모두 근거에 있으면 맞음(평가 채점기의 '지어낸 값' 기준과 같다). 근거에 있는 다른 행·해의 값을 말한 경우는
    못 가른다. 목표 답에 값이 없으면 '판단 못 함'으로 센다. 틀린 답은 2회차 선호 학습의 '나쁜 답' 후보로 남긴다.
    """
    answers = [answer for answer in [record.get("ax_answer"), *(record.get("ax_samples") or [])] if answer]
    question = record.get("question") or ""
    expected = values(record.get("target_ga") or "", question)
    context = normalize("\n".join(evidence_blocks(record.get("prompt") or "").values()))
    behavior = _behavior(kind)
    correct, decided, wrong = 0, 0, []
    for answer in answers:
        refused = answer.strip().startswith(REFUSAL) or refusal_like(answer)
        if behavior == "refuse":
            ok = refused
        elif not expected:
            continue
        else:
            said = values(answer, question)
            ok = bool(said & expected) and all(value_in(value, context) for value in said) and (
                behavior == "partial" or not refused)
        decided += 1
        correct += ok
        if not ok:
            wrong.append(answer)
    return {"n": len(answers), "decided": decided, "correct": correct, "wrong": wrong}


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
