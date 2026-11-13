"""표 청크 후보(#259 설계 3-3) 테스트. 데이터는 지어낸 학교(가나대학)다.

1. 후보를 모두 끈 상태의 청크가 실험 코드를 넣기 전(6d0e6c0) 코드의 출력과 글자까지 같다(golden/table_chunk_off.json).
2. 후보마다 의도한 부분만 바뀐다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

import main
import table_chunk_experiments as tcx
import table_chunk_fixture as fx

GOLDEN = Path(__file__).resolve().parent / "golden" / "table_chunk_off.json"


@pytest.fixture(autouse=True)
def chunk_off(monkeypatch):
    monkeypatch.setattr(main, "EXP_CHUNK", tcx.ChunkExperiment())


def pipeline() -> list[Document]:
    raw = [Document(page_content=fx.PAGE_1, metadata={"page": 1}), Document(page_content=fx.PAGE_2, metadata={"page": 2})]
    split = main._split_loaded_documents(main._normalize_loaded_documents(raw))
    return main._apply_overlap(main._merge_short_chunks(main._dedupe_chunk_documents(split)))


def rewrite(**settings) -> tcx.RewriteResult:
    return tcx.rewrite_pages([fx.PAGE_1, fx.PAGE_2], [fx.JSON_1, fx.JSON_2], tcx.ChunkExperiment(**settings),
                             is_subheader=main._is_probable_subheader_row, chunk_size=main.CHUNK_SIZE)


def test_all_off_matches_pre_experiment_chunks():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert [{"text": d.page_content, "meta": d.metadata} for d in pipeline()] == golden["pipeline"]
    assert [{"text": d.page_content, "meta": d.metadata} for d in main._split_table_block(fx.LONG_TABLE, {"page": 1})] \
        == golden["long_table"]
    assert not tcx.ChunkExperiment().rewrites_pages() and tcx.ChunkExperiment().settings() == {}
    # 다시 쓰기가 켜져 있어도 표를 바꾸는 후보가 없으면 쪽 글은 그대로다(주석만 모음)
    assert rewrite(notes="block").pages == [fx.PAGE_1, fx.PAGE_2]


def test_from_env_reads_flags(monkeypatch):
    monkeypatch.setenv("AI_EXP_CHUNK_GRID", "true")
    monkeypatch.setenv("AI_EXP_CHUNK_TABLE_MAX", "2000")
    monkeypatch.setenv("AI_EXP_CHUNK_NOTES", "symbol")
    assert tcx.from_env().settings() == {"grid": True, "notes": "symbol", "table_max": 2000}


def test_grid_fills_merged_cells():
    page_1 = rewrite(grid=True).pages[0]
    assert "|계열|모집단위|수시1차|수시1차|" in page_1  # 가로로 합친 머리글 칸을 채움
    assert "|계열|모집단위|일반고|특성화고|" in page_1  # 세로로 합친 머리글 칸을 채움
    assert "|공학|나다전자과|25|4|" in page_1  # 본문 세로 병합(계열)을 채움
    assert "## 가나대학 학사 안내" in page_1  # 표 밖 글은 그대로


def test_header_all_repeats_subheader_row(monkeypatch):
    before = main._split_table_block(fx.LONG_TABLE, {})
    monkeypatch.setattr(main, "EXP_CHUNK", tcx.ChunkExperiment(header_all=True))
    after = main._split_table_block(fx.LONG_TABLE, {})
    assert len(before) >= 2 and len(after) >= 2
    assert all(d.page_content.splitlines()[2] == "| | |일반고|특성화고|" for d in after)
    assert any(d.page_content.splitlines()[2] != "| | |일반고|특성화고|" for d in before[1:])
    rows = lambda docs: [line for d in docs for line in d.page_content.splitlines()[3 if docs is after else 2:]]  # noqa: E731
    assert sorted(set(rows(after))) == sorted({line for line in fx.LONG_TABLE.splitlines()[3:]})


def test_cross_page_joins_continuation_without_repeated_header():
    result = rewrite(cross_page=True)
    assert "|인문|라마경영과|40|6|" in result.pages[0] and "|인문|바사회계과|20|3|" in result.pages[0]
    assert result.pages[0].count("| | |일반고|특성화고|") == 1  # 이어진 쪽의 되풀이 머리글은 뺀다
    assert "라마경영과" not in result.pages[1]  # 이어진 조각은 둘째 쪽에서 지운다
    # 원래 줄을 지킨다(격자 후보가 꺼져 있으면 첫 쪽 표 줄은 바뀌지 않는다)
    assert "| |나다전자과|25|4|" in result.pages[0]


def test_notes_symbol_block_bbox():
    symbol = rewrite(notes="symbol").notes
    assert symbol == [(0, "|계열|모집단위|수시1차| |", ["★ 표시: 야간 과정을 함께 운영하는 학과"])]
    block = rewrite(notes="block").notes
    assert block[0][2] == ["★ 표시: 야간 과정을 함께 운영하는 학과", "※ 모집인원은 사정에 따라 바뀔 수 있음"] or \
        block[0][2] == ["※ 모집인원은 사정에 따라 바뀔 수 있음"]
    bbox = rewrite(notes="bbox").notes
    # 아래로 이어진 두 줄, 위로 줄 높이 두 배 안의 표 제목
    assert bbox[0][2] == ["★ 표시: 야간 과정을 함께 운영하는 학과", "※ 모집인원은 사정에 따라 바뀔 수 있음", "가나대학 모집인원"]
    assert all("휴학" not in line for _, _, lines in bbox for line in lines)  # 줄 높이 두 배 밖의 글은 뺀다


def test_attach_notes_only_to_same_table_chunks():
    notes = [(1, "|계열|모집단위|수시1차| |", ["★ 표시: 야간 운영"])]
    chunks = [("|계열|모집단위|수시1차| |\n|---|---|---|---|\n|공학|가나기계과 ★|30|5|", 1),
              ("|계열|모집단위|수시1차| |\n|---|---|---|---|\n|인문|라마경영과|40|6|", 2),
              ("가나대학 휴학 안내", 1)]
    out = tcx.attach_notes(chunks, notes)
    assert out[0].endswith("★ 표시: 야간 운영") and out[1] == chunks[1][0] and out[2] == chunks[2][0]
    assert tcx.attach_notes([(out[0], 1)], notes) == [out[0]]  # 이미 든 줄은 다시 붙이지 않는다


def test_cells_format_lines():
    page_1 = rewrite(table_format="cells").pages[0]
    assert "- 공학 > 가나기계과 ★, 수시1차 > 일반고 = 30" in page_1
    assert "- 공학 > 나다전자과, 수시1차 > 특성화고 = 4" in page_1
    assert "|---|" not in page_1.split("## 가나대학 학사 안내")[0]


def test_html_keeps_spans_and_repeats_split_rowspan():
    page_1 = rewrite(table_format="html").pages[0]
    assert '<th rowspan="2">계열</th>' in page_1 and '<th colspan="2">수시1차</th>' in page_1
    assert '<td rowspan="2">공학</td>' in page_1
    cells = tcx._span_cells(fx.JSON_1["kids"][1])
    pieces = "\n".join(tcx.render_html(cells, 2, 220)).split("\n\n")
    assert len(pieces) == 2
    assert all(p.count("<th") == 5 for p in pieces)  # 머리글 두 줄을 조각마다
    assert "<td>공학</td>" in pieces[1] or '<td rowspan="1">공학</td>' not in pieces[1]
    assert "공학" in pieces[1]  # 조각 경계를 넘는 세로 병합 칸을 다시 적는다


def test_html_block_is_not_split_and_overlap_skips_tags(monkeypatch):
    monkeypatch.setattr(main, "EXP_CHUNK", tcx.ChunkExperiment(table_format="html"))
    text = "가나대학 안내 " * 60 + "\n\n<table>\n<tr><th>학과</th></tr>\n" + "\n".join(
        f"<tr><td>가나{n:02d}과</td></tr>" for n in range(30)) + "\n</table>\n\n" + "다음 글 " * 80
    docs = main._split_large_chunk_preserving_tables(Document(page_content=text, metadata={}))
    html_docs = [d for d in docs if "<tr>" in d.page_content]
    assert len(html_docs) == 1 and html_docs[0].page_content.startswith("<table>")
    final = main._apply_overlap(main._merge_short_chunks(docs))
    assert all(d.page_content.count("<table>") == d.page_content.count("</table>") for d in final)


def test_table_max_keeps_table_whole(monkeypatch):
    table = fx.LONG_TABLE
    assert len(table) > main.CHUNK_SIZE
    assert len(main._split_table_block(table, {})) >= 2
    monkeypatch.setattr(main, "EXP_CHUNK", tcx.ChunkExperiment(table_max=2000))
    assert len(table) <= 2000
    assert [d.page_content for d in main._split_table_block(table, {})] == [table]
