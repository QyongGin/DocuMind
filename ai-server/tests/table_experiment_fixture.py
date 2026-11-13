"""표 근거 실험(#259) 테스트용 합성 근거(지어낸 학교 '가나대학'). 실제 학교 문서가 아니다.

후보 설정을 모두 끈 상태의 근거 블록·프롬프트가 실험 코드를 넣기 전과 글자까지 같은지 잠그는 데 쓴다
(golden/table_experiment_off.json — 실험 코드를 넣기 전 develop 코드로 만든 값).
"""

from __future__ import annotations

from datetime import date

TABLE_HEAD = "|계열|모집단위|수업 연한|수시1차| | |\n|---|---|---|---|---|---|\n| | | |일반고|특성화고|특기자|"
PIECE_1 = (
    "## 가나대학 모집인원\n"
    f"{TABLE_HEAD}\n"
    "|공학|가나기계과 ★|2|30|5|2|\n"
    "| |나다전자과|2|25|4| |\n"
)
PIECE_2 = (
    "|계열|모집단위|수업 연한|수시1차| | |\n|---|---|---|---|---|---|\n"
    "| |다라화학과|3|20|3| |\n"
    "|인문|라마경영과 ★|2|40|6|1|\n"
    "※ ★표시: 야간 운영 학과\n"
)
TEXT_DOC = "가나대학 휴학 신청은 학기 시작 전까지 포털에서 할 수 있다. 문의는 학사지원팀(02-000-0000)."

QUESTIONS = [
    "가나기계과는 수시1차 일반고로 몇 명 뽑아요?",
    "라마경영과 수시1차 특기자 모집인원은?",
    "가나대학 휴학 신청은 어떻게 해요?",
]


def metas():
    return [
        {"source": "가나대학 모집요강.pdf", "document_id": "7", "chunk_index": 3, "page": 2, "page_start": 2,
         "page_end": 2, "chunk_role": "raw"},
        {"source": "가나대학 모집요강.pdf", "document_id": "7", "chunk_index": 4, "page": 3, "page_start": 3,
         "page_end": 3, "chunk_role": "raw", "matched_chunk_role": "table_fact",
         "matched_table_facts": ["가나대학 모집인원: 라마경영과 ★ 행 정보는 계열=인문; 수업 연한=2; 수시1차=40; 수시1차=6; 수시1차=1이다."]},
        {"source": "가나대학 학사 안내", "document_id": "9", "chunk_index": 0, "chunk_role": "raw"},
    ]


def docs():
    return [PIECE_1, PIECE_2, TEXT_DOC]


def ids():
    return ["7_3", "7_4", "9_0"]


TODAY = date(2026, 10, 31)
