"""표 격자를 마크다운 표로 옮긴다 (HWP·HWPX·HTML·DOCX 공통).

마크다운 표는 칸 병합을 나타내지 못한다. 그래서 병합된 자리마다 무엇을 적을지 아래 규칙으로 정한다
(이슈 #125 결정 2. 근거 수치는 수집한 HWP 467개·HTML 2,215개 실측).

1. 칸 하나뿐인 1×1 표는 표가 아니라 글로 낸다(글상자처럼 쓴 표).
2. 맨 윗줄이 전체 폭 한 칸이면 표 제목으로 보고 표 위 글줄로 뺀다.
3. 머리 줄은 HTML이면 th로만 된 앞쪽 줄들, 그 밖에는 첫 줄이다. 왼쪽 위 칸이 아래로 k줄 병합이면
   머리를 k줄로 보고 한 줄로 합친다(예: "1학기 등록금"). 표 사실 코드의 큰 표 나누기
   (`_split_table_block`)가 머리 한 줄만 알아서 여러 줄로 내면 뒤 조각에 머리가 빠진다.
4. 세로 병합 값은 줄마다 채운다. 행 하나만 읽어도 뜻이 통하게 하기 위해서다.
5. 본문 가로 병합은 그 범위의 열 이름이 서로 다르고 값이 짧으면(`SPAN_FILL_MAX_CHARS` 이하) 칸마다 채우고,
   아니면 첫 칸에만 둔다. 긴 설명을 열마다 되풀이하지 않기 위해서다.
6. 본문의 전체 폭 줄(구분 제목·주석 줄)은 첫 칸에만 둔다.
7. 칸 글의 '|'와 줄바꿈은 다른 글자로 바꾼다. 표 사실 코드(`_split_markdown_cells`)는 '\\|'도 칸 구분으로 자른다.
8. 칸 자리가 겹치거나 비는 표(해석이 어긋난 표)는 표로 내지 않고 글로 낸다.
9. 글 없이 빈 줄만 두고 이어지는 두 표 사이에는 `TABLE_SEPARATOR` 줄을 넣는다. 기존 표 블록 나누기
   (`_split_markdown_table_blocks`)는 빈 줄을 표 블록에 붙여 두 표를 한 표로 합치고, 그러면 뒤 표의 값이 앞 표의
   열 이름으로 읽힌다(수집 HWP 112개 파일 216곳). PDF의 쪽 넘김 표가 이 합치기에 기대고 있을 수 있어 기존 코드는 두고
   여기서 끊는다. 이 줄은 '>'로 끝나 표 제목 후보(`_extract_table_caption`)에서도 빠진다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Union

logger = logging.getLogger(__name__)

# 가로 병합 값을 칸마다 채우는 최대 글자 수(규칙 5). 수집 HWP에서 20자 이하가 대상 칸의 63%(1,198/1,900)이고
# 표 글자는 3%만 늘었다. 바꾸면 색인한 문서의 청크가 달라지므로 서비스·데이터셋 색인을 함께 다시 만든다.
SPAN_FILL_MAX_CHARS = 20

# 이어지는 두 표를 끊는 줄(규칙 9). 표 줄도 빈 줄도 아니고, 표 제목 후보도 아니다
TABLE_SEPARATOR = "<!-- -->"
_ADJACENT_TABLES = re.compile(r"(?m)^(\|[^\n]*\|)[ \t]*\n(?:[ \t]*\n)+(?=[ \t]*\|)")

# 표 안의 표를 바깥 칸 글로 펼칠 때 쓰는 구분자(규칙 7과 겹치지 않는 글자)
_INLINE_CELL_SEP = " · "
_INLINE_ROW_SEP = " / "


@dataclass
class TableCell:
    """표의 칸 하나. blocks는 칸 안의 글(str)과 표 안의 표(TableGrid)를 차례대로 담는다."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    blocks: list[Block] = field(default_factory=list)
    is_header: bool = False


@dataclass
class TableGrid:
    """칸 주소와 병합 수가 있는 표.

    strict가 참이면(HWP·HWPX) 비거나 겹친 칸 자리를 해석이 어긋난 것으로 보고 글로 낸다.
    HTML은 줄마다 칸 수가 달라도 정상이라 strict를 끄고 빈 자리를 빈칸으로 둔다.
    """

    rows: int
    cols: int
    cells: list[TableCell] = field(default_factory=list)
    strict: bool = True


Block = Union[str, TableGrid]


def clean_cell_text(text: str) -> str:
    """칸 글을 한 줄로 만들고 표 구분 글자와 겹치지 않게 한다(규칙 7)."""
    return re.sub(r"\s+", " ", text.replace("|", "/")).strip()


def cell_text(cell: TableCell) -> str:
    """칸 안의 글과 표 안의 표를 한 줄 글로 합친다."""
    parts: list[str] = []
    for block in cell.blocks:
        if isinstance(block, TableGrid):
            parts.append(table_inline_text(block))
        else:
            parts.append(block)
    return clean_cell_text(" ".join(part for part in parts if part))


def table_inline_text(table: TableGrid) -> str:
    """표 안의 표를 "칸 · 칸 / 다음 줄" 모양의 한 줄 글로 펼친다."""
    lines: list[str] = []
    for row in range(max(table.rows, 1)):
        texts = [cell_text(cell) for cell in sorted(table.cells, key=lambda c: c.col) if cell.row == row]
        texts = [text for text in texts if text]
        if texts:
            lines.append(_INLINE_CELL_SEP.join(texts))
    return _INLINE_ROW_SEP.join(lines)


def separate_adjacent_tables(markdown: str) -> str:
    """빈 줄만 사이에 둔 두 마크다운 표 사이에 끊는 줄을 넣는다(규칙 9)."""
    return _ADJACENT_TABLES.sub(lambda match: f"{match.group(1)}\n\n{TABLE_SEPARATOR}\n\n", markdown)


def blocks_to_markdown(blocks: list[Block]) -> str:
    """글·표 블록을 마크다운으로 잇는다. 표 앞뒤에는 빈 줄을 둬 글과 섞이지 않게 한다."""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TableGrid):
            rendered = render_table(block)
            if rendered:
                parts.append(f"\n{rendered}\n")
        else:
            text = block.strip()
            if text:
                parts.append(text)
    markdown = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _layout(table: TableGrid) -> tuple[dict[tuple[int, int], TableCell], bool]:
    """칸 자리 → 칸 사전을 만들고, 겹치거나 표 밖으로 나간 칸이 있었는지 돌려준다."""
    covered: dict[tuple[int, int], TableCell] = {}
    broken = False
    for cell in table.cells:
        if not (0 <= cell.row < table.rows and 0 <= cell.col < table.cols):
            broken = True
            continue
        row_end = min(cell.row + max(cell.row_span, 1), table.rows)
        col_end = min(cell.col + max(cell.col_span, 1), table.cols)
        for row in range(cell.row, row_end):
            for col in range(cell.col, col_end):
                if (row, col) in covered:
                    broken = True
                covered[(row, col)] = cell
    return covered, broken


def _span_cols(cell: TableCell, cols: int) -> int:
    return min(cell.col + max(cell.col_span, 1), cols) - cell.col


def _table_as_text(table: TableGrid) -> str:
    """해석이 어긋난 표를 줄마다 칸 글을 이은 글로 낸다(규칙 8)."""
    lines: list[str] = []
    for row in sorted({cell.row for cell in table.cells}):
        texts = [cell_text(cell) for cell in sorted(table.cells, key=lambda c: c.col) if cell.row == row]
        texts = [text for text in texts if text]
        if texts:
            lines.append(_INLINE_CELL_SEP.join(texts))
    return "\n".join(lines)


def render_table(table: TableGrid) -> str:
    """표 하나를 규칙 1~8에 따라 마크다운(표 위 제목 글줄 포함)으로 낸다. 빈 표는 빈 문자열."""
    if table.rows <= 0 or table.cols <= 0 or not table.cells:
        return ""

    covered, broken = _layout(table)
    gaps = len(covered) < table.rows * table.cols
    if broken or (table.strict and gaps):
        logger.warning(
            "[table_grid] 칸 자리가 어긋난 표를 글로 냅니다. rows=%s cols=%s cells=%s overlap_or_outside=%s gaps=%s",
            table.rows, table.cols, len(table.cells), broken, gaps,
        )
        return _table_as_text(table)

    texts = {id(cell): cell_text(cell) for cell in table.cells}
    if not any(texts.values()):
        return ""

    # 규칙 1: 1×1 표는 칸 안의 블록(글·표)을 그대로 낸다
    if table.rows == 1 and table.cols == 1:
        return blocks_to_markdown(table.cells[0].blocks)

    def at(row: int, col: int) -> TableCell | None:
        return covered.get((row, col))

    def starts_in(row: int) -> list[TableCell]:
        return [cell for cell in table.cells if cell.row == row]

    # 규칙 2: 맨 윗줄이 전체 폭 한 칸이면 표 제목 글줄로 뺀다(남는 줄이 2줄 이상일 때)
    top = 0
    captions: list[str] = []
    while table.cols >= 2 and table.rows - top >= 2:
        row_cells = starts_in(top)
        if not (
            len(row_cells) == 1
            and row_cells[0].col == 0
            and _span_cols(row_cells[0], table.cols) == table.cols
            and max(row_cells[0].row_span, 1) == 1
        ):
            break
        if texts[id(row_cells[0])]:
            captions.append(texts[id(row_cells[0])])
        top += 1

    # 규칙 3: 머리 줄 수
    remaining = table.rows - top
    if any(cell.is_header for cell in table.cells):
        depth = 0
        for row in range(top, table.rows):
            row_cells = starts_in(row)
            if row_cells and all(cell.is_header for cell in row_cells):
                depth += 1
            else:
                break
        depth = max(depth, 1)
    else:
        corner = at(top, 0)
        depth = max(corner.row_span, 1) if corner is not None and corner.row == top else 1
    depth = min(depth, remaining)
    if depth >= remaining and remaining >= 2:
        depth = 1

    labels: list[str] = []
    for col in range(table.cols):
        parts: list[str] = []
        for row in range(top, top + depth):
            cell = at(row, col)
            text = texts[id(cell)] if cell is not None else ""
            if text and text not in parts:
                parts.append(text)
        labels.append(" ".join(parts))

    body: list[list[str]] = []
    for row in range(top + depth, table.rows):
        values: list[str] = []
        for col in range(table.cols):
            cell = at(row, col)
            if cell is None:
                values.append("")
                continue
            text = texts[id(cell)]
            if cell.col == col:
                values.append(text)  # 칸이 시작하는 자리이거나 세로 병합(규칙 4)
                continue
            span = _span_cols(cell, table.cols)
            if cell.col == 0 and span == table.cols:
                values.append("")  # 규칙 6
            elif len(text) <= SPAN_FILL_MAX_CHARS and len(set(labels[cell.col:cell.col + span])) > 1:
                values.append(text)  # 규칙 5
            else:
                values.append("")
        if any(values):
            body.append(values)

    lines = [
        "| " + " | ".join(labels) + " |",
        "| " + " | ".join("---" for _ in labels) + " |",
    ]
    lines += ["| " + " | ".join(values) + " |" for values in body]
    table_markdown = "\n".join(lines)
    if captions:
        return "\n".join(captions) + "\n\n" + table_markdown
    return table_markdown
