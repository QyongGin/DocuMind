"""색인할 때 문서 안 표마다 번호를 매기고, 표 조각이 든 청크에 그 번호를 붙인다(#269).

표 하나가 약 800자 청크 여럿으로 나뉘어 색인되면, 청크만 보고는 어느 표의 조각인지 알 수 없다.
이 모듈은 청크 글을 바꾸지 않고 "이 청크에 든 표 번호" 목록만 계산한다. 메타데이터에 넣는 일은 `main.py`가 한다.

규칙(문서 형식과 상관없이 같다. 특정 문서·학과명·기호를 조건으로 쓰지 않는다):

1. 표: 로더가 낸 글(PDF는 쪽마다)에서 마크다운 표 줄(`| … |`)이 이어진 덩어리. 두 행·두 열에 못 미치는 덩어리
   (빈 칸 하나짜리 상자 등)는 표로 보지 않는다.
2. 쪽을 넘는 표: PDF는 OpenDataLoader JSON 표의 `previous table id`·`next table id`로 이어진 표를 한 번호로 묶는다.
   마크다운 표와 JSON 표는 같은 쪽에서 글 겹침(공백과 줄바꿈 표시를 뺀 세 글자 조각이 서로 든 비율 0.5 이상)이 큰 것부터
   짝 짓는다.
3. 원문 청크: 청크 글의 표 줄 덩어리마다, 그 행들이 가장 많이 든 표(행의 절반 이상)에 붙인다. 청크의 쪽 범위는 글 맞춤으로
   어림한 값이라 거르는 데 쓰지 않고, 같은 점수일 때만 쪽 범위 안의 표, 그다음 바로 앞 조각이 붙은 표에서 가까운 표를 고른다.
4. OpenDataLoader 표 원문 블록: JSON 표 하나를 칸 글로 적은 것이라, 같은 쪽 JSON 표와 글 겹침으로 붙인다.
5. 번호: 1부터. 로더 글 순서의 마크다운 표 묶음이 먼저, 마크다운 표와 짝 짓지 못한 JSON 표 묶음이 그 뒤(쪽 순서).
   같은 문서를 같은 코드로 다시 색인하면 같은 번호가 나온다(입력 순서와 글만으로 정해진다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

TABLE_NUMBERS_METADATA_KEY = "table_numbers"

_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEP = re.compile(r"^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$")
_MIN_ROWS, _MIN_COLS = 2, 2
_PAIR_MIN = 0.5  # 짝 짓기: 세 글자 조각이 서로 든 비율(둘 중 큰 쪽)
_PIECE_MIN = 0.5  # 청크 조각의 행 가운데 표에 든 비율


@dataclass(frozen=True)
class LoaderPage:
    """로더가 낸 글 하나(PDF는 쪽 하나, 다른 형식은 문서 전체나 시트 하나)."""

    page: int | None
    text: str


@dataclass(frozen=True)
class ChunkText:
    """번호를 붙일 청크 하나. key는 결과에서 그 청크를 찾을 이름이다."""

    key: str
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class TableNumbering:
    """문서 하나의 표 번호 결과."""

    table_count: int = 0
    chunk_tables: dict[str, list[int]] = field(default_factory=dict)
    block_tables: dict[str, list[int]] = field(default_factory=dict)
    cross_page_links: int = 0

    def numbers_for_chunk(self, key: str) -> list[int]:
        return sorted(self.chunk_tables.get(key, []))

    def numbers_for_block(self, key: str) -> list[int]:
        return sorted(self.block_tables.get(key, []))


# ---------------------------------------------------------------- 표 줄 읽기


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def _pipe_cells(line: str) -> list[str]:
    """OpenDataLoader 표 원문 블록 한 줄('가 | 나 | 다')의 칸 글."""
    return [cell.strip() for cell in line.split(" | ")]


def _squash(text: str) -> str:
    """비교용: 줄바꿈 표시(<br>)와 공백을 모두 뺀다."""
    return re.sub(r"\s+", "", re.sub(r"<br\s*/?>", "", text or "", flags=re.I))


def _row_key(line: str) -> str:
    return "|".join(_squash(cell) for cell in _cells(line))


@dataclass
class _Run:
    """글 안에서 마크다운 표 줄이 이어진 덩어리(구분 줄 포함)."""

    lines: list[str]

    @property
    def rows(self) -> list[list[str]]:
        return [_cells(line) for line in self.lines if not _SEP.match(line)]

    @property
    def keys(self) -> list[str]:
        return [_row_key(line) for line in self.lines if not _SEP.match(line) and _squash(line.replace("|", ""))]

    def is_table(self) -> bool:
        rows = self.rows
        if len(rows) < _MIN_ROWS or max(len(row) for row in rows) < _MIN_COLS:
            return False
        return any(_squash(cell) for row in rows for cell in row)


def _runs(text: str) -> list[_Run]:
    lines = (text or "").split("\n")
    out: list[_Run] = []
    index = 0
    while index < len(lines):
        if _ROW.match(lines[index]):
            end = index
            while end < len(lines) and _ROW.match(lines[end]):
                end += 1
            out.append(_Run(lines[index:end]))
            index = end
        else:
            index += 1
    return out


def has_table_rows(text: str) -> bool:
    """글에 표로 보는 덩어리(두 행·두 열 이상)가 하나라도 있는가."""
    return any(run.is_table() for run in _runs(text))


# ---------------------------------------------------------------- OpenDataLoader JSON


def _text_of(node: Any) -> str:
    if not isinstance(node, Mapping):
        return ""
    parts = [str(node.get("content") or "").strip()]
    parts += [_text_of(child) for child in node.get("kids") or []]
    return " ".join(part for part in parts if part)


def _json_tables(page_data: Mapping[str, Any]) -> list[dict]:
    """쪽 JSON의 표: id, 다음 표 id, 칸 글."""
    out: list[dict] = []

    def walk(nodes: Iterable[Any]) -> None:
        for node in nodes or []:
            if not isinstance(node, Mapping):
                continue
            if str(node.get("type", "")).lower() == "table":
                texts = [_text_of(cell) for row in node.get("rows") or [] for cell in row.get("cells") or []]
                out.append({"id": node.get("id"), "next": node.get("next table id"), "texts": texts})
            else:
                walk(node.get("kids") or [])

    walk(page_data.get("kids") or [])
    return out


def _grams(texts: Iterable[str]) -> set[str]:
    """글 겹침 비교용 세 글자 조각(공백·줄바꿈 표시·줄 나눔 하이픈을 뺀 글)."""
    flat = "".join(_squash(text) for text in texts).replace("­", "")
    return {flat[i:i + 3] for i in range(max(0, len(flat) - 2))}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    common = len(a & b)
    return max(common / len(a), common / len(b))


def _pair(left: list[set[str]], right: list[set[str]]) -> dict[int, int]:
    """글 겹침이 큰 것부터 하나씩 짝 짓는다(왼쪽 번호 → 오른쪽 번호)."""
    scores = sorted(((_overlap(a, b), i, j) for i, a in enumerate(left) for j, b in enumerate(right)), reverse=True)
    pairs: dict[int, int] = {}
    used: set[int] = set()
    for score, i, j in scores:
        if score < _PAIR_MIN or i in pairs or j in used:
            continue
        pairs[i] = j
        used.add(j)
    return pairs


def _page_of(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 번호 매기기


@dataclass
class _Unit:
    page: int | None
    keys: set[str]
    grams: set[str]
    node: int


def number_document_tables(
    loader_pages: Sequence[LoaderPage],
    chunks: Sequence[ChunkText],
    json_pages: Sequence[tuple[int | None, Mapping[str, Any]]] = (),
    table_blocks: Sequence[ChunkText] = (),
) -> TableNumbering:
    """문서 하나의 표에 번호를 매기고 청크·표 원문 블록마다 든 표 번호를 돌려준다.

    loader_pages: 로더가 낸 글(청크로 나누기 전). json_pages: PDF의 OpenDataLoader JSON 쪽 자료(쪽 번호, JSON).
    chunks: 원문 청크(청크 순서). table_blocks: OpenDataLoader 표 원문 블록(`가 | 나` 줄, page_start에 쪽).
    """
    parent: list[int] = []

    def node() -> int:
        parent.append(len(parent))
        return len(parent) - 1

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> bool:
        a, b = find(a), find(b)
        if a == b:
            return False
        parent[max(a, b)] = min(a, b)
        return True

    units: list[_Unit] = []
    for loader_page in loader_pages:
        for run in _runs(loader_page.text):
            if run.is_table():
                units.append(_Unit(
                    page=_page_of(loader_page.page),
                    keys=set(run.keys),
                    grams=_grams(cell for row in run.rows for cell in row),
                    node=node(),
                ))

    # JSON 표: 같은 쪽 마크다운 표와 짝 짓고, 다음 표 id로 잇는다
    json_nodes: dict[Any, int] = {}
    json_info: dict[int, dict] = {}
    for raw_page, data in json_pages:
        if not isinstance(data, Mapping):
            continue
        page = _page_of(raw_page)
        tables = _json_tables(data)
        for table in tables:
            json_nodes[table["id"]] = node()
            json_info[json_nodes[table["id"]]] = {**table, "page": page, "grams": _grams(table["texts"])}
        mine = [unit for unit in units if unit.page == page]
        pairs = _pair([unit.grams for unit in mine], [json_info[json_nodes[table["id"]]]["grams"] for table in tables])
        for i, j in pairs.items():
            union(mine[i].node, json_nodes[tables[j]["id"]])
    links = 0
    for info in json_info.values():
        if info["next"] is not None and info["next"] in json_nodes:
            links += union(json_nodes[info["id"]], json_nodes[info["next"]])

    # 표 원문 블록 → 같은 쪽 JSON 표
    block_nodes: list[tuple[ChunkText, int]] = []
    for block in table_blocks:
        page = _page_of(block.page_start)
        block_grams = _grams(
            cell for line in (block.text or "").split("\n") if line.strip() for cell in _pipe_cells(line)
        )
        scored = sorted(
            ((_overlap(block_grams, info["grams"]), n) for n, info in json_info.items()
             if page is None or info["page"] == page),
            reverse=True,
        )
        block_nodes.append((block, scored[0][1] if scored and scored[0][0] >= _PAIR_MIN else -1))

    # 번호: 마크다운 표 묶음(로더 글 순서) 먼저, 블록만 있는 JSON 표 묶음(쪽 순서) 그 뒤
    order_keys: dict[int, tuple] = {}
    for position, unit in enumerate(units):
        order_keys.setdefault(find(unit.node), (0, position))
    for position, (_, n) in enumerate(block_nodes):
        if n >= 0:
            order_keys.setdefault(find(n), (1, json_info[n]["page"] or 0, position))
    numbers = {root: number for number, root in enumerate(sorted(order_keys, key=lambda r: order_keys[r]), 1)}
    result = TableNumbering(table_count=len(numbers), cross_page_links=links)

    # 원문 청크의 표 조각 → 표 번호
    last = 0  # 바로 앞 조각이 붙은 표(로더 글 순서)
    for chunk in chunks:
        low, high = _page_of(chunk.page_start), _page_of(chunk.page_end)
        for run in _runs(chunk.text):
            keys = run.keys
            if not keys or not units:
                continue
            scored = []
            for position, unit in enumerate(units):
                score = sum(1 for key in keys if key in unit.keys) / len(keys)
                in_range = low is not None and unit.page is not None and low <= unit.page <= (high or low)
                scored.append((score, in_range, -abs(position - last), position))
            best = max(scored)
            if best[0] < _PIECE_MIN:
                continue
            last = best[3]
            number = numbers[find(units[best[3]].node)]
            found = result.chunk_tables.setdefault(chunk.key, [])
            if number not in found:
                found.append(number)

    for block, n in block_nodes:
        if n >= 0:
            result.block_tables[block.key] = [numbers[find(n)]]
    return result
