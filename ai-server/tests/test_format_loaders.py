"""이슈 #125: HWP 5.0·HWPX·HTML·DOCX 로더와 공통 표 격자 규칙의 골든 테스트.

모든 시험 자료는 지어낸 내용이다(저장소가 공개라 학교 문서를 넣지 않는다).
- HWP: `tests/fixtures/table_sample.hwp`(자바 hwplib으로 만든 합성 파일, 만드는 법은 `tools/hwp-fixture/README.md`)와
  레코드를 직접 짜 맞춘 섹션 스트림
- HWPX·DOCX: 시험 중에 만든다
- HTML: 문자열

표 규칙(1×1 표는 글, 표 안 제목 줄, 머리 여러 줄 합침, 세로 병합 채움, 짧은 가로 병합 채움 등)은
`format_loaders/table_grid.py` 머리말과 조사 보고서의 결정 2를 따른다.
"""

from __future__ import annotations

import logging
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

from format_loaders import UnsupportedDocumentError, load_markdown
from format_loaders import hwp5
from format_loaders.html_tables import html_to_markdown, load_html_markdown
from format_loaders.table_grid import (
    TABLE_SEPARATOR,
    TableCell,
    TableGrid,
    blocks_to_markdown,
    render_table,
    separate_adjacent_tables,
)
from main import ALLOWED_EXTENSIONS, _extract_table_facts, _load_documents

TESTS_DIR = Path(__file__).resolve().parent
HWP_FIXTURE = TESTS_DIR / "fixtures" / "table_sample.hwp"
HWP_GOLDEN = TESTS_DIR / "golden" / "formats" / "table_sample_hwp.md"
META = {"source": "fixture", "document_id": "fixture"}


def _cell(row: int, col: int, text: str, row_span: int = 1, col_span: int = 1, header: bool = False) -> TableCell:
    return TableCell(row, col, row_span, col_span, [text], is_header=header)


def _table_lines(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("|")]


# ── 공통 표 격자 규칙 ────────────────────────────────────────────────


def test_one_by_one_table_becomes_plain_text() -> None:
    grid = TableGrid(1, 1, [_cell(0, 0, "상자 안 안내 글")])
    assert render_table(grid) == "상자 안 안내 글"


def test_full_width_top_row_moves_above_table_as_title_line() -> None:
    grid = TableGrid(3, 2, [
        _cell(0, 0, "등록금 안내", col_span=2),
        _cell(1, 0, "구분"), _cell(1, 1, "금액"),
        _cell(2, 0, "수업료"), _cell(2, 1, "100"),
    ])
    assert render_table(grid) == "등록금 안내\n\n| 구분 | 금액 |\n| --- | --- |\n| 수업료 | 100 |"


def test_corner_cell_spanning_two_rows_merges_header_into_one_line() -> None:
    grid = TableGrid(3, 3, [
        _cell(0, 0, "구분", row_span=2), _cell(0, 1, "1학기", col_span=2),
        _cell(1, 1, "등록금"), _cell(1, 2, "입학금"),
        _cell(2, 0, "신입생"), _cell(2, 1, "100"), _cell(2, 2, "20"),
    ])
    assert _table_lines(render_table(grid)) == [
        "| 구분 | 1학기 등록금 | 1학기 입학금 |",
        "| --- | --- | --- |",
        "| 신입생 | 100 | 20 |",
    ]


def test_vertical_merge_value_is_repeated_on_every_row() -> None:
    grid = TableGrid(3, 3, [
        _cell(0, 0, "구분"), _cell(0, 1, "학기"), _cell(0, 2, "금액"),
        _cell(1, 0, "수업료", row_span=2), _cell(1, 1, "1학기"), _cell(1, 2, "100"),
        _cell(2, 1, "2학기"), _cell(2, 2, "200"),
    ])
    assert _table_lines(render_table(grid))[2:] == ["| 수업료 | 1학기 | 100 |", "| 수업료 | 2학기 | 200 |"]


def test_short_horizontal_merge_fills_columns_with_different_names() -> None:
    grid = TableGrid(2, 3, [
        _cell(0, 0, "구분"), _cell(0, 1, "1학기"), _cell(0, 2, "2학기"),
        _cell(1, 0, "수업료"), _cell(1, 1, "동결", col_span=2),
    ])
    assert _table_lines(render_table(grid))[2] == "| 수업료 | 동결 | 동결 |"


def test_long_horizontal_merge_stays_in_first_cell() -> None:
    sentence = "학기 시작 2주 전까지 고지서와 문자로 안내"  # 23자 > 20자
    grid = TableGrid(2, 3, [
        _cell(0, 0, "구분"), _cell(0, 1, "1학기"), _cell(0, 2, "2학기"),
        _cell(1, 0, "비고"), _cell(1, 1, sentence, col_span=2),
    ])
    assert _table_lines(render_table(grid))[2] == f"| 비고 | {sentence} |  |"


def test_horizontal_merge_under_one_merged_header_stays_in_first_cell() -> None:
    grid = TableGrid(2, 3, [
        _cell(0, 0, "구분"), _cell(0, 1, "내용", col_span=2),
        _cell(1, 0, "수업료"), _cell(1, 1, "동결", col_span=2),
    ])
    lines = _table_lines(render_table(grid))
    assert lines[0] == "| 구분 | 내용 | 내용 |"
    assert lines[2] == "| 수업료 | 동결 |  |"


def test_full_width_body_row_stays_in_first_cell() -> None:
    grid = TableGrid(3, 3, [
        _cell(0, 0, "구분"), _cell(0, 1, "학기"), _cell(0, 2, "금액"),
        _cell(1, 0, "1학년", col_span=3),
        _cell(2, 0, "수업료"), _cell(2, 1, "1학기"), _cell(2, 2, "100"),
    ])
    assert _table_lines(render_table(grid))[2] == "| 1학년 |  |  |"


def test_pipe_and_line_break_in_cell_do_not_break_columns() -> None:
    grid = TableGrid(2, 2, [
        _cell(0, 0, "구분"), _cell(0, 1, "방법"),
        _cell(1, 0, "신청"), _cell(1, 1, "방문|우편\n전화"),
    ])
    assert _table_lines(render_table(grid))[2] == "| 신청 | 방문/우편 전화 |"


def test_nested_table_is_spread_into_outer_cell_text() -> None:
    inner = TableGrid(2, 2, [_cell(0, 0, "요일"), _cell(0, 1, "시간"), _cell(1, 0, "평일"), _cell(1, 1, "9시")])
    grid = TableGrid(2, 2, [
        _cell(0, 0, "부서"), _cell(0, 1, "안내"),
        _cell(1, 0, "학사"), TableCell(1, 1, 1, 1, [inner]),
    ])
    assert _table_lines(render_table(grid))[2] == "| 학사 | 요일 · 시간 / 평일 · 9시 |"


def test_strict_table_with_missing_cell_falls_back_to_text(caplog: pytest.LogCaptureFixture) -> None:
    grid = TableGrid(2, 2, [_cell(0, 0, "구분"), _cell(0, 1, "금액"), _cell(1, 0, "수업료")], strict=True)
    with caplog.at_level(logging.WARNING):
        assert render_table(grid) == "구분 · 금액\n수업료"
    assert "어긋난 표" in caplog.text


def test_html_style_grid_allows_short_rows() -> None:
    grid = TableGrid(2, 2, [_cell(0, 0, "구분"), _cell(0, 1, "금액"), _cell(1, 0, "수업료")], strict=False)
    assert _table_lines(render_table(grid))[2] == "| 수업료 |  |"


def test_empty_table_is_dropped() -> None:
    grid = TableGrid(2, 2, [_cell(0, 0, ""), _cell(0, 1, ""), _cell(1, 0, ""), _cell(1, 1, "")])
    assert render_table(grid) == ""
    assert blocks_to_markdown(["앞 글", grid, "뒤 글"]) == "앞 글\n뒤 글"


def test_back_to_back_tables_keep_their_own_column_names() -> None:
    # 기존 표 블록 나누기는 빈 줄만 둔 두 표를 한 표로 합쳐 뒤 표의 값을 앞 표의 열 이름으로 읽었다
    first = TableGrid(2, 2, [_cell(0, 0, "구분"), _cell(0, 1, "금액"), _cell(1, 0, "수업료"), _cell(1, 1, "100")])
    second = TableGrid(2, 2, [_cell(0, 0, "기간"), _cell(0, 1, "1학기"), _cell(1, 0, "수강신청"), _cell(1, 1, "2월")])
    markdown = separate_adjacent_tables(blocks_to_markdown([first, second]))
    assert TABLE_SEPARATOR in markdown
    facts = _extract_table_facts(markdown, META)
    assert any("기간=수강신청; 1학기=2월" in fact for fact in facts)
    assert not any("구분=기간" in fact or "구분=수강신청" in fact for fact in facts)


# ── HWP 5.0 ─────────────────────────────────────────────────────────


def test_hwp_fixture_matches_golden_markdown() -> None:
    assert load_markdown(str(HWP_FIXTURE), "hwp") + "\n" == HWP_GOLDEN.read_text(encoding="utf-8")


def test_hwp_table_facts_keep_merged_header_names() -> None:
    facts = _extract_table_facts(load_markdown(str(HWP_FIXTURE), "hwp"), META)
    assert any("1학기 등록금=100" in fact and "1학기 입학금=20" in fact for fact in facts)
    assert any("구분=수업료; 학기=2학기; 금액=200" in fact for fact in facts)


def _record(tag: int, level: int, payload: bytes = b"") -> bytes:
    size = len(payload)
    if size >= 0xFFF:
        return struct.pack("<II", tag | (level << 10) | (0xFFF << 20), size) + payload
    return struct.pack("<I", tag | (level << 10) | (size << 20)) + payload


def _para_text(text: str) -> bytes:
    return text.encode("utf-16-le")


def _control(control_id: bytes) -> bytes:
    # 컨트롤 ID는 네 글자를 거꾸로 저장한다('tbl ' → b' lbt')
    return control_id[::-1] + b"\x00" * 4


def _cell_header(row: int, col: int, row_span: int = 1, col_span: int = 1) -> bytes:
    return struct.pack("<iI4H", 1, 0, col, row, col_span, row_span) + b"\x00" * 16


def _cell_paragraph(level: int, text: str) -> bytes:
    return _record(hwp5.PARA_HEADER, level) + _record(hwp5.PARA_TEXT, level + 1, _para_text(text))


def test_hwp_section_skips_header_keeps_textbox_caption_and_table() -> None:
    extended = [11, 0x6274, 0x206C, 0, 0, 0, 0, 11]  # 8글자짜리 확장 제어 문자(표 자리)
    table_paragraph_text = _para_text("표 앞 ") + struct.pack("<8H", *extended) + _para_text("글")
    section = b"".join([
        # 본문 글: 사용자 정의 영역 기호는 버리고, 대리 문자 쌍(확장 한자)은 살린다
        _record(hwp5.PARA_HEADER, 0), _record(hwp5.PARA_TEXT, 1, _para_text("본문 글 𠀀")),
        # 머리말 컨트롤: 버린다
        _record(hwp5.PARA_HEADER, 0), _record(hwp5.CTRL_HEADER, 1, _control(b"head")),
        _record(hwp5.LIST_HEADER, 2, b"\x00" * 8), _cell_paragraph(2, "머리말 글"),
        # 글상자(그리기 개체) 컨트롤: 안의 글을 꺼낸다
        _record(hwp5.PARA_HEADER, 0), _record(hwp5.CTRL_HEADER, 1, _control(b"gso ")),
        _record(hwp5.LIST_HEADER, 2, b"\x00" * 8), _cell_paragraph(2, "글상자 글"),
        # 표: TABLE 앞에 컨트롤 데이터(태그 87)와 캡션 문단이 끼어 있다
        _record(hwp5.PARA_HEADER, 0), _record(hwp5.PARA_TEXT, 1, table_paragraph_text),
        _record(hwp5.CTRL_HEADER, 1, _control(b"tbl ")),
        _record(87, 2, b"\x00" * 4),
        _record(hwp5.LIST_HEADER, 2, b"\x00" * 8), _cell_paragraph(2, "캡션 글"),
        _record(hwp5.TABLE, 2, struct.pack("<IHH", 0, 2, 2)),
        _record(hwp5.LIST_HEADER, 2, _cell_header(0, 0)), _cell_paragraph(2, "가"),
        _record(hwp5.LIST_HEADER, 2, _cell_header(0, 1)), _cell_paragraph(2, "나"),
        _record(hwp5.LIST_HEADER, 2, _cell_header(1, 0)), _cell_paragraph(2, "1"),
        _record(hwp5.LIST_HEADER, 2, _cell_header(1, 1)), _cell_paragraph(2, "2"),
    ])
    assert blocks_to_markdown(hwp5.parse_section(section)) == (
        "본문 글 𠀀\n글상자 글\n표 앞 글\n캡션 글\n\n| 가 | 나 |\n| --- | --- |\n| 1 | 2 |"
    )


def test_hwp_space_and_hyphen_controls_become_characters() -> None:
    def control(code: int) -> bytes:
        return struct.pack("<H", code)

    text = _para_text("제1장") + control(31) + _para_text("총칙") + control(30) + _para_text("A") + control(24) + _para_text("B")
    assert hwp5.para_text(text) == "제1장 총칙 A-B"


def test_hwp_stray_top_level_record_does_not_drop_following_paragraphs() -> None:
    section = b"".join([
        _record(hwp5.PARA_HEADER, 0), _record(hwp5.PARA_TEXT, 1, _para_text("앞 문단")),
        _record(99, 0, b"\x00" * 4),
        _record(hwp5.PARA_HEADER, 0), _record(hwp5.PARA_TEXT, 1, _para_text("뒤 문단")),
    ])
    assert hwp5.parse_section(section) == ["앞 문단", "뒤 문단"]


def test_hwp_record_with_extended_size_is_read() -> None:
    long_text = "가" * 3000  # 6,000바이트 > 4,095 → 크기를 머리 뒤 4바이트에 따로 적는다
    section = _record(hwp5.PARA_HEADER, 0) + _record(hwp5.PARA_TEXT, 1, _para_text(long_text))
    assert hwp5.parse_section(section) == [long_text]


def _copy_with_header_flags(tmp_path: Path, flags: int) -> Path:
    olefile = pytest.importorskip("olefile")
    target = tmp_path / "flagged.hwp"
    shutil.copyfile(HWP_FIXTURE, target)
    with olefile.OleFileIO(str(target), write_mode=True) as ole:
        header = bytearray(ole.openstream("FileHeader").read())
        struct.pack_into("<I", header, 36, struct.unpack_from("<I", header, 36)[0] | flags)
        ole.write_stream("FileHeader", bytes(header))
    return target


@pytest.mark.parametrize("flag", [2, 4], ids=["password", "distribution"])
def test_hwp_password_or_distribution_document_is_rejected(tmp_path: Path, flag: int) -> None:
    with pytest.raises(UnsupportedDocumentError, match="암호가 걸렸거나 배포용"):
        load_markdown(str(_copy_with_header_flags(tmp_path, flag)), "hwp")


def test_hwp_3_document_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "old.hwp"
    path.write_bytes(b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05" + b"\x00" * 100)
    with pytest.raises(UnsupportedDocumentError, match="HWP 3.0"):
        load_markdown(str(path), "hwp")


def test_hwp_broken_ole_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.hwp"
    path.write_bytes(HWP_FIXTURE.read_bytes()[:1024])  # OLE 서명은 있지만 뒤가 잘린 파일
    with pytest.raises(UnsupportedDocumentError):
        load_markdown(str(path), "hwp")


def test_hwp_section_parse_failure_falls_back_to_text(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def broken(_: bytes) -> list:
        raise struct.error("깨진 표 레코드")

    monkeypatch.setattr(hwp5, "parse_section", broken)
    with caplog.at_level(logging.WARNING):
        markdown = load_markdown(str(HWP_FIXTURE), "hwp")
    assert "합성 시험 문서" in markdown and "신입생" in markdown
    assert "|" not in markdown
    assert "글만 꺼냅니다" in caplog.text


# ── HWPX ────────────────────────────────────────────────────────────

_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _hwpx_cell(row: int, col: int, text: str, row_span: int = 1, col_span: int = 1) -> str:
    return (
        f"<hp:tc header=\"0\"><hp:subList><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hp:subList>"
        f"<hp:cellAddr colAddr=\"{col}\" rowAddr=\"{row}\"/><hp:cellSpan colSpan=\"{col_span}\" rowSpan=\"{row_span}\"/></hp:tc>"
    )


def _write_hwpx(path: Path, body: str) -> Path:
    section = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="{_HS}" xmlns:hp="{_HP}">{body}</hs:sec>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", section)
    return path


def test_hwpx_reads_text_table_and_textbox_and_skips_header(tmp_path: Path) -> None:
    table = (
        "<hp:tbl rowCnt=\"3\" colCnt=\"2\">"
        f"<hp:tr>{_hwpx_cell(0, 0, '구분')}{_hwpx_cell(0, 1, '금액')}</hp:tr>"
        f"<hp:tr>{_hwpx_cell(1, 0, '수업료', row_span=2)}{_hwpx_cell(1, 1, '100')}</hp:tr>"
        f"<hp:tr>{_hwpx_cell(2, 1, '200')}</hp:tr>"
        "</hp:tbl>"
    )
    body = (
        "<hp:p><hp:run><hp:t>본문<hp:tab/>글</hp:t></hp:run></hp:p>"
        "<hp:p><hp:run><hp:ctrl><hp:header><hp:subList><hp:p><hp:run><hp:t>머리말</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:header></hp:ctrl></hp:run></hp:p>"
        f"<hp:p><hp:run><hp:t>표 앞 글</hp:t>{table}</hp:run></hp:p>"
        "<hp:p><hp:run><hp:rect><hp:drawText><hp:subList><hp:p><hp:run><hp:t>글상자 글</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:drawText></hp:rect></hp:run></hp:p>"
    )
    markdown = load_markdown(str(_write_hwpx(tmp_path / "sample.hwpx", body)), "hwpx")
    assert markdown == (
        "본문 글\n표 앞 글\n\n| 구분 | 금액 |\n| --- | --- |\n| 수업료 | 100 |\n| 수업료 | 200 |\n\n글상자 글"
    )


def test_hwpx_rejects_doctype_and_broken_zip(tmp_path: Path) -> None:
    path = tmp_path / "doctype.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Contents/section0.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "a">]><x/>')
    with pytest.raises(UnsupportedDocumentError):
        load_markdown(str(path), "hwpx")
    broken = tmp_path / "broken.hwpx"
    broken.write_bytes(b"not a zip")
    with pytest.raises(UnsupportedDocumentError):
        load_markdown(str(broken), "hwpx")


# ── HTML ────────────────────────────────────────────────────────────


def test_html_rowspan_without_th_keeps_columns_and_header() -> None:
    html = (
        "<p>등록금 안내</p><table>"
        "<tr><td>구분</td><td>학기</td><td>금액</td></tr>"
        "<tr><td rowspan=\"2\">수업료</td><td>1학기</td><td>100</td></tr>"
        "<tr><td>2학기</td><td>200</td></tr></table>"
    )
    markdown = html_to_markdown(html)
    assert _table_lines(markdown) == [
        "| 구분 | 학기 | 금액 |", "| --- | --- | --- |", "| 수업료 | 1학기 | 100 |", "| 수업료 | 2학기 | 200 |",
    ]
    facts = _extract_table_facts(markdown, META)
    assert any("구분=수업료; 학기=2학기; 금액=200" in fact for fact in facts)


def test_html_th_rows_become_one_combined_header() -> None:
    html = (
        "<table><thead><tr><th rowspan=\"2\">구분</th><th colspan=\"2\">1학기</th></tr>"
        "<tr><th>등록금</th><th>입학금</th></tr></thead>"
        "<tbody><tr><td>신입생</td><td>100</td><td>20</td></tr></tbody></table>"
    )
    assert _table_lines(html_to_markdown(html))[0] == "| 구분 | 1학기 등록금 | 1학기 입학금 |"


def test_html_caption_and_title_row_go_above_table() -> None:
    html = (
        "<table><caption>표 1</caption><tr><td colspan=\"2\">등록금 안내</td></tr>"
        "<tr><td>구분</td><td>금액</td></tr><tr><td>수업료</td><td>100</td></tr></table>"
    )
    assert html_to_markdown(html) == "표 1\n\n등록금 안내\n\n| 구분 | 금액 |\n| --- | --- |\n| 수업료 | 100 |"


def test_html_single_cell_box_is_unwrapped_and_inner_table_kept() -> None:
    html = (
        "<table><tr><td><p>안내 글</p><table><tr><td>요일</td><td>시간</td></tr>"
        "<tr><td>평일</td><td>9시</td></tr></table></td></tr></table>"
    )
    assert html_to_markdown(html) == "안내 글\n\n| 요일 | 시간 |\n| --- | --- |\n| 평일 | 9시 |"


def test_html_nested_table_is_spread_into_outer_cell() -> None:
    html = (
        "<table><tr><td>부서</td><td>안내</td></tr><tr><td>학사</td><td>"
        "<table><tr><td>요일</td><td>시간</td></tr><tr><td>평일</td><td>9시</td></tr></table>"
        "</td></tr></table>"
    )
    assert _table_lines(html_to_markdown(html))[2] == "| 학사 | 요일 · 시간 / 평일 · 9시 |"


def test_html_keeps_image_alt_text_only_and_tables_inside_lists() -> None:
    html = (
        "<p>포스터 <img src=\"/upload/a.png\" alt=\"입학 설명회 일정\"></p><p><img src=\"/upload/b.png\"></p>"
        "<ul><li>목록<table><tr><td>가</td><td>나</td></tr><tr><td>1</td><td>2</td></tr></table></li></ul>"
    )
    markdown = html_to_markdown(html)
    assert "포스터 입학 설명회 일정" in markdown
    assert "upload" not in markdown
    assert "| 가 | 나 |" in markdown and "| 1 | 2 |" in markdown


def test_html_file_in_cp949_is_decoded(tmp_path: Path) -> None:
    path = tmp_path / "old.html"
    path.write_bytes('<html><head><meta charset="euc-kr"></head><body><p>학사 안내</p></body></html>'.encode("cp949"))
    assert load_html_markdown(str(path)) == "학사 안내"


# ── DOCX ────────────────────────────────────────────────────────────


def _make_docx(path: Path) -> Path:
    docx = pytest.importorskip("docx", reason="python-docx 없으면 DOCX 픽스처 생성 불가")
    document = docx.Document()
    document.add_heading("학사 안내", level=1)
    table = document.add_table(rows=4, cols=3)
    values = [["구분", "학기", "금액"], ["수업료", "1학기", "100"], ["", "2학기", "200"], ["비고", "동결", ""]]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    table.cell(1, 0).merge(table.cell(2, 0)).text = "수업료"
    table.cell(3, 1).merge(table.cell(3, 2)).text = "동결"
    schedule = document.add_table(rows=2, cols=3)
    for col_index, value in enumerate(["기간", "1학기", "2학기"]):
        schedule.cell(0, col_index).text = value
    for col_index, value in enumerate(["수강신청", "2월", "8월"]):
        schedule.cell(1, col_index).text = value
    document.save(path)
    return path


def test_docx_merged_table_keeps_columns_and_heading(tmp_path: Path) -> None:
    markdown = load_markdown(str(_make_docx(tmp_path / "sample.docx")), "docx")
    assert markdown.startswith("# 학사 안내")
    assert _table_lines(markdown)[:6] == [
        "| 구분 | 학기 | 금액 |", "| --- | --- | --- |", "| 수업료 | 1학기 | 100 |", "| 수업료 | 2학기 | 200 |",
        "| 비고 | 동결 | 동결 |", "| 기간 | 1학기 | 2학기 |",
    ]


def test_docx_header_row_with_digits_still_yields_table_facts(tmp_path: Path) -> None:
    # MarkItDown 경로는 머리 줄이 비고 첫 줄에 숫자가 있으면 열 이름을 모두 잃어 표 사실이 0개였다
    facts = _extract_table_facts(load_markdown(str(_make_docx(tmp_path / "sample.docx")), "docx"), META)
    assert any("1학기=2월" in fact and "2학기=8월" in fact for fact in facts)


# ── AI 서버 연결 ──────────────────────────────────────────────────────


def test_allowed_extensions_include_new_formats() -> None:
    assert {"hwp", "hwpx", "html", "htm"} <= ALLOWED_EXTENSIONS


def test_load_documents_routes_hwp_to_table_grid_loader() -> None:
    documents = _load_documents(str(HWP_FIXTURE), "table_sample.hwp")
    assert len(documents) == 1
    assert documents[0].page_content + "\n" == HWP_GOLDEN.read_text(encoding="utf-8")


def test_upload_rejects_password_hwp_with_reason(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import main

    payload = _copy_with_header_flags(tmp_path, 2).read_bytes()
    response = TestClient(main.app).post(
        "/documents",
        files={"file": ("secret.hwp", payload, "application/octet-stream")},
        data={"document_id": "987654"},
    )
    assert response.status_code == 422
    assert "암호가 걸렸거나 배포용" in response.json()["detail"]
    progress = main._get_document_progress(987654)
    assert progress["status"] == "failed" and "암호가 걸렸거나 배포용" in progress["message"]
