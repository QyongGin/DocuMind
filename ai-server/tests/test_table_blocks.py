"""표 블록 조립(#274): 표 전체와 표 아래 주석을 한 근거 블록으로 넣는다.

가나대학 합성 문서만 쓴다. 표 조각은 실제 서버처럼 source_blocks 컬렉션(메모리 Chroma)에 넣고 `table_numbers`로 꺼낸다.
"""

from __future__ import annotations

import itertools
from datetime import date

import chromadb
import pytest

import main
import table_blocks
from prompt_tokens import nfc
from table_blocks import is_note_line

DOC = "31"
SOURCE = "2027학년도 가나대학 신입생 모집요강.pdf"
HEADERS = {"Header 1": "Ⅰ. 2027학년도 모집인원", "Header 2": "1. 정원내 전형 모집인원"}
QUESTION = "가나대학 항공기계공학과 수시1차 모집 인원은 몇 명이야?"

# 표 1(정원내 전형 모집인원)은 청크 3, 4에 나뉜다. 청크 4 끝에 주석 두 줄과 주석이 아닌 글 한 줄이 이어진다
CHUNK_3 = """# Ⅰ. 2027학년도 모집인원
## 1. 정원내 전형 모집인원
|계열|모집단위|모집 정원|수시1차|
|---|---|---|---|
|공학|기계공학과|90|50|
| |항공기계공학과|110|50|"""
CHUNK_4 = """## 1. 정원내 전형 모집인원
|계열|모집단위|모집 정원|수시1차|
|---|---|---|---|
|자연|화학과|40|20|
|인문|국어국문과|30|15|
※ 동일 모집시기 내 1개 전형에만 지원 가능함
- ※ ♣표시: 전공심화과정 운영 학과
그러나 복수 지원이 확인되면 합격을 취소합니다."""
# 표 2, 3이 한 청크에 든다. 표 2 뒤 주석, 그 뒤에 표 3, 표 3 뒤 글
CHUNK_7 = """## 2. 정원외 전형
|전형|모집 인원|
|---|---|
|농어촌|12|
|기초생활수급자|8|
주) 정원외 인원은 학과별로 다를 수 있음
1. 지원 자격은 다음 쪽에 있다
|학과|면접|
|---|---|
|기계공학과|있음|
|화학과|없음|
면접 일정은 따로 안내합니다."""
OTHER_TEXT = "가나대학 입학처는 본관 1층에 있으며 전화 상담은 평일 9시부터 18시까지 받는다."
OTHER_META = {"document_id": "40", "source": "가나대학 입학처 안내.html", "chunk_index": 0, "Header 1": "입학처 안내"}


def _meta(chunk_index: int, numbers: list[int], page: int, **extra) -> dict:
    meta = {"document_id": DOC, "source": SOURCE, "academic_year": 2027, "chunk_index": chunk_index,
            "page": page, "page_start": page, "page_end": page, **HEADERS, **extra}
    if numbers:
        meta["table_numbers"] = numbers
    return meta


_COUNTER = itertools.count()


@pytest.fixture
def store(monkeypatch):
    """메모리 Chroma의 source_blocks 컬렉션. add(청크 번호, 글, 표 번호, 쪽)로 원문 사본을, add_odl로 표 원문 블록을 넣는다."""
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(f"source_blocks_test_{next(_COUNTER)}")
    monkeypatch.setattr(main, "source_block_collection", collection)
    monkeypatch.setattr(main, "TABLE_BLOCK_ENABLED", True)
    monkeypatch.setattr(main, "TABLE_BLOCK_FILL_ENABLED", False)
    monkeypatch.setattr(main, "PROMPT_DATE_LINES_ENABLED", False)
    chunks: dict[str, tuple[str, dict]] = {}

    class Store:
        def add(self, chunk_index, text, numbers, page, document_id=DOC, **extra):
            meta = _meta(chunk_index, numbers, page, **extra)
            meta["document_id"] = document_id
            collection.add(ids=[f"{document_id}_{chunk_index}_source"], documents=[text], embeddings=[[0.0]],
                           metadatas=[{**meta, "chunk_role": "source_block",
                                       "source_parent_chunk_id": f"{document_id}_{chunk_index}"}])
            chunks[f"{document_id}_{chunk_index}"] = (text, {**meta, "chunk_role": "raw"})

        def add_odl(self, source_index, text, numbers, page):
            parent_index = main.OPENDATALOADER_JSON_PARENT_CHUNK_INDEX_OFFSET + source_index
            meta = {"document_id": DOC, "source": SOURCE, "chunk_role": "source_block", "page": page,
                    "page_start": page, "page_end": page, "table_numbers": numbers,
                    "parser_name": main.OPENDATALOADER_JSON_TABLE_FACT_SOURCE,
                    "source_parent_chunk_id": f"{DOC}_{parent_index}", "source_parent_chunk_index": parent_index}
            collection.add(ids=[f"{DOC}_odl_{source_index}"], documents=[text], embeddings=[[0.0]], metadatas=[meta])
            chunks[f"{DOC}_{parent_index}"] = (text, {**meta, "chunk_role": "raw", "chunk_index": parent_index})

        def build(self, chunk_ids, top_k=8, question=QUESTION, today=None):
            lookup = {**chunks, "40_0": (OTHER_TEXT, OTHER_META)}
            docs = [lookup[chunk_id][0] for chunk_id in chunk_ids]
            metas = [dict(lookup[chunk_id][1]) for chunk_id in chunk_ids]
            return main._build_table_block_prompt(None, question, today, docs, metas, list(chunk_ids), top_k,
                                                  main._analyze_query(question))

    # 컬렉션은 지우지 않는다. 메모리 Chroma에서 지운 컬렉션의 배열 메타데이터가 뒤에 만든 컬렉션의 $contains 조회에 섞인 적이 있다
    return Store()


@pytest.fixture
def table_one(store):
    store.add(3, CHUNK_3, [1], 2)
    store.add(4, CHUNK_4, [1], 3)
    return store


def _blocks(context: str) -> list[str]:
    return context.split("\n\n[출처 ")


# ---------------------------------------------------------------- 주석 표시


@pytest.mark.parametrize("line", ["※ 단위: 명", "* 2026.3.1. 기준", "＊ 수시 면접 학과", "주) 정원외 인원", "(주) 별도 안내",
                                  "주 1) 복수지원 불가", "주1) 복수지원 불가", "- ※ 글머리 기호 뒤 주석", "· * 가운뎃점 뒤 주석",
                                  "   ※ 들여 쓴 주석"])
def test_note_marks(line):
    assert is_note_line(line)


@pytest.mark.parametrize("line", ["1) 번호 각주", "① 번호 각주", "1. 지원 자격", "비고: 별도", "참고: 별도", "단위: 명",
                                  "♣표시: 전공심화", "그러나 복수 지원은 안 됩니다.", "주소: 가나시"])
def test_not_note_marks(line):
    assert not is_note_line(line)


# ---------------------------------------------------------------- 표 전체와 주석


def test_one_piece_retrieved_gets_whole_table_and_notes(table_one):
    result = table_one.build([f"{DOC}_3", "40_0"])
    first = _blocks(result.context)[0]
    assert first == "\n".join([
        "[출처 1]",
        f"문서: {SOURCE}",
        "위치: PDF 2페이지",
        "섹션: Ⅰ. 2027학년도 모집인원 > 1. 정원내 전형 모집인원",
        "내용:",
        "# Ⅰ. 2027학년도 모집인원",
        "## 1. 정원내 전형 모집인원",
        "표:",
        "|계열|모집단위|모집 정원|수시1차|",
        "|---|---|---|---|",
        "|공학|기계공학과|90|50|",
        "| |항공기계공학과|110|50|",
        "|자연|화학과|40|20|",
        "|인문|국어국문과|30|15|",
        "표 아래 주석:",
        "※ 동일 모집시기 내 1개 전형에만 지원 가능함",
        "- ※ ♣표시: 전공심화과정 운영 학과",
    ])
    # 표를 채우려고 가져온 조각(청크 4)의 표 밖 글은 넣지 않는다. 표 블록에는 청크 줄이 없다
    assert "합격을 취소" not in result.context
    assert "청크:" not in first
    # 표가 아닌 블록은 지금 모양(청크 줄, 발췌, 전체 내용) 그대로다
    assert "청크: 문서 내 1번째 청크" in _blocks(result.context)[1]


def test_both_pieces_retrieved_table_once_and_later_body_kept(table_one):
    result = table_one.build([f"{DOC}_3", f"{DOC}_4"])
    blocks = _blocks(result.context)
    assert result.context.count("|공학|기계공학과|90|50|") == 1
    assert result.context.count("※ 동일 모집시기") == 1
    # 뒤 순위 블록(청크 4): 표 줄과 주석 줄을 빼면 이미 든 제목 줄과 새 본문 한 줄이 남아 표 밖 글만 가진 블록으로 남는다
    assert blocks[1] == "\n".join([
        "2]",
        f"문서: {SOURCE}",
        "위치: PDF 3페이지",
        "섹션: Ⅰ. 2027학년도 모집인원 > 1. 정원내 전형 모집인원",
        "내용:",
        "## 1. 정원내 전형 모집인원",
        "그러나 복수 지원이 확인되면 합격을 취소합니다.",
    ])
    assert result.block_of == {f"{DOC}_3": 1, f"{DOC}_4": 2}


def test_text_after_notes_gets_content_label_again(table_one):
    # 청크 4가 먼저 검색되면 표 뒤 주석, 그 뒤 주석이 아닌 글이 원문 순서로 「내용:」을 다시 달고 이어진다
    result = table_one.build([f"{DOC}_4"])
    body = result.context.split("섹션: Ⅰ. 2027학년도 모집인원 > 1. 정원내 전형 모집인원\n", 1)[1]
    assert body.split("\n")[0] == "내용:"
    assert body.endswith("표 아래 주석:\n※ 동일 모집시기 내 1개 전형에만 지원 가능함\n- ※ ♣표시: 전공심화과정 운영 학과\n"
                         "내용:\n그러나 복수 지원이 확인되면 합격을 취소합니다.")
    assert "|공학|기계공학과|90|50|" in body  # 앞 조각(청크 3)의 행도 들어온다


def test_later_block_with_only_new_heading_lines_is_dropped(table_one):
    # 청크 4가 먼저 들면, 뒤 순위 청크 3에서 표 줄을 빼고 새로 남는 줄은 제목 줄(# Ⅰ. …)뿐이라 블록을 뺀다
    result = table_one.build([f"{DOC}_4", f"{DOC}_3", "40_0"])
    assert result.context.count("[출처 ") == 2
    assert result.info["dropped_chunk_ids"] == [f"{DOC}_3"]
    assert result.block_of[f"{DOC}_3"] is None
    assert "[출처 2]\n문서: 가나대학 입학처 안내.html" in result.context


def test_chunk_with_two_tables(store):
    store.add(7, CHUNK_7, [2, 3], 5)
    result = store.build([f"{DOC}_7"])
    body = result.context.split("섹션: Ⅰ. 2027학년도 모집인원 > 1. 정원내 전형 모집인원\n", 1)[1]
    assert body == "\n".join([
        "내용:", "## 2. 정원외 전형",
        "표:", "|전형|모집 인원|", "|---|---|", "|농어촌|12|", "|기초생활수급자|8|",
        "표 아래 주석:", "주) 정원외 인원은 학과별로 다를 수 있음",
        "내용:", "1. 지원 자격은 다음 쪽에 있다",
        "표:", "|학과|면접|", "|---|---|", "|기계공학과|있음|", "|화학과|없음|",
        "내용:", "면접 일정은 따로 안내합니다.",
    ])
    assert [table["table_number"] for table in result.info["blocks"][0]["tables"]] == [2, 3]


def test_two_table_chunk_pieces_follow_row_keys(store):
    # 표 2의 뒤 조각이 청크 8에만 있다. 청크 7의 두 표 조각은 행 열쇠로(청크 8에 없는 표 3은 남은 번호로) 짝 짓는다
    store.add(7, CHUNK_7, [2, 3], 5)
    store.add(8, "|전형|모집 인원|\n|---|---|\n|기초생활수급자|8|\n|특성화고졸 재직자|20|", [2], 6)
    result = store.build([f"{DOC}_7"])
    table_two = result.context.split("표:\n", 1)[1].split("\n표 아래 주석:", 1)[0]
    assert table_two.split("\n") == ["|전형|모집 인원|", "|---|---|", "|농어촌|12|", "|기초생활수급자|8|",
                                     "|특성화고졸 재직자|20|"]
    assert "|기계공학과|있음|" in result.context


def test_filled_table_blocks_are_preferred(store):
    # PDF 표 원문 블록(합친 칸을 채운 표)이 있으면 그 표를 쪽 순서로 잇는다. 둘째 쪽이 되풀이한 머리 행은 한 번만 둔다
    store.add(3, CHUNK_3, [1], 2)
    store.add(4, CHUNK_4, [1], 3)
    store.add_odl(1, "계열 | 모집단위 | 모집 정원 | 수시1차\n공학 | 기계공학과 | 90 | 50\n공학 | 항공기계공학과 | 110 | 50", [1], 2)
    store.add_odl(2, "계열 | 모집단위 | 모집 정원 | 수시1차\n자연 | 화학과 | 40 | 20\n인문 | 국어국문과 | 30 | 15", [1], 3)
    result = store.build([f"{DOC}_3"])
    table = result.context.split("표:\n", 1)[1].split("\n표 아래 주석:", 1)[0]
    assert table.split("\n") == ["계열 | 모집단위 | 모집 정원 | 수시1차", "공학 | 기계공학과 | 90 | 50",
                                 "공학 | 항공기계공학과 | 110 | 50", "자연 | 화학과 | 40 | 20", "인문 | 국어국문과 | 30 | 15"]
    assert result.info["blocks"][0]["tables"] == [{"table_number": 1, "shape": "odl", "mode": "full"}]
    # 표 원문 블록 근거가 뒤 순위로 들어오면 그 표는 이미 들어가 블록이 빠진다
    result = store.build([f"{DOC}_3", f"{DOC}_{main.OPENDATALOADER_JSON_PARENT_CHUNK_INDEX_OFFSET + 2}"])
    assert result.context.count("[출처 ") == 1


def test_table_fact_sentences_and_bridge_lines_are_removed(store):
    store.add(3, CHUNK_3, [1], 2)
    meta = _meta(3, [], 2, matched_table_facts=["표: 합성 표 / 행: 항공기계공학과 / 값: 50"],
                 query_evidence_facts=["항공기계공학과 수시1차: 50"])
    result = main._build_table_block_prompt(None, QUESTION, None, [CHUNK_3], [meta], ["99_3"], 8,
                                            main._analyze_query(QUESTION))
    assert "표 검색 정보" not in result.prompt
    assert "항공기계공학과 수시1차: 50" not in result.prompt
    assert "4. 검색 근거에 '표 검색 정보'" not in result.prompt
    assert "'표 검색 정보'가 있으면 표의 행/열/값" not in result.prompt
    # 규칙 번호는 그대로 두고 그 줄만 뺀다
    assert "3. 질문이 방법" in result.prompt and "\n5. 표에서 숫자" in result.prompt


def test_index_without_table_numbers_keeps_current_blocks(store, monkeypatch):
    # 표 번호가 없는 색인: 모든 블록이 지금 모양(_format_context_block)이고, 빠지는 것은 표 사실 문장과 표 조합 줄뿐이다
    docs = [CHUNK_3, OTHER_TEXT]
    metas = [_meta(3, [], 2), dict(OTHER_META)]
    analysis = main._analyze_query(QUESTION)
    result = main._build_table_block_prompt(None, QUESTION, None, docs, metas, [f"{DOC}_3", "40_0"], 8, analysis)
    assert result.context == main._build_context(docs, metas, [f"{DOC}_3", "40_0"], analysis)
    assert "청크: 문서 내 4번째 청크" in result.context and "표:" not in result.context
    monkeypatch.setattr(main, "TABLE_BLOCK_ENABLED", False)
    assert result.context == main._build_context(docs, metas, [f"{DOC}_3", "40_0"], analysis)


def test_fill_uses_next_candidate_only_when_enabled(table_one, monkeypatch):
    ids = [f"{DOC}_4", f"{DOC}_3", "40_0"]
    result = table_one.build(ids, top_k=2)
    assert result.considered == 2 and result.context.count("[출처 ") == 1
    monkeypatch.setattr(main, "TABLE_BLOCK_FILL_ENABLED", True)
    result = table_one.build(ids, top_k=2)
    assert result.considered == 3 and result.context.count("[출처 ") == 2
    assert result.block_of == {f"{DOC}_4": 1, f"{DOC}_3": None, "40_0": 2}


def test_prompt_is_nfc_and_counted(store):
    # 호환 한자 樂(U+F95C)은 NFC에서 U+6A02가 된다. 서버는 정규화한 글을 세고 그 글을 생성 모델에 보낸다
    store.add(3, CHUNK_3.replace("기계공학과|90", "기계공학과(樂)|90"), [1], 2)
    result = store.build([f"{DOC}_3"])
    assert "樂" not in result.prompt and "樂" in result.prompt
    assert result.prompt == nfc(result.prompt)
    assert result.info["prompt_tokens"] == main.PROMPT_TOKEN_COUNTER.count(result.prompt)
    assert result.info["prompt_token_limit"] == main.PROMPT_TOKEN_LIMIT


# ---------------------------------------------------------------- 문맥 길이를 넘는 표


def _big_table_chunks(rows_per_chunk: int, chunks: int, prefix: str) -> list[str]:
    header = f"|{prefix} 학과|입학 정원|수시 합격자|정시 합격자|"
    out = []
    for chunk in range(chunks):
        rows = [f"|{prefix}학과{chunk * rows_per_chunk + row}|{100 + row}|{2000 + row}|{3000 + row}|"
                for row in range(rows_per_chunk)]
        out.append("\n".join([header, "|---|---|---|---|", *rows]))
    return out


def test_table_over_limit_keeps_retrieved_piece_header_and_notes(store):
    # 표 1은 조각 40개(약 2만 토큰)라 프롬프트 상한(11,771)을 넘는다. 검색된 조각(청크 12)과 머리글, 주석만 넣는다
    pieces = _big_table_chunks(25, 40, "가")
    for index, text in enumerate(pieces):
        if index == len(pieces) - 1:
            text += "\n※ 합격자 수는 2026년 2월 기준"
        store.add(index, text, [1], index + 1)
    full = store.build(["31_12"])
    assert full.info["partial_tables"] == ["31:1"]
    assert full.info["prompt_tokens"] <= main.PROMPT_TOKEN_LIMIT and not full.info["over_limit"]
    body = full.context.split("섹션: Ⅰ. 2027학년도 모집인원 > 1. 정원내 전형 모집인원\n", 1)[1]
    assert body.split("\n")[:3] == ["표 일부:", "|가 학과|입학 정원|수시 합격자|정시 합격자|", "|---|---|---|---|"]
    assert "|가학과300|" in body and "|가학과324|" in body and "|가학과299|" not in body
    assert body.endswith("표 아래 주석:\n※ 합격자 수는 2026년 2월 기준")


def test_higher_rank_table_whole_first(store):
    # 표 1(약 6천 토큰)과 표 2(약 6천 토큰)는 함께 넣으면 상한을 넘는다. 높은 순위 표 1은 통째로, 표 2는 줄인다
    for index, text in enumerate(_big_table_chunks(25, 12, "가")):
        store.add(index, text, [1], 1)
    for index, text in enumerate(_big_table_chunks(25, 12, "나")):
        store.add(100 + index, text, [2], 2)
    result = store.build(["31_3", "31_105"])
    assert result.info["partial_tables"] == ["31:2"]
    assert result.info["blocks"][0]["tables"][0]["mode"] == "full"
    assert result.info["prompt_tokens"] <= main.PROMPT_TOKEN_LIMIT
    assert "|가학과0|" in result.context and "|가학과299|" in result.context
    assert "|나학과125|" in result.context and "|나학과0|" not in result.context
    # 상한 안이면 줄이지 않는다
    small = store.build(["31_3"])
    assert small.info["partial_tables"] == [] and "|가학과299|" in small.context


# ---------------------------------------------------------------- 표 사실 청크 검색 설정


def test_table_fact_retrieval_switch_drops_fact_candidates(monkeypatch):
    vector = (["표 사실 문장", OTHER_TEXT], [{"chunk_role": "table_fact", "parent_chunk_id": "31_3", "parent_content": CHUNK_3},
                                            dict(OTHER_META)], ["31_fact_0", "40_0"])
    table_fact = (["표 사실 문장 2"], [{"chunk_role": "table_fact", "parent_chunk_id": "31_4", "parent_content": CHUNK_4}],
                  ["31_fact_1"])
    analysis = main._analyze_query(QUESTION)
    monkeypatch.setattr(main, "_load_parent_chunk", lambda _id: (None, None))
    monkeypatch.setattr(main, "RERANKER_URL", "")
    on = main._order_retrieval_results(QUESTION, analysis, vector, ([], [], []), table_fact)
    assert {"31_3", "31_4"} <= set(on.final[2])
    monkeypatch.setattr(main, "TABLE_FACT_RETRIEVAL_ENABLED", False)
    off = main._order_retrieval_results(QUESTION, analysis, vector, ([], [], []), table_fact)
    assert off.final[2] == ["40_0"]


def test_rules_unchanged_when_table_block_off(monkeypatch):
    monkeypatch.setattr(main, "TABLE_BLOCK_ENABLED", False)
    prompt = main._build_rag_prompt(None, "근거", "질문")
    assert main.TABLE_FACT_RULE in prompt and main.TABLE_FACT_CHECK in prompt
    monkeypatch.setattr(main, "TABLE_BLOCK_ENABLED", True)
    prompt = main._build_rag_prompt(None, "근거", "질문")
    assert main.TABLE_FACT_RULE not in prompt and main.TABLE_FACT_CHECK not in prompt
    assert table_blocks.TABLE_LABEL_FULL == "표:"


def test_heading_closes_note_range(store):
    # 표 뒤 주석 범위는 다음 제목 줄 전까지다. 제목 줄 뒤의 ※ 줄은 이 표의 주석이 아니다
    store.add(5, "|과목|학점|\n|---|---|\n|수학|3|\n|물리|2|\n※ 학점은 학기당 기준\n## 3. 장학\n※ 장학금은 별도 공지", [4], 4)
    result = store.build([f"{DOC}_5"])
    assert "표 아래 주석:\n※ 학점은 학기당 기준\n내용:\n## 3. 장학\n※ 장학금은 별도 공지" in result.context


def test_later_block_with_only_lines_already_present_is_dropped(store):
    # 뒤 순위 블록에서 표 줄을 빼고 남은 줄(본문)이 모두 앞 블록에 이미 든 줄이면 블록을 뺀다(공백만 달라도 같은 줄)
    store.add(3, "모집 인원은 아래와 같다.\n|학과|인원|\n|---|---|\n|가학과|10|", [1], 2)
    store.add(4, "모집  인원은 아래와  같다.\n|학과|인원|\n|---|---|\n|나학과|20|", [1], 3)
    result = store.build([f"{DOC}_3", f"{DOC}_4"])
    assert result.info["dropped_chunk_ids"] == [f"{DOC}_4"]
    assert "|나학과|20|" in result.context


def test_extra_piece_in_two_table_chunk_follows_known_rows(store):
    # 청크 7에 표 2 조각, 표 2의 이어지는 조각(글 한 줄 뒤), 표 3 조각이 있다. 번호는 [2, 3] 둘뿐이라 순서만으로는
    # 가운데 조각이 표 3으로 붙는다. 다른 청크(8, 9)에서 본 행으로 첫째와 셋째를 짝 지으면 가운데 조각은 앞 조각의 표 2다
    chunk = "\n".join(["|전형|인원|", "|---|---|", "|농어촌|12|", "다음 행은 정원외다.", "|전형|인원|", "|---|---|",
                       "|재직자|20|", "", "|학과|면접|", "|---|---|", "|기계공학과|있음|"])
    store.add(7, chunk, [2, 3], 5)
    store.add(8, "|전형|인원|\n|---|---|\n|농어촌|12|", [2], 5)
    store.add(9, "|학과|면접|\n|---|---|\n|기계공학과|있음|\n|화학과|없음|", [3], 6)
    result = store.build([f"{DOC}_7"])
    tables = [part.split("\n내용:")[0].split("\n표 아래")[0] for part in result.context.split("표:\n")[1:]]
    assert "|재직자|20|" in tables[0] and "|재직자|20|" not in tables[1]
    assert "|화학과|없음|" in tables[1]
