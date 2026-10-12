"""규칙 기반 채점(결정 ②): 답을 정답과 비교해 맞음·일부·모름·틀림·애매·빈 답을 매긴다.

규칙이 정하지 못하는 답은 '애매'로 두고 사람이 본다. 평가셋을 만들 때의 이중 라벨링과, 평가할 때의 채점기가
같은 규칙을 쓴다. 판정 모델(다른 AI가 채점)은 쓰지 않는다.

점수는 둘이다(ADR-0023). 정확은 핵심 사실로 매기는 위 판정이고, 안내는 질문이 묻지 않았지만 문서에 있는
다음 할 일(안내 사실)을 답이 알려 줬는지 충족·일부·부족(안내 사실이 없으면 해당 없음)으로 따로 센다.
"""

import re
import unicodedata

from .schema import core_facts, guidance_facts

# 서버 프롬프트의 거절 문구("제공된 문서에서는 확인할 수 없습니다")와 모델마다 다른 말투를 함께 잡는다
REFUSAL_PHRASES = (
    "확인할 수 없", "찾을 수 없", "알 수 없", "나와 있지 않", "명시되어 있지 않", "포함되어 있지 않",
    "안내되어 있지 않", "기재되어 있지 않", "언급되어 있지 않", "제공되지 않", "정보가 없",
)
UNITS = "원|명|학점|시간|일|%|퍼센트|시|분|년|월|개|회|쪽|주|학기|학년|점|등급|세"
PARTIAL_SHAPES = ("목록", "절차", "설명", "예아니오")

_FULL_DATE = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?")
_SHORT_DATE = re.compile(r"(?<![\d.])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.(?!\d)")
_MONEY = re.compile(r"(\d+)\s*만\s*(?:(\d+)\s*천\s*)?(?=원)|(\d+)\s*천\s*(?=원)")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_NUMBER_WITH_UNIT = re.compile(rf"\d+(?:\.\d+)?(?:{UNITS})")


def _money(match: re.Match) -> str:
    if match.group(3):
        return str(int(match.group(3)) * 1000)
    return str(int(match.group(1)) * 10000 + int(match.group(2) or 0) * 1000)


def normalize(text: str) -> str:
    """비교용 글: 전각을 반각으로, '3만 원'을 '30000원'으로, '2026. 9. 8.'을 '2026년9월8일'로, 숫자 쉼표와 공백은 뺀다."""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = _MONEY.sub(_money, text)
    text = _FULL_DATE.sub(lambda match: f"{match.group(1)}년{int(match.group(2))}월{int(match.group(3))}일", text)
    text = _SHORT_DATE.sub(lambda match: f"{int(match.group(1))}월{int(match.group(2))}일", text)
    text = _THOUSANDS.sub("", text)
    return re.sub(r"\s+", "", text)


def contains(normalized_text: str, value: str) -> bool:
    """허용 표기가 들어 있나. 숫자로 시작·끝나는 표기는 앞뒤가 다른 숫자에 붙어 있으면 아니다(30000 ≠ 130000)."""
    target = normalize(value)
    if not target:
        return False
    if not re.search(r"\d", target):
        return target in normalized_text
    pattern = re.escape(target)
    if target[0].isdigit():
        pattern = r"(?<![\d.])" + pattern
    if target[-1].isdigit():
        pattern += r"(?!\d)"
    return re.search(pattern, normalized_text) is not None


def numbers_with_units(normalized_text: str) -> set[str]:
    return set(_NUMBER_WITH_UNIT.findall(normalized_text))


def score(item: dict, answer: str | None, context: str | None = None) -> dict:
    """답 하나를 판정한다. context(모델이 받은 근거 글)를 주면 근거에 없는 숫자를 '지어낸 숫자'로 본다.

    `label`·`matched`·`missing`은 핵심 사실로 매긴 정확 점수, `guidance`는 안내 사실로 매긴 안내 점수다.
    """
    text = (answer or "").strip()
    result = {"label": "빈 답", "matched": [], "missing": [], "forbidden_hits": [], "invented": [], "abstained": False,
              "appended_refusal": False, "guidance": guidance(item, "")}
    if not text:
        return result
    normalized = normalize(text)
    abstained = any(normalize(phrase) in normalized for phrase in REFUSAL_PHRASES)
    forbidden = [entry["value"] for entry in item.get("forbidden", []) if contains(normalized, entry["value"])]
    matched, missing = _match(core_facts(item), normalized)
    # 질문에 있던 숫자(예: "2028학년도")를 답에서 되풀이한 것은 새로 단정한 숫자로 보지 않는다
    numbers = numbers_with_units(normalized) - numbers_with_units(normalize(item.get("question", "")))
    invented = []
    if context is not None:
        normalized_context = normalize(context)
        invented = sorted(number for number in numbers if not _number_in_context(number, normalized_context))

    if forbidden:
        label = "틀림"
    elif item["shape"] == "답없음":
        if abstained:
            label = "애매" if numbers else "맞음"  # 거절하며 덧붙인 숫자는 '지난해 값'처럼 밝혔는지 사람이 본다
        else:
            label = "틀림" if numbers else "애매"  # 답이 없는 질문에 구체 숫자를 단정하면 지어낸 답
    elif abstained and matched and not missing and not invented and _refusal_after_facts(item, normalized):
        # 핵심 사실을 모두 말한 뒤에 다른 것에 대해 '확인할 수 없다'를 덧붙인 답(예: "인사학적팀입니다. 다른 장학금은 확인할 수
        # 없습니다"). 2026-10-12까지 이중 라벨링 오탐 4번(125·160·242·277)이 모두 이 경우였다. 수는 appended_refusal로 센다.
        # "확인할 수 없지만 30,000원으로 보입니다"처럼 먼저 망설이고 값을 대는 답은 그대로 애매다
        label = "맞음"
    elif abstained:
        label = "애매" if matched else "모름"
    elif not matched:
        label = "애매"
    elif missing:
        label = "일부" if item["shape"] in PARTIAL_SHAPES else "애매"
    else:
        label = "맞음"
    if label in ("맞음", "일부") and invented:
        label = "애매"
    result.update(label=label, matched=matched, missing=missing, forbidden_hits=forbidden, invented=invented,
                  abstained=abstained, appended_refusal=abstained and label == "맞음" and item["shape"] != "답없음",
                  guidance=guidance(item, text))
    return result


def _number_in_context(number_with_unit: str, normalized_context: str) -> bool:
    """답의 '50명'이 근거에 있나: 단위까지 같은 글이 있거나, 단위 없는 같은 수(표 칸의 '50')가 따로 있으면 있다고 본다.
    표 근거는 칸에 단위 없이 수만 적는 경우가 많아, 단위까지 맞춰 보면 맞는 답을 '지어낸 숫자'로 잡는다(2026-10-12 실측:
    정답 글을 그대로 채점해도 346문항 중 32문항이 애매)."""
    if number_with_unit in normalized_context:
        return True
    value = re.match(r"\d+(?:\.\d+)?", number_with_unit).group(0)
    return re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d])", normalized_context) is not None


def _value_end(normalized_text: str, value: str) -> int | None:
    """허용 표기가 처음 나오는 곳의 끝 위치(contains와 같은 숫자 경계 규칙). 없으면 None."""
    target = normalize(value)
    if not target:
        return None
    pattern = re.escape(target)
    if re.search(r"\d", target):
        if target[0].isdigit():
            pattern = r"(?<![\d.])" + pattern
        if target[-1].isdigit():
            pattern += r"(?!\d)"
    match = re.search(pattern, normalized_text)
    return match.end() if match else None


def _refusal_after_facts(item: dict, normalized_text: str) -> bool:
    """거절 문구가 핵심 사실을 모두 말한 뒤에만 나오나. 명사를 꾸미는 말("확인할 수 없는 서류")은 거절로 보지 않는다."""
    facts_end = 0
    for fact in core_facts(item):
        ends = [end for end in (_value_end(normalized_text, value) for value in fact["values"]) if end is not None]
        facts_end = max(facts_end, min(ends)) if ends else facts_end
    for phrase in REFUSAL_PHRASES:
        target = normalize(phrase)
        for match in re.finditer(re.escape(target), normalized_text):
            if normalized_text[match.end():match.end() + 1] in ("는", "은"):
                continue
            if match.start() < facts_end:
                return False
    return True


def guidance(item: dict, answer: str) -> dict:
    """안내 점수: 안내 사실을 몇 개 알려 줬나. 정확 판정과 섞지 않는다(맞는데 짧은 답은 정확 '맞음' + 안내 '부족')."""
    facts = guidance_facts(item)
    if not facts:
        return {"label": "해당 없음", "matched": [], "missing": []}
    matched, missing = _match(facts, normalize(answer or ""))
    label = "충족" if not missing else ("일부" if matched else "부족")
    return {"label": label, "matched": matched, "missing": missing}


def _match(facts: list[dict], normalized: str) -> tuple[list[str], list[str]]:
    matched, missing = [], []
    for fact in facts:
        (matched if any(contains(normalized, value) for value in fact["values"]) else missing).append(fact["name"])
    return matched, missing
