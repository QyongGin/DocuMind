"""R0-2: ``_build_rag_prompt`` 프롬프트 골든 스냅샷 테스트.

목적
----
LLM 호출 없이 ``_build_rag_prompt`` 를 직접 불러 조립된 프롬프트 문자열을
golden 파일과 **byte 단위로** 비교한다. 의도한 블록만 바뀌었는지 사람 눈이
아니라 전체 문자열 동일성으로 잠근다.

배경(#110 오진 재발 방지)
-------------------------
#110 에서 "우선 질의 근거" 블록이 주입됐는지를 ``"[우선 질의 근거]" in prompt``
로 판별했다가, 그 문자열이 하단 [답변 직전 확인] 체크리스트에도 항상 들어 있어
무조건 True 가 되어 "미배포" 오진을 했다. 올바른 판별자는 블록 주입 시에만
생기는 ``[우선 질의 근거 사용 규칙]`` 이다. 골든 스냅샷은 이런 부분 문자열
검사 대신 프롬프트 전체를 잠그므로 같은 함정을 원천 차단한다.

대표 케이스
-----------
``_build_rag_prompt`` 의 분기는 system_prompt 기본/커스텀 하나다. 우선 표 근거·우선 질의 근거
블록(옛 a·b·d 케이스)은 규칙 경로와 함께 지웠다(#169, ADR-0032). M2 4단계 ②(2026-10-20)에서 그 흔적 줄과
'질문 관련 발췌 우선' 줄을 빼고 [답변 작성 순서]를 더해 c·e 골든 파일을 다시 썼다.

입력은 전부 합성(synthetic)이다. 실제 PDF/임베딩/DB 가 필요 없다.

골든 갱신
---------
의도적으로 프롬프트를 바꾼 경우에만::

    DOCUMIND_UPDATE_GOLDEN=1 venv/bin/python -m pytest tests/test_prompt_golden.py

로 golden 파일을 다시 쓴다. 평소 실행에서 프롬프트가 1줄이라도 달라지면 실패한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from main import _build_rag_prompt

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# 합성 입력. 실제 모집요강 값이 아니라 구조만 흉내 낸 placeholder 다.
_SYNTHETIC_CONTEXT = (
    "[표 검색 정보]\n"
    "표: 합성 표\n"
    "행: 가 / 열: 금액 / 값: 10,000원\n"
    "[질문 의도 추출 정보]\n"
    "신청 방법: 합성 홈페이지에서 신청\n"
    "[질문 관련 발췌]\n"
    "합성 문서의 합성 문단 발췌."
)
_SYNTHETIC_CUSTOM_SYSTEM = "너는 합성 안내원이다. 반드시 JSON 형식으로만 답하라."

# 케이스 이름은 골든 파일 이름과 같다(옛 이름 그대로 — 파일이 바뀌지 않았음을 git으로도 확인할 수 있게).
#   c_no_priority   -> 기본 system_prompt
#   e_custom_system -> 관리자 커스텀 system_prompt
CASES = {
    "c_no_priority": {
        "system_prompt": None,
        "context": _SYNTHETIC_CONTEXT,
        "question": "합성 문서에 대한 일반 질문입니다.",
    },
    "e_custom_system": {
        "system_prompt": _SYNTHETIC_CUSTOM_SYSTEM,
        "context": _SYNTHETIC_CONTEXT,
        "question": "근거에 없는 내용을 물어봅니다.",
    },
}


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_prompt_matches_golden(case_name):
    rendered = _build_rag_prompt(**CASES[case_name])
    golden_path = GOLDEN_DIR / f"{case_name}.txt"

    if os.getenv("DOCUMIND_UPDATE_GOLDEN") == "1":
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(rendered, encoding="utf-8")
        pytest.skip(f"golden 갱신됨: {golden_path.name}")

    assert golden_path.exists(), (
        f"golden 파일이 없다: {golden_path}. "
        "최초 생성은 DOCUMIND_UPDATE_GOLDEN=1 로 한다."
    )
    expected = golden_path.read_text(encoding="utf-8")
    assert rendered == expected, (
        f"프롬프트가 golden 과 다르다: case={case_name}. "
        "의도한 변경이면 DOCUMIND_UPDATE_GOLDEN=1 로 갱신하라."
    )
