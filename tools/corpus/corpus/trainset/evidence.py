"""운영 프롬프트의 [검색 근거]를 다루는 곳. 근거 블록 나누기와, 근거에 있는 안내 후보(연락처·사이트·신청 경로) 뽑기.

목표 답 지시문(prompts)과 자동 검사(checks)가 같은 규칙으로 근거를 읽도록 한 곳에 둔다.
"""

from __future__ import annotations

import re

BLOCK_HEAD = re.compile(r"^\[출처 (\d+)\]\s*$", re.M)
PHONE = re.compile(r"(?<!\d)\d{2,4}-\d{3,4}-\d{4}(?!\d)")
# 안내 후보로 볼 연락처·사이트: 전화번호(지역번호를 뺀 '870-2037', 괄호 지역번호 포함), 이메일, 주소
CONTACT = re.compile(r"(?<![\d.])(?:\(?\d{2,4}\)?[-\s)]?)?\d{3,4}-\d{4}(?!\d)|[\w.+-]+@[\w-]+\.[\w.]+|https?://[^\s)\]>]+|www\.[^\s)\]>]+")
# 신청·접수·제출·문의의 방법·기간·장소를 말하는 줄. 학교·학과 이름이 아니라 행정 안내 일반 낱말이다
GUIDE_LINE = re.compile(r"(신청|접수|제출|등록|문의|지원)\s*(기간|기한|마감|방법|처|장소|경로|일정)")
META_PREFIXES = ("문서:", "청크:", "위치:", "섹션:", "표 검색 정보:", "질문 의도 추출 정보:", "질문 관련 발췌:", "전체 내용:")
MAX_CANDIDATES = 10
MAX_LINE_CHARS = 120


def evidence_blocks(prompt: str) -> dict[int, str]:
    """프롬프트의 [검색 근거]를 [출처 N] 블록마다 나눈다."""
    start = prompt.find("[검색 근거]")
    end = prompt.find("[사용자 질문]", start + 1)
    evidence = prompt[start:end] if start >= 0 else prompt
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
