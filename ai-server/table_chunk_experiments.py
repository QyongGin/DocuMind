"""표 청크 후보(#259 설계 3-3) — PDF 표를 색인하기 전에 다시 쓰는 실험 코드.

설정은 환경값 AI_EXP_CHUNK_*로 켠다. 모두 꺼져 있으면 아무것도 바꾸지 않는다(지금 색인과 글자까지 같은 청크).
표 구조(합친 칸·쪽을 넘는 연결·위치)는 OpenDataLoader JSON에서 읽고, 마크다운 표와는 칸 글 겹침으로 짝 짓는다.
특정 학과명·기호를 조건에 쓰지 않는다. 기호는 그 표의 칸에 실제로 나온 글자에서 고른다.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from opendataloader_contract_adapter import _table_rows

_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEP = re.compile(r"^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$")
_NOTE_START = re.compile(r"^\s*(?:[-*]\s*)?(?:※|\*|주\)|주:|비고|참고|단위|\[주\])")
# 칸 기호 후보에서 뺄 글자: 한글·영문·숫자·공백과 흔한 문장부호
_PLAIN = re.compile(r"[\w\s가-힣()\[\]{}.,:;/\-~%+·'\"<>=&!?@#$^_|]")


@dataclass(frozen=True)
class ChunkExperiment:
    grid: bool = False  # 합친 칸을 채운 표 격자로 마크다운 표를 다시 쓴다
    header_all: bool = False  # 표를 나눌 때 여러 줄 머리글 전체를 조각마다 되풀이한다
    cross_page: bool = False  # 쪽을 넘는 표를 도구가 준 연결로 합친다
    notes: str = ""  # symbol(기호가 든 주석 줄) | block(주석 묶음 전체) | bbox(좌표 규칙)
    table_format: str = ""  # cells(칸마다 머리글을 붙인 줄) | html(합친 칸을 rowspan·colspan으로)
    table_max: int = 0  # 표를 한 청크로: 이 글자 수까지 나누지 않는다

    def rewrites_pages(self) -> bool:
        return self.grid or self.cross_page or bool(self.table_format) or bool(self.notes)

    def settings(self) -> dict:
        values = {"grid": self.grid, "header_all": self.header_all, "cross_page": self.cross_page,
                  "notes": self.notes, "table_format": self.table_format, "table_max": self.table_max}
        return {key: value for key, value in values.items() if value}


def from_env() -> ChunkExperiment:
    def flag(name: str) -> bool:
        return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")

    def number(name: str) -> int:
        try:
            return max(0, int(os.getenv(name, "0").strip() or 0))
        except ValueError:
            return 0

    return ChunkExperiment(
        grid=flag("AI_EXP_CHUNK_GRID"),
        header_all=flag("AI_EXP_CHUNK_HEADER_ALL"),
        cross_page=flag("AI_EXP_CHUNK_CROSS_PAGE"),
        notes=os.getenv("AI_EXP_CHUNK_NOTES", "").strip(),
        table_format=os.getenv("AI_EXP_CHUNK_TABLE_FORMAT", "").strip(),
        table_max=number("AI_EXP_CHUNK_TABLE_MAX"),
    )


# ---------------------------------------------------------------- 표 찾기·짝 짓기


@dataclass
class MdTable:
    start: int  # 쪽 글의 줄 번호(머리 줄)
    end: int  # 마지막 표 줄 다음
    rows: list[list[str]]  # 구분 줄을 뺀 줄들(머리 줄 포함)
    lines: list[str] = field(default_factory=list)  # 원래 줄(구분 줄 포함)


@dataclass
class JsonTable:
    page: int
    tid: Any
    element: Mapping[str, Any]
    filled: list[list[str]]  # 합친 칸을 채운 격자
    prev_id: Any = None
    next_id: Any = None
    bbox: Sequence[float] | None = None
    md: MdTable | None = None
    notes: list[str] = field(default_factory=list)


def split_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def markdown_tables(text: str) -> list[MdTable]:
    lines = text.split("\n")
    out, index = [], 0
    while index < len(lines) - 1:
        if _ROW.match(lines[index]) and _SEP.match(lines[index + 1]):
            rows = [split_cells(lines[index])]
            end = index + 2
            while end < len(lines) and _ROW.match(lines[end]) and not _SEP.match(lines[end]):
                rows.append(split_cells(lines[end]))
                end += 1
            out.append(MdTable(index, end, rows, lines[index:end]))
            index = end
        else:
            index += 1
    return out


def _walk_tables(nodes: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    for node in nodes or []:
        if not isinstance(node, Mapping):
            continue
        if str(node.get("type", "")).lower() == "table":
            yield node
        else:
            yield from _walk_tables(node.get("kids") or [])


def _walk_texts(nodes: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    for node in nodes or []:
        if not isinstance(node, Mapping) or str(node.get("type", "")).lower() == "table":
            continue
        if node.get("content") and node.get("bounding box"):
            yield node
        yield from _walk_texts(node.get("kids") or [])


def json_tables(page_data: Mapping[str, Any], page: int) -> list[JsonTable]:
    out = []
    for element in _walk_tables(page_data.get("kids") or []):
        out.append(JsonTable(page=page, tid=element.get("id"), element=element,
                             filled=[list(row) for row in _table_rows(element)],
                             prev_id=element.get("previous table id"), next_id=element.get("next table id"),
                             bbox=element.get("bounding box")))
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _cell_set(rows: Sequence[Sequence[str]]) -> set[str]:
    return {_norm(cell) for row in rows for cell in row if _norm(cell)}


def pair_tables(md: list[MdTable], js: list[JsonTable]) -> None:
    """같은 쪽의 마크다운 표와 JSON 표를 칸 글 겹침(자카드 0.3 이상)이 큰 것부터 짝 짓는다."""
    scores = []
    for i, m in enumerate(md):
        a = _cell_set(m.rows)
        for j, t in enumerate(js):
            b = _cell_set(t.filled)
            if a and b:
                scores.append((len(a & b) / len(a | b), i, j))
    used_m, used_j = set(), set()
    for score, i, j in sorted(scores, reverse=True):
        if score < 0.3 or i in used_m or j in used_j:
            continue
        js[j].md = md[i]
        used_m.add(i), used_j.add(j)


# ---------------------------------------------------------------- 머리글 줄 수


def header_row_count(rows: Sequence[Sequence[str]], filled: bool,
                     is_subheader: Callable[[list[str], list[list[str]]], bool] | None = None) -> int:
    """위에서부터 머리글 줄 수. 마크다운 표는 서비스의 보강 머리글 판정(is_subheader)을 쓰고, 채운 격자는
    '숫자 없는 짧은 칸으로 된 줄이 위 줄과 같은 열에 같은 글(세로로 합친 머리글 칸)을 가진다'로 본다(최대 3줄)."""
    count = 1
    while count < min(len(rows), 3):
        row = list(rows[count])
        cells = [cell for cell in row if cell.strip()]
        if filled:
            above = rows[count - 1]
            shares = any(cell.strip() and k < len(above) and cell == above[k] for k, cell in enumerate(row))
            plain = len(cells) >= 2 and not any(re.search(r"\d", c) for c in cells) and all(
                len(c) <= 24 and len(c.split()) < 4 for c in cells)
            if not (shares and plain):
                break
        elif not (is_subheader and is_subheader(row, [list(r) for r in rows[:count]])):
            break
        count += 1
    return count


# ---------------------------------------------------------------- 그리기


def render_markdown(rows: Sequence[Sequence[str]]) -> list[str]:
    width = max(len(row) for row in rows)
    padded = [list(row) + [""] * (width - len(row)) for row in rows]
    lines = ["|" + "|".join(padded[0]) + "|", "|" + "|".join(["---"] * width) + "|"]
    lines += ["|" + "|".join(row) + "|" for row in padded[1:]]
    return lines


def header_paths(rows: Sequence[Sequence[str]], header_rows: int) -> list[str]:
    width = max(len(row) for row in rows)
    paths = []
    for k in range(width):
        seq: list[str] = []
        for r in range(header_rows):
            value = rows[r][k].strip() if k < len(rows[r]) else ""
            if value and value not in seq:
                seq.append(value)
        paths.append(" > ".join(seq))
    return paths


def render_cells(rows: Sequence[Sequence[str]], header_rows: int) -> list[str]:
    """칸마다 '행 머리글, 열 머리글 = 값' 한 줄. 행 머리글은 숫자 없는 앞쪽 칸(최대 2개)."""
    paths = header_paths(rows, header_rows)
    lines = []
    for row in rows[header_rows:]:
        label_cols = []
        for k, cell in enumerate(row[:2]):
            if cell.strip() and not re.search(r"\d", cell):
                label_cols.append(k)
        label = " > ".join(dict.fromkeys(row[k].strip() for k in label_cols))
        for k, cell in enumerate(row):
            if k in label_cols or not cell.strip():
                continue
            column = paths[k] if k < len(paths) else ""
            head = ", ".join(part for part in (label, column) if part)
            # 목록 표시('- ')로 시작한다: 쪽 글 정규화가 한글로 시작하는 줄을 앞 한글 줄에 붙이지 않게
            lines.append(f"- {head} = {cell.strip()}" if head else f"- {cell.strip()}")
    return lines


def _span_cells(element: Mapping[str, Any]) -> list[dict]:
    from opendataloader_contract_adapter import _element_text  # 칸 글 모으기는 서비스와 같게
    cells = []
    for row in element.get("rows") or []:
        for cell in row.get("cells") or []:
            cells.append({"r": int(cell.get("row number", 1)) - 1, "c": int(cell.get("column number", 1)) - 1,
                          "rs": int(cell.get("row span", 1) or 1), "cs": int(cell.get("column span", 1) or 1),
                          "t": re.sub(r"\s+", " ", _element_text(cell)).strip()})
    return cells


def render_html(cells: list[dict], header_rows: int, max_chars: int) -> list[str]:
    """rowspan·colspan을 살린 HTML 표(한 줄 = 한 tr). 길면 행 묶음으로 나누고 머리글 줄을 조각마다 되풀이한다.
    조각 경계를 넘는 세로 합친 칸은 조각마다 다시 적고 rowspan을 그 조각 안으로 줄인다."""
    if not cells:
        return []
    last = max(cell["r"] + cell["rs"] for cell in cells)
    starts: dict[int, list[dict]] = {}
    for cell in cells:
        starts.setdefault(cell["r"], []).append(cell)

    def tr(r: int, lo: int, hi: int) -> str:
        tag = "th" if r < header_rows else "td"
        row_cells = list(starts.get(r, []))
        if r == lo:  # 조각 첫 줄: 앞 줄에서 세로로 합쳐 내려온 칸을 다시 적는다
            row_cells += [c for c in cells if c["r"] < lo < c["r"] + c["rs"]]
        parts = []
        for cell in sorted(row_cells, key=lambda c: c["c"]):
            rs = min(cell["r"] + cell["rs"], hi) - max(cell["r"], lo)
            attrs = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cell["cs"]}"' if cell["cs"] > 1 else "")
            parts.append(f"<{tag}{attrs}>{html.escape(cell['t'])}</{tag}>")
        return "<tr>" + "".join(parts) + "</tr>"

    head = [tr(r, 0, header_rows) for r in range(header_rows)]
    budget = max_chars - sum(len(x) + 1 for x in head) - 16
    groups, lo, size = [], header_rows, 0
    for r in range(header_rows, last):
        width = len(tr(r, header_rows, last)) + 1  # 길이 어림(조각 첫 줄의 다시 적은 칸은 빼고 잼)
        if r > lo and size + width > budget:
            groups.append((lo, r))
            lo, size = r, 0
        size += width
    if lo < last:
        groups.append((lo, last))
    out = []
    for n, (lo, hi) in enumerate(groups or [(header_rows, header_rows)]):
        if n:
            out.append("")
        out += ["<table>"] + head + [tr(r, lo, hi) for r in range(lo, hi)] + ["</table>"]
    return out


# ---------------------------------------------------------------- 주석


def table_symbols(rows: Sequence[Sequence[str]]) -> set[str]:
    return {ch for row in rows for cell in row for ch in cell if not _PLAIN.match(ch)}


def notes_from_text(lines: list[str], table: MdTable, mode: str, symbols: set[str]) -> list[str]:
    """표 바로 앞뒤 글 줄에서 주석을 고른다. symbol: 그 표 칸에 나온 기호가 든 줄, block: 표 바로 뒤 주석 묶음 전체."""
    picked = []
    after = []
    for line in lines[table.end:table.end + 12]:
        if _ROW.match(line) or line.lstrip().startswith("#"):
            break
        if line.strip():
            after.append(line.strip())
    if mode == "block":
        for line in after:
            if _NOTE_START.match(line) or (picked and not line.startswith(("-", "#"))):
                picked.append(line)
            elif picked:
                break
        return picked[:12]
    if mode == "symbol" and symbols:
        before = [x.strip() for x in lines[max(0, table.start - 4):table.start] if x.strip() and not _ROW.match(x)]
        for line in before + after:
            if any(symbol in line for symbol in symbols):
                picked.append(line)
    return picked


def notes_from_bbox(page_data: Mapping[str, Any], table: JsonTable, max_chars: int = 200) -> list[str]:
    """좌표 규칙: 표 위아래로 줄 높이 두 배 안에 있는 짧은 글을 이어서 모은다(PDF 좌표는 위로 갈수록 y가 크다)."""
    if not table.bbox:
        return []
    texts = [t for t in _walk_texts(page_data.get("kids") or []) if len(str(t.get("content"))) <= max_chars]
    heights = sorted(t["bounding box"][3] - t["bounding box"][1] for t in texts if t["bounding box"][3] > t["bounding box"][1])
    line = heights[len(heights) // 2] if heights else 12.0
    x0, y0, x1, y1 = table.bbox
    picked, used = [], set()
    for direction in ("below", "above"):
        edge = y0 if direction == "below" else y1
        while True:
            best, gap = None, None
            for k, t in enumerate(texts):
                if k in used:
                    continue
                tx0, ty0, tx1, ty1 = t["bounding box"]
                if tx1 < x0 or tx0 > x1:
                    continue  # 표와 가로로 겹치지 않음
                d = edge - ty1 if direction == "below" else ty0 - edge
                if 0 <= d <= 2 * line and (gap is None or d < gap):
                    best, gap = k, d
            if best is None:
                break
            used.add(best)
            t = texts[best]
            picked.append(re.sub(r"\s+", " ", str(t["content"])).strip())
            edge = t["bounding box"][1] if direction == "below" else t["bounding box"][3]
    return picked


# ---------------------------------------------------------------- 쪽 글 다시 쓰기


@dataclass
class RewriteResult:
    pages: list[str]
    notes: list[tuple[int, str, list[str]]]  # (쪽 위치, 표 머리 줄, 주석 줄들)
    tables: int = 0


def rewrite_pages(page_texts: list[str], page_jsons: list[Mapping[str, Any] | None], exp: ChunkExperiment,
                  is_subheader: Callable[[list[str], list[list[str]]], bool] | None = None,
                  chunk_size: int = 800) -> RewriteResult:
    """쪽마다 마크다운 표를 후보 방식으로 다시 쓴다. page_jsons[i]는 i번째 쪽의 OpenDataLoader JSON(없으면 None)."""
    lines_by_page = [text.split("\n") for text in page_texts]
    tables_by_page: list[list[JsonTable]] = []
    for i, data in enumerate(page_jsons):
        js = json_tables(data, i) if data else []
        pair_tables(markdown_tables(page_texts[i]), js)
        tables_by_page.append(js)
    by_id = {(t.tid): t for page in tables_by_page for t in page if t.tid is not None}

    replace: dict[tuple[int, int], tuple[int, list[str]]] = {}  # (쪽, 시작 줄) → (끝 줄, 새 줄들)
    notes: list[tuple[int, str, list[str]]] = []
    count = 0
    for i, page in enumerate(tables_by_page):
        for t in page:
            if t.md is None:
                continue
            if exp.cross_page and t.prev_id is not None and t.prev_id in by_id and by_id[t.prev_id].md is not None:
                replace[(i, t.md.start)] = (t.md.end, [])  # 앞 조각에 붙였으므로 이 쪽에서는 지운다
                continue
            filled = exp.grid or bool(exp.table_format)
            rows = [list(r) for r in (t.filled if filled else t.md.rows)]
            original = list(t.md.lines)  # 마크다운 그대로 쓰는 경우(격자·형식 후보가 꺼짐) 원래 줄을 지킨다
            joined = False
            if exp.cross_page:
                head = rows[:header_row_count(rows, filled, is_subheader)]
                link = t
                while link.next_id is not None and link.next_id in by_id and by_id[link.next_id].md is not None:
                    link = by_id[link.next_id]
                    more = [list(r) for r in (link.filled if filled else link.md.rows)]
                    drop = 0
                    while drop < len(head) and drop < len(more) and [_norm(c) for c in more[drop]] == [_norm(c) for c in head[drop]]:
                        drop += 1
                    rows += more[drop:]
                    # 원래 줄: 이어진 표의 구분 줄은 늘 빼고, 되풀이된 머리 줄만 뺀다
                    tail = [line for k, line in enumerate(link.md.lines) if k != 1]
                    original += tail[drop:]
                    joined = True
            header_rows = header_row_count(rows, filled, is_subheader)
            if exp.table_format == "cells":
                new = render_cells(rows, header_rows)
            elif exp.table_format == "html":
                cells = _span_cells(t.element)
                new = render_html(cells, header_rows, max(chunk_size, exp.table_max or 0))
            elif exp.grid:
                new = render_markdown(rows)
            else:
                new = original
            if filled or joined:
                replace[(i, t.md.start)] = (t.md.end, new)
                count += 1
            if exp.notes:
                if exp.notes == "bbox":
                    found = notes_from_bbox(page_jsons[i] or {}, t)
                else:
                    found = notes_from_text(lines_by_page[i], t.md, exp.notes, table_symbols(rows))
                if found:
                    notes.append((i, new[0] if new else "", found))
    out_pages = []
    for i, lines in enumerate(lines_by_page):
        result, k = [], 0
        while k < len(lines):
            if (i, k) in replace:
                end, new = replace[(i, k)]
                result += new
                k = end
            else:
                result.append(lines[k])
                k += 1
        out_pages.append("\n".join(result))
    return RewriteResult(out_pages, notes, count)


def attach_notes(chunks: list[tuple[str, int | None]], notes: list[tuple[int, str, list[str]]]) -> list[str]:
    """표 머리 줄이 든 청크마다(같은 쪽이면) 그 표의 주석 줄을 뒤에 붙인다. 이미 든 줄은 다시 붙이지 않는다."""
    out = []
    for text, page in chunks:
        flat = _norm(text)
        extra: list[str] = []
        for note_page, head, lines in notes:
            if not head or _norm(head) not in flat or (page is not None and page != note_page):
                continue
            extra += [line for line in lines if _norm(line) not in flat and line not in extra]
        out.append(text + "\n\n" + "\n".join(extra) if extra else text)
    return out
