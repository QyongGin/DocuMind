"""표 근거 실험 후보 설정(#259, 설계 3-1) 테스트. 데이터는 지어낸 학교(가나대학)다.

1. 후보를 모두 끈 상태의 근거 블록·프롬프트가 실험 코드를 넣기 전(develop) 코드의 출력과 글자까지 같다.
2. 후보마다 의도한 부분만 바뀐다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import main
import table_experiment_fixture as fx

GOLDEN = Path(__file__).resolve().parent / "golden" / "table_experiment_off.json"
FLAGS = ("EXP_DROP_TABLE_BRIDGE", "EXP_DROP_INTENT_PRIORITY", "EXP_TABLE_FULL_TEXT", "EXP_MERGE_TABLE_PIECES",
         "EXP_ROW_FACT_TO_SOURCE", "EXP_COPY_ROWS_FIRST", "EXP_CHECK_EACH_ROW")


@pytest.fixture(autouse=True)
def flags_off(monkeypatch):
    for name in FLAGS:
        monkeypatch.setattr(main, name, False)
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_CHARS", 0)
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_BUDGET_CHARS", 0)
    monkeypatch.setattr(main, "EXP_TABLE_FACT_FORMAT", "")
    monkeypatch.setattr(main, "EXP_CONTEXT_ORDER", "")


def build(question: str) -> tuple[str, str]:
    analysis = main._analyze_query(question)
    metas = main._attach_runtime_table_facts(question, fx.docs(), [dict(m) for m in fx.metas()], analysis)
    context = main._build_context(fx.docs(), metas, fx.ids(), analysis)
    return context, main._build_rag_prompt(None, context, question, today=fx.TODAY)


def test_all_off_matches_pre_experiment_output():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(golden) == set(fx.QUESTIONS)
    for question in fx.QUESTIONS:
        context, prompt = build(question)
        assert context == golden[question]["context"]
        assert prompt == golden[question]["prompt"]
    assert main._table_experiment_settings() == {}


def test_drop_table_bridge_removes_only_combined_lines(monkeypatch):
    monkeypatch.setattr(main, "_derive_query_table_evidence_facts", lambda facts, analysis: ["- 가짜 조합: 99"])
    question = fx.QUESTIONS[0]
    analysis = main._analyze_query(question)
    with_bridge = main._attach_runtime_table_facts(question, fx.docs(), [dict(m) for m in fx.metas()], analysis)
    assert "- 가짜 조합: 99" in json.dumps(with_bridge, ensure_ascii=False)
    monkeypatch.setattr(main, "EXP_DROP_TABLE_BRIDGE", True)
    without = main._attach_runtime_table_facts(question, fx.docs(), [dict(m) for m in fx.metas()], analysis)
    assert "- 가짜 조합: 99" not in json.dumps(without, ensure_ascii=False)
    # 표 검색 정보(런타임 표 사실)는 그대로 붙는다
    assert [m.get("matched_table_facts") for m in without] == [m.get("matched_table_facts") for m in with_bridge]


def test_drop_intent_priority_removes_one_line(monkeypatch):
    _, before = build(fx.QUESTIONS[0])
    monkeypatch.setattr(main, "EXP_DROP_INTENT_PRIORITY", True)
    _, after = build(fx.QUESTIONS[0])
    line = "- [검색 근거]의 '질문 의도 추출 정보'가 있으면 답변에 우선 사용한다.\n"
    assert line in before and line not in after
    assert before.replace(line, "") == after


def test_table_full_text_only_for_table_blocks(monkeypatch):
    before, _ = build(fx.QUESTIONS[0])
    monkeypatch.setattr(main, "EXP_TABLE_FULL_TEXT", True)
    after, _ = build(fx.QUESTIONS[0])
    blocks_before, blocks_after = before.split("\n\n[출처 "), after.split("\n\n[출처 ")
    assert "전체 내용:" not in blocks_before[0] and "전체 내용:" in blocks_after[0]
    assert "|공학|가나기계과 ★|2|30|5|2|" in blocks_after[0].split("전체 내용:")[1]
    assert blocks_before[2] == blocks_after[2]  # 표 없는 글 블록은 그대로
    assert "표 검색 정보:" in blocks_after[0]  # 줄은 두고 원문만 더한다


def test_row_fact_to_source_drops_fact_lines_and_adds_source(monkeypatch):
    monkeypatch.setattr(main, "EXP_ROW_FACT_TO_SOURCE", True)
    context, _ = build(fx.QUESTIONS[1])
    assert "표 검색 정보:" not in context
    second = context.split("\n\n[출처 ")[1]
    assert "전체 내용:" in second and "|인문|라마경영과 ★|2|40|6|1|" in second


def test_reformat_table_fact_styles():
    fact = "가나 표: 가나기계과 행 정보는 계열=공학; 수시1차 일반고=30이다."
    assert main._reformat_table_fact(fact, "bracket") == "가나 표: 가나기계과 행 정보는 (계열: 공학) (수시1차 일반고: 30)"
    assert main._reformat_table_fact(fact, "keyvalue") == "가나 표: 가나기계과 행 정보는 {계열: 공학, 수시1차 일반고: 30}"
    cut = "가나 표: 가 행 정보는 계열=공학; 비고=긴..."
    assert main._reformat_table_fact(cut, "bracket") == "가나 표: 가 행 정보는 (계열: 공학) (비고: 긴)..."
    assert main._reformat_table_fact("모양이 다른 줄", "bracket") == "모양이 다른 줄"


def test_fact_format_applies_to_prompt(monkeypatch):
    monkeypatch.setattr(main, "EXP_TABLE_FACT_FORMAT", "bracket")
    context, _ = build(fx.QUESTIONS[0])
    assert "(수시1차 일반고: 30)" in context and "수시1차 일반고=30" not in context


def test_merge_table_pieces_joins_same_table_under_one_header(monkeypatch):
    before, _ = build(fx.QUESTIONS[1])
    monkeypatch.setattr(main, "EXP_MERGE_TABLE_PIECES", True)
    context, _ = build(fx.QUESTIONS[1])
    blocks = context.split("\n\n[출처 ")
    assert len(blocks) == 2  # 표 조각 둘이 한 블록으로, 글 블록 하나
    full = blocks[0].split("전체 내용:\n")[1]  # 이은 표는 발췌와 함께 전체 내용으로 준다
    assert full.count("|---|---|---|---|---|---|") == 1
    assert "|공학|가나기계과 ★|2|30|5|2|" in full and "|인문|라마경영과 ★|2|40|6|1|" in full
    assert blocks[1].split("\n", 1)[1] == before.split("\n\n[출처 ")[2].split("\n", 1)[1]  # 글 블록은 번호만 당겨짐


def test_expand_table_loads_neighbors_within_cap(monkeypatch):
    other = "|이름|값|\n|---|---|\n|다른 표|1|\n"
    store = {"7_4": (fx.PIECE_2, {}), "7_5": (other, {})}
    asked = []

    def fake_load(chunk_ids):
        asked.extend(chunk_ids)
        return {cid: store[cid] for cid in chunk_ids if cid in store}

    monkeypatch.setattr(main, "_load_raw_chunks_by_id", fake_load)
    docs, metas, ids = [fx.PIECE_1], [fx.metas()[0]], ["7_3"]
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_CHARS", 10000)
    out_docs, _, _ = main._apply_table_context_experiments(docs, metas, ids)
    assert "|인문|라마경영과 ★|2|40|6|1|" in out_docs[0] and "다른 표" not in out_docs[0]
    assert out_docs[0].count("|---|---|---|---|---|---|") == 1
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_CHARS", len(fx.PIECE_1) + 5)
    capped, _, _ = main._apply_table_context_experiments(docs, metas, ids)
    assert capped == [fx.PIECE_1]
    # 이미 넓힌 표의 다른 조각이 검색 결과에 또 있으면 한 번만 넣는다
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_CHARS", 10000)
    twice, _, _ = main._apply_table_context_experiments(fx.docs()[:2], fx.metas()[:2], fx.ids()[:2])
    assert len(twice) == 1


def test_context_order_ends(monkeypatch):
    docs = [f"글 {i}" for i in range(5)]
    metas = [{"source": f"문서{i}"} for i in range(5)]
    ids = [str(i) for i in range(5)]
    monkeypatch.setattr(main, "EXP_CONTEXT_ORDER", "ends")
    out_docs, _, out_ids = main._apply_table_context_experiments(docs, metas, ids)
    assert out_ids == ["0", "2", "4", "3", "1"]


def test_prompt_rule_candidates_add_lines(monkeypatch):
    _, before = build(fx.QUESTIONS[0])
    monkeypatch.setattr(main, "EXP_COPY_ROWS_FIRST", True)
    monkeypatch.setattr(main, "EXP_CHECK_EACH_ROW", True)
    _, after = build(fx.QUESTIONS[0])
    assert "'근거 행:' 뒤에 그대로 옮겨 적고" in after and "하나씩 확인해" in after
    assert "'근거 행:'" not in before
    assert after.endswith("[답변 작성]\n") and "\n\n[답변 작성]" in after
    assert main._table_experiment_settings() == {"copy_rows_first": True, "check_each_row": True}


def test_expand_within_budget_keeps_blocks_and_respects_budget(monkeypatch):
    store = {"7_4": (fx.PIECE_2, {}), "7_3": (fx.PIECE_1, {})}
    monkeypatch.setattr(main, "_load_raw_chunks_by_id", lambda chunk_ids: {c: store[c] for c in chunk_ids if c in store})
    question = fx.QUESTIONS[1]
    analysis = main._analyze_query(question)
    metas = main._attach_runtime_table_facts(question, fx.docs(), [dict(m) for m in fx.metas()], analysis)
    before = main._build_context(fx.docs(), metas, fx.ids(), analysis)
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_CHARS", 4000)
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_BUDGET_CHARS", 100000)
    roomy = main._build_context(fx.docs(), metas, fx.ids(), analysis)
    assert roomy.count("[출처 ") == before.count("[출처 ") == 3  # 블록 수와 순서는 그대로
    first = roomy.split("\n\n[출처 ")[0]
    assert "|인문|라마경영과 ★|2|40|6|1|" in first.split("전체 내용:")[1]  # 1위 표 블록을 넓힘
    monkeypatch.setattr(main, "EXP_EXPAND_TABLE_BUDGET_CHARS", len(before) + 10)
    tight = main._build_context(fx.docs(), metas, fx.ids(), analysis)
    assert tight == before  # 넓히면 예산을 넘으니 원래 조각을 둔다
    assert main._table_experiment_settings() == {"expand_table_chars": 4000, "expand_table_budget_chars": len(before) + 10}
