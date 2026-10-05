"""규칙 판정(결정 ②): 답을 정답지와 비교해 맞음·일부·모름·틀림·애매·빈 답을 매긴다.

규칙이 정하지 못하는 답은 '애매'로 두고 사람이 본다. 평가셋을 만들 때의 교차 확인과, 평가할 때의 채점기가
같은 규칙을 쓴다. 판정 모델(다른 AI가 채점)은 쓰지 않는다.
"""

import re
import unicodedata

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


def judge(item: dict, answer: str | None, context: str | None = None) -> dict:
    """답 하나를 판정한다. context(모델이 받은 근거 글)를 주면 근거에 없는 숫자를 '지어낸 숫자'로 본다."""
    text = (answer or "").strip()
    result = {"label": "빈 답", "matched": [], "missing": [], "forbidden_hits": [], "invented": [], "refusal": False}
    if not text:
        return result
    normalized = normalize(text)
    refusal = any(normalize(phrase) in normalized for phrase in REFUSAL_PHRASES)
    forbidden = [entry["value"] for entry in item.get("forbidden", []) if contains(normalized, entry["value"])]
    matched, missing = [], []
    for fact in item.get("facts", []):
        (matched if any(contains(normalized, value) for value in fact["values"]) else missing).append(fact["name"])
    # 질문에 있던 숫자(예: "2028학년도")를 답에서 되풀이한 것은 새로 단정한 숫자로 보지 않는다
    numbers = numbers_with_units(normalized) - numbers_with_units(normalize(item.get("question", "")))
    invented = []
    if context is not None:
        normalized_context = normalize(context)
        invented = sorted(number for number in numbers if number not in normalized_context)

    if forbidden:
        label = "틀림"
    elif item["shape"] == "거절":
        if refusal:
            label = "애매" if numbers else "맞음"  # 거절하며 덧붙인 숫자는 '지난해 값'처럼 밝혔는지 사람이 본다
        else:
            label = "틀림" if numbers else "애매"  # 답이 없는 질문에 구체 숫자를 단정하면 지어낸 답
    elif refusal:
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
                  refusal=refusal)
    return result
