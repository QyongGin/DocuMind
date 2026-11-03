"""운영 프롬프트의 [검색 근거]를 다루는 곳. 근거 블록 나누기, 근거에 있는 안내 후보(연락처·사이트·신청 경로) 뽑기,
목표 답이 쓴 근거의 안내 줄이 답에 다 들어갔는지 대조하기(ADR-0046).

목표 답 지시문(prompts)·목표 답 단계(pipeline)·자동 검사(checks)가 같은 규칙으로 근거를 읽도록 한 곳에 둔다.
"""

from __future__ import annotations

import re

from ..evalset.scoring import _number_in_context, normalize, numbers_with_units

BLOCK_HEAD = re.compile(r"^\[출처 (\d+)\]\s*$", re.M)
CITE = re.compile(r"\[출처\s*(\d+)\]")
PHONE = re.compile(r"(?<!\d)\d{2,4}-\d{3,4}-\d{4}(?!\d)")
# 안내 후보로 볼 연락처·사이트: 전화번호(지역번호를 뺀 '870-2037', 괄호 지역번호 포함), 이메일, 주소
CONTACT = re.compile(r"(?<![\d.])(?:\(?\d{2,4}\)?[-\s)]?)?\d{3,4}-\d{4}(?!\d)|[\w.+-]+@[\w-]+\.[\w.]+|https?://[^\s)\]>]+|www\.[^\s)\]>]+")
# 신청·접수·제출·문의의 방법·기간·장소를 말하는 줄. 학교·학과 이름이 아니라 행정 안내 일반 낱말이다
GUIDE_LINE = re.compile(r"(신청|접수|제출|등록|문의|지원)\s*(기간|기한|마감|방법|처|장소|경로|일정)")
META_PREFIXES = ("문서:", "청크:", "위치:", "섹션:", "표 검색 정보:", "질문 의도 추출 정보:", "질문 관련 발췌:", "전체 내용:")
MAX_CANDIDATES = 10
MAX_LINE_CHARS = 120


def evidence_section(prompt: str) -> str:
    """프롬프트의 [검색 근거] 부분([사용자 질문] 앞까지). 없으면 프롬프트 전체."""
    start = prompt.find("[검색 근거]")
    end = prompt.find("[사용자 질문]", start + 1)
    return prompt[start:end] if start >= 0 else prompt


def evidence_blocks(prompt: str) -> dict[int, str]:
    """프롬프트의 [검색 근거]를 [출처 N] 블록마다 나눈다."""
    evidence = evidence_section(prompt)
    heads = list(BLOCK_HEAD.finditer(evidence))
    return {int(head.group(1)): evidence[head.end(): heads[index + 1].start() if index + 1 < len(heads) else len(evidence)]
            for index, head in enumerate(heads)}


def _clean(line: str) -> str:
    line = line.strip().lstrip("-").strip()
    for prefix in ("관련 근거:", "관련 항목:"):
        if line.startswith(prefix):
            line = line[len(prefix):].strip()
    return " ".join(line.split())


def guidance_candidates(blocks: dict[int, str]) -> list[tuple[int, str]]:
    """근거에 있는 안내 후보: 연락처·사이트가 있거나 신청·접수·문의 방법·기간을 말하는 줄. (출처 번호, 줄) 목록.

    2026-10-21 첫 묶음에서 Claude 탈락 16개 중 7개가 '근거에 있는 안내를 목표 답이 뺌'이었다. 초안 모델이 근거 8개에서
    안내를 놓치지 않도록 후보를 뽑아 보여 준다. 어느 후보가 질문한 일과 관계있는지는 초안 모델과 판정이 가린다.
    """
    seen, found = set(), []
    for number, text in sorted(blocks.items()):
        for raw in text.splitlines():
            line = _clean(raw)
            if not line or line.startswith(META_PREFIXES) or line.startswith("|"):
                continue
            if not (CONTACT.search(line) or GUIDE_LINE.search(line)):
                continue
            key = re.sub(r"\s+", "", line)
            if key in seen:
                continue
            seen.add(key)
            found.append((number, line[:MAX_LINE_CHARS]))
            if len(found) >= MAX_CANDIDATES:
                return found
    return found


def contacts(text: str) -> set[str]:
    """글 속 연락처·사이트(공백을 뺀 형태)."""
    return {re.sub(r"[\s()]", "", match.group(0)).rstrip(".,") for match in CONTACT.finditer(text)}


# 날짜를 표기('3월 17일', '2026. 03. 17.', '7. 12.(일)')와 상관없이 (월, 일)로 맞춰 본다
DATES = (re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
         re.compile(r"(?<!\d)\d{2,4}\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?!\d)"),
         re.compile(r"(?<![\d.])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?(?=\s*[(（~∼]|\s|$|까지|부터)"))
# 규정 끝의 개정일은 안내가 아니다
REVISION = re.compile(r"[<(]\s*(?:개정|신설|전문개정|본조신설)[^>)]*[>)]")
# 기간·기한을 말하는 줄. 날짜나 'N일'이 함께 있어야 안내 줄로 본다
PERIOD_LINE = re.compile(r"기간|기한|마감|접수|까지|이내|일정")
MAX_FIX_LINE_CHARS = 120


def dates(text: str) -> set[tuple[int, int]]:
    """글 속 날짜를 (월, 일)로."""
    found = set()
    for pattern in DATES:
        for month, day in pattern.findall(text):
            month, day = int(month), int(day)
            if 1 <= month <= 12 and 1 <= day <= 31:
                found.add((month, day))
    return found


def _line_keys(line: str, refusal: bool) -> tuple[set[str], set[tuple[int, int]], set[str]]:
    """안내 줄에서 답에 있어야 할 값: 연락처·사이트, 날짜, 날짜를 뺀 단위 붙은 숫자. 거절 답은 확인처(연락처·사이트)만 본다."""
    line = REVISION.sub(" ", line)
    if refusal:
        return contacts(line), set(), set()
    rest = line
    for pattern in DATES:
        rest = pattern.sub(" ", rest)
    return contacts(line), dates(line), numbers_with_units(normalize(rest))


def guidance_lines(answer: str, prompt: str, refusal: bool = False) -> list[tuple[int, str]]:
    """목표 답이 쓴 근거(쓴 번호가 없으면 근거 전체)에서 안내 줄: 연락처·사이트가 있는 줄과 기간·기한 줄.
    거절 답이면 연락처·사이트 줄만(덧붙일 수 있는 것은 확인처뿐이다, ADR-0039). (출처 번호, 줄) 목록.

    어느 줄이 안내인지는 초안 모델이 아니라 이 규칙이 정한다 — 2026-10-26 시험에서 Gemma가 안내 목록을 뽑게 하면
    답을 쓸 때와 같이 '묻지 않은 링크'를 빼, 빠진 안내 10개 중 6개가 목록에서도 빠졌다(ADR-0046).
    """
    blocks = evidence_blocks(prompt)
    cited = {int(number) for number in CITE.findall(answer)}
    found, seen = [], set()
    for number, text in sorted(blocks.items()):
        if cited and number not in cited:
            continue
        for raw in text.splitlines():
            line = _clean(raw)
            if not line or line.startswith(META_PREFIXES) or line.startswith("|"):
                continue
            has_contact, line_dates, values = _line_keys(line, refusal=False)
            period = PERIOD_LINE.search(line) and (line_dates or any(value.endswith("일") for value in values))
            if not (has_contact or (period and not refusal)):
                continue
            key = re.sub(r"\s+", "", line)
            if key not in seen:
                seen.add(key)
                found.append((number, line))
    return found


def missing_guidance(answer: str, prompt: str, refusal: bool = False) -> list[tuple[int, str, list[str]]]:
    """안내 줄 가운데 값이 목표 답에 없는 것. (출처 번호, 줄, 빠진 값) 목록."""
    answer_contacts, answer_dates, normalized = contacts(answer), dates(answer), normalize(answer)
    missing = []
    for number, line in guidance_lines(answer, prompt, refusal):
        line_contacts, line_dates, values = _line_keys(line, refusal)
        lost = sorted(line_contacts - answer_contacts)
        lost += [f"{month}월 {day}일" for month, day in sorted(line_dates - answer_dates)]
        lost += sorted(value for value in values if not _number_in_context(value, normalized))
        if lost:
            missing.append((number, line, lost))
    return missing
