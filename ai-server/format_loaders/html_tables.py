"""HTML·DOCX 문서를 마크다운으로 바꾼다. 표는 공통 표 격자로, 표 밖 글은 MarkItDown HTML 변환으로.

MarkItDown(markdownify)은 표의 rowspan을 버려 세로 병합 아래 줄의 칸이 밀리고, th가 없는 표에 빈 머리 줄을
만든다(수집 HTML 표 1,266개 중 칸 밀림 385개, 열 이름을 모두 잃은 표 272개). 그래서 표만 따로 격자로 만든다.
DOCX는 MarkItDown과 같은 순서(`pre_process_docx` → mammoth)로 HTML을 만든 뒤 같은 길로 보낸다(이슈 #125 결정 3).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag, UnicodeDammit
from markitdown.converters import HtmlConverter

from .table_grid import TableCell, TableGrid, render_table, table_inline_text

# 잘못된 rowspan·colspan 값으로 격자가 지나치게 커지지 않게 막는다
_MAX_SPAN = 200
_TOKEN = re.compile(r"DMTABLE(\d+)X")
_LIST_OR_QUOTE_MARKER = re.compile(r"^\s*(?:[>*+-]|\d+\.)?\s*$")


def _span(value: object) -> int:
    try:
        return min(max(int(str(value).strip() or 1), 1), _MAX_SPAN)
    except ValueError:
        return 1


def _rows(table: Tag) -> list[Tag]:
    """표에 직접 딸린 줄(tr)만 모은다. 표 안의 표의 줄은 넣지 않는다."""
    rows: list[Tag] = []
    for child in table.children:
        name = getattr(child, "name", None)
        if name == "tr":
            rows.append(child)
        elif name in ("thead", "tbody", "tfoot"):
            rows.extend(row for row in child.children if getattr(row, "name", None) == "tr")
    return rows


def _cells(row: Tag) -> list[Tag]:
    return [cell for cell in row.children if getattr(cell, "name", None) in ("td", "th")]


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ").split())


def table_to_grid(table: Tag) -> TableGrid:
    """HTML 표를 칸 주소가 있는 격자로 만든다(브라우저의 표 배치 규칙: 이미 찬 자리는 건너뛴다)."""
    rows = _rows(table)
    occupied: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        col_index = 0
        for cell in _cells(row):
            while (row_index, col_index) in occupied:
                col_index += 1
            row_span = min(_span(cell.get("rowspan", 1)), len(rows) - row_index)
            col_span = _span(cell.get("colspan", 1))
            for row_offset in range(row_span):
                for col_offset in range(col_span):
                    occupied.add((row_index + row_offset, col_index + col_offset))
            cells.append(TableCell(row_index, col_index, row_span, col_span, [_text(cell)], is_header=cell.name == "th"))
            col_index += col_span
    cols = max((cell.col + cell.col_span for cell in cells), default=0)
    return TableGrid(len(rows), cols, cells, strict=False)


def _unwrap_single_cell_tables(soup: BeautifulSoup) -> None:
    """칸 하나뿐인 표는 표가 아니라 상자로 쓴 것이라 칸 내용만 남긴다(규칙 1). 안에 든 표는 진짜 표로 살린다."""
    changed = True
    while changed:
        changed = False
        for table in soup.find_all("table"):
            rows = _rows(table)
            cells = _cells(rows[0]) if len(rows) == 1 else []
            if len(cells) != 1:
                continue
            caption = table.find("caption", recursive=False)
            box = cells[0]
            box.name = "div"
            box.attrs = {}
            if caption is not None:
                caption.name = "p"
                caption.attrs = {}
                box.insert(0, caption)
            table.replace_with(box)
            changed = True
            break


def html_to_markdown(html: str) -> str:
    """HTML 글을 마크다운으로 바꾼다. 그림은 대체 글만 남긴다."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for image in soup.find_all("img"):
        alt = " ".join((image.get("alt") or "").split())
        image.replace_with(soup.new_string(alt) if alt else "")

    _unwrap_single_cell_tables(soup)

    rendered: dict[str, str] = {}
    # find_all은 문서 순서라 뒤에서부터 처리하면 표 안의 표가 바깥 표보다 먼저 처리된다
    for table in reversed(soup.find_all("table")):
        grid = table_to_grid(table)
        caption = table.find("caption", recursive=False)
        caption_text = _text(caption) if caption is not None else ""
        if table.find_parent("table") is not None:
            inline = " ".join(part for part in (caption_text, table_inline_text(grid)) if part)
            table.replace_with(soup.new_string(f" {inline} "))
            continue
        markdown = render_table(grid)
        if caption_text and markdown:
            markdown = f"{caption_text}\n\n{markdown}"
        token = f"DMTABLE{len(rendered)}X"
        rendered[token] = markdown
        placeholder = soup.new_tag("p")
        placeholder.string = token
        table.replace_with(placeholder)

    converted = HtmlConverter().convert_string(str(soup)).markdown
    lines: list[str] = []
    for line in converted.splitlines():
        match = _TOKEN.search(line)
        if match is None:
            lines.append(line)
            continue
        before, after = line[:match.start()], line[match.end():]
        if not _LIST_OR_QUOTE_MARKER.fullmatch(before):
            lines.append(before.rstrip())
        block = rendered.pop(match.group(0), "")
        if block:
            lines.extend(["", block, ""])
        if after.strip():
            lines.append(after.strip())
    # 자리표가 변환 중에 사라졌다면 표를 버리지 않고 끝에 붙인다
    for block in rendered.values():
        if block:
            lines.extend(["", block, ""])
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def load_html_markdown(path: str) -> str:
    """HTML 파일을 읽어 마크다운으로 바꾼다. 인코딩은 UTF-8을 먼저, 아니면 문서 선언·CP949 순으로 본다."""
    with open(path, "rb") as file:
        data = file.read()
    dammit = UnicodeDammit(data, known_definite_encodings=["utf-8"], user_encodings=["cp949"], is_html=True)
    html = dammit.unicode_markup if dammit.unicode_markup is not None else data.decode("utf-8", errors="replace")
    return html_to_markdown(html)


def load_docx_markdown(path: str) -> str:
    """DOCX를 MarkItDown과 같은 전처리·mammoth로 HTML로 만든 뒤 HTML 길로 바꾼다."""
    import mammoth
    from markitdown.converter_utils.docx.pre_process import pre_process_docx

    with open(path, "rb") as file:
        html = mammoth.convert_to_html(pre_process_docx(file)).value
    return html_to_markdown(html)
