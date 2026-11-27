"""표 전체와 표 아래 주석을 한 근거 블록으로 조립한다(#274).

표가 여러 청크로 나뉘어 색인되면 한 조각만 검색돼도 나머지 행과 주석이 프롬프트에 없다. 색인은 표 조각이 든 청크에
문서 안 표 번호(`table_numbers`, #269)를 남기므로, 검색된 청크의 표 번호로 같은 문서의 조각을 모두 모아 표 전체를 넣는다.
이 모듈은 글과 메타데이터만 받는 순수 함수다. Chroma에서 조각을 꺼내고 머리말을 쓰고 설정을 읽는 일은 `main.py`가 한다.

규칙(특정 문서·학과명·금액을 조건으로 쓰지 않는다. 줄 모양과 메타데이터로만 가른다):

1. 표 모양: 합친 칸을 채운 표(PDF OpenDataLoader 표 원문 블록, 쪽마다 한 조각)가 있으면 그것을 쪽 순서로 잇고, 없으면 원문
   청크의 마크다운 표 조각을 청크 순서로 잇는다. 뒤 조각이 되풀이한 머리글과 청크 겹침 행은 한 번만 둔다.
2. 블록 본문은 검색된 청크 글의 원문 순서 조각이다. 조각마다 이름표를 붙인다: 표 밖 글은 「내용:」, 표 자리는 「표:」(표 전체),
   주석은 「표 아래 주석:」. 주석 뒤에 주석이 아닌 글이 이어지면 「내용:」을 다시 단다. 검색된 청크의 표 밖 글은 발췌하지 않고
   전부 넣고, 표를 채우려고 가져온 조각의 표 밖 글은 넣지 않는다.
3. 주석: 표 바로 뒤, 다음 표나 제목 줄 전까지에서 주석 표시(`※`, `*`, `＊`, `주)`, `(주)`, `주 1)` 모양)로 시작하는 줄.
   줄 머리의 글머리 기호(`-`, `·`)와 공백은 떼고 본다. 번호 각주(`1)`, `①`), `1.`, `비고`, `참고`, `단위`는 주석 표시가 아니다.
   표를 채우려고 가져온 조각 뒤의 주석(큰 표는 끝 쪽에 한 번 나온다)도 표 바로 아래에 붙인다.
4. 같은 표의 조각이 근거에 여럿이면 가장 높은 순위 블록 하나에 표를 한 번만 넣는다. 뒤 순위 블록은 표 줄과 주석 줄을 뺀 뒤
   (1) 남는 글이 없거나 (2) 남은 줄이 모두 그 표의 블록에 이미 든 줄(공백을 지운 글자가 똑같은 줄)이거나 (3) 새로 남는 줄이
   제목 줄(`#`으로 시작하는 줄, 색인이 청크 첫 줄에 붙인 섹션 줄)뿐이면 뺀다. 본문이 남으면 표 밖 글만 가진 블록으로 둔다.
5. 줄인 표(문맥 길이를 넘을 때만, `main.py`가 정함): 검색된 조각과 머리글, 주석. 이름표는 「표 일부:」다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from table_numbering import _PIECE_MIN, _ROW, _SEP, _cells, _grams, _overlap, _row_key, _squash

TEXT, TABLE, NOTE = "text", "table", "note"
LABELS = {TEXT: "내용:", NOTE: "표 아래 주석:"}
TABLE_LABEL_FULL, TABLE_LABEL_PARTIAL = "표:", "표 일부:"
HEADING = re.compile(r"^\s*#")
# 줄 머리에서 떼는 글머리 기호와 공백
_BULLET_PREFIX = re.compile(r"^[\s\-·]+")
# 주석 표시: ※, *, ＊, (주), 주), 주 1)
NOTE_MARK = re.compile(r"^(?:※|\*|＊|\(주\)|주\s*\d*\s*\))")

TableKey = tuple[str, int]


def is_note_line(line: str) -> bool:
    """주석 표시로 시작하는 줄인가. 줄 머리의 글머리 기호(-, ·)와 공백은 떼고 본다."""
    return bool(NOTE_MARK.match(_BULLET_PREFIX.sub("", line)))


def squash(line: str) -> str:
    """같은 줄 비교용: 공백(과 줄바꿈 표시)을 모두 지운 글."""
    return _squash(line)


# ---------------------------------------------------------------- 청크 글 나누기


@dataclass(frozen=True)
class Run:
    """청크 글에서 마크다운 표 줄이 이어진 덩어리. start·end는 글의 줄 번호(end는 마지막 표 줄 다음)."""

    start: int
    end: int
    lines: tuple[str, ...]

    @property
    def keys(self) -> list[str]:
        return [_row_key(line) for line in self.lines if not _SEP.match(line) and _squash(line.replace("|", ""))]

    @property
    def is_piece(self) -> bool:
        """표 조각으로 볼 덩어리: 빈 칸이 아닌 행이 있고 두 칸 이상인 행이 있다(한 칸 상자는 표가 아니다)."""
        rows = [_cells(line) for line in self.lines if not _SEP.match(line)]
        return bool(self.keys) and max(len(row) for row in rows) >= 2


def table_runs(text: str) -> list[Run]:
    lines = (text or "").split("\n")
    out: list[Run] = []
    index = 0
    while index < len(lines):
        if _ROW.match(lines[index]):
            end = index
            while end < len(lines) and _ROW.match(lines[end]):
                end += 1
            out.append(Run(index, end, tuple(lines[index:end])))
            index = end
        else:
            index += 1
    return out


def assign_runs(text: str, numbers: Sequence[int], known_keys: Mapping[int, set[str]]) -> list[tuple[Run, int]]:
    """청크 글의 표 조각마다 표 번호를 정한다. 색인은 청크에 든 표 번호 목록만 남기므로 조각과 번호를 다시 짝 짓는다.

    번호가 하나면 모든 조각이 그 표다. 둘 이상이면 같은 문서의 다른 조각(번호가 하나뿐인 청크)에서 모은 행 열쇠와 행 절반 이상이
    같은 표로 붙이고, 못 붙인 조각은 글 순서대로 남은 번호와 짝 짓는다(번호는 로더 글 순서로 매겨져 글 순서와 같다).
    남는 조각은 바로 앞 조각의 표로 본다.
    """
    pieces = [run for run in table_runs(text) if run.is_piece]
    ordered = sorted(set(int(number) for number in numbers))
    if not pieces or not ordered:
        return []
    if len(ordered) == 1:
        return [(run, ordered[0]) for run in pieces]
    assigned: dict[int, int] = {}
    for position, run in enumerate(pieces):
        keys = run.keys
        scored = sorted(
            ((sum(1 for key in keys if key in known_keys.get(number, set())) / len(keys), number) for number in ordered),
            reverse=True,
        )
        if scored and scored[0][0] >= _PIECE_MIN:
            assigned[position] = scored[0][1]
    remaining = [number for number in ordered if number not in assigned.values()]
    for position in range(len(pieces)):
        if position not in assigned and remaining:
            assigned[position] = remaining.pop(0)
    out: list[tuple[Run, int]] = []
    for position, run in enumerate(pieces):
        number = assigned.get(position)
        if number is None:
            number = out[-1][1] if out else next(assigned[p] for p in sorted(assigned))
        out.append((run, number))
    return out


@dataclass
class Segment:
    """블록 본문의 조각 하나: 표 밖 글, 표 자리, 주석."""

    kind: str
    lines: list[str]
    table: int | None = None


def split_segments(text: str, assignments: Sequence[tuple[Run, int]]) -> list[Segment]:
    """청크 글을 원문 순서의 조각으로 나눈다. 표 조각 뒤 주석 범위(다음 표 조각이나 제목 줄 전까지)의 주석 표시 줄은 주석이다.

    빈 줄은 조각 경계에서 떼고, 표 밖 글 조각 안의 빈 줄은 그대로 둔다.
    """
    lines = (text or "").split("\n")
    run_at = {run.start: (run, number) for run, number in assignments}
    segments: list[Segment] = []
    pending_blank = 0
    note_table: int | None = None  # 주석 범위가 열린 표
    index = 0

    def push(kind: str, line: str, table: int | None) -> None:
        nonlocal pending_blank
        last = segments[-1] if segments else None
        if last is not None and last.kind == kind and last.table == table and kind != TABLE:
            if kind == TEXT:
                last.lines += [""] * pending_blank
            last.lines.append(line)
        else:
            segments.append(Segment(kind, [line], table))
        pending_blank = 0

    while index < len(lines):
        if index in run_at:
            run, number = run_at[index]
            segments.append(Segment(TABLE, list(run.lines), number))
            pending_blank = 0
            note_table = number
            index = run.end
            continue
        line = lines[index]
        index += 1
        if not line.strip():
            pending_blank += 1
            continue
        if HEADING.match(line):
            note_table = None
        if note_table is not None and is_note_line(line):
            push(NOTE, line, note_table)
        else:
            push(TEXT, line, None)
    return segments


# ---------------------------------------------------------------- 표 잇기


def _overlap_rows(out: Sequence[str], lines: Sequence[str], key: Callable[[str], str]) -> int:
    for size in range(min(len(out), len(lines)), 0, -1):
        if [key(line) for line in out[-size:]] == [key(line) for line in lines[:size]]:
            return size
    return 0


def header_lines(lines: Sequence[str]) -> list[str]:
    """마크다운 표의 머리(머리 줄 + 구분 줄). 구분 줄이 없으면 첫 줄만."""
    if len(lines) >= 2 and _SEP.match(lines[1]):
        return list(lines[:2])
    return list(lines[:1])


def join_raw_pieces(pieces: Iterable[Sequence[str]]) -> list[str]:
    """원문 청크 표 조각(청크 순서)을 표 하나로 잇는다. 뒤 조각이 되풀이한 머리(머리 줄 + 구분 줄)와 겹친 행은 한 번만 둔다."""
    out: list[str] = []
    header: list[str] = []
    for piece in pieces:
        lines = [line.rstrip() for line in piece]
        if not out:
            out = list(lines)
            header = lines[:2] if len(lines) >= 2 and _SEP.match(lines[1]) else []
            continue
        if header and len(lines) >= 2 and _row_key(lines[0]) == _row_key(header[0]) and _SEP.match(lines[1]):
            lines = lines[2:]
        out += lines[_overlap_rows(out, lines, _row_key):]
    return out


def join_odl_pieces(pieces: Iterable[Sequence[str]]) -> tuple[list[str], int]:
    """표 원문 블록 조각(쪽 순서)을 잇는다. 뒤 조각 앞에 되풀이된 머리 행은 뺀다. (이은 줄, 되풀이된 머리 행 수)."""
    out: list[str] = []
    repeated_header = 0
    for piece in pieces:
        lines = [line.rstrip() for line in piece if line.strip()]
        if out:
            repeated = 0
            while repeated < len(lines) and repeated < len(out) and _squash(lines[repeated]) == _squash(out[repeated]):
                repeated += 1
            repeated_header = max(repeated_header, repeated)
            lines = lines[repeated:]
            lines = lines[_overlap_rows(out, lines, _squash):]
        out += lines
    return out, repeated_header


def _pipe_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.split(" | ")]


# ---------------------------------------------------------------- 표 하나


@dataclass(frozen=True)
class RawPiece:
    """같은 표 번호가 든 원문 청크(색인 순서 chunk_index)."""

    chunk_index: int
    text: str
    numbers: tuple[int, ...]


@dataclass(frozen=True)
class OdlPiece:
    """같은 표 번호가 든 표 원문 블록(쪽 하나). order는 (쪽, 블록 순번)."""

    chunk_id: str
    order: tuple[int, int]
    text: str


@dataclass
class TableSource:
    """Chroma에서 꺼낸 표 하나의 조각들."""

    document_id: str
    number: int
    raw_pieces: list[RawPiece] = field(default_factory=list)
    odl_pieces: list[OdlPiece] = field(default_factory=list)


@dataclass
class AssembledTable:
    """이어 붙인 표 하나: 모양(odl/raw), 표 전체 줄, 머리글, 주석, 줄일 때 쓸 조각."""

    key: TableKey
    shape: str
    full: list[str]
    header: list[str]
    notes: list[str]
    odl_pieces: list[OdlPiece]

    def partial(self, retrieved_runs: Sequence[tuple[int, Sequence[str]]], retrieved_odl_ids: set[str]) -> list[str]:
        """줄인 표: 검색된 조각(청크 순서)과 머리글. 채운 표 모양이면 검색된 원문 조각과 글이 겹치는 쪽 조각을 고른다."""
        if self.shape == "odl":
            run_grams = [_grams(cell for line in lines for cell in _cells(line)) for _, lines in retrieved_runs]
            chosen = [
                piece for piece in self.odl_pieces
                if piece.chunk_id in retrieved_odl_ids
                or any(_overlap(grams, _grams(cell for line in piece.text.split("\n") if line.strip()
                                              for cell in _pipe_cells(line))) >= _PIECE_MIN for grams in run_grams)
            ]
            if chosen:
                lines, _ = join_odl_pieces(piece.text.split("\n") for piece in chosen)
                return self._with_header(lines)
        if not retrieved_runs:
            return list(self.full)
        lines = join_raw_pieces(lines for _, lines in sorted(retrieved_runs, key=lambda item: item[0]))
        # 채운 표에서 고를 쪽이 없으면 검색된 원문 조각을 원문 모양 그대로 둔다(채운 표의 머리글은 모양이 달라 붙이지 않는다)
        return self._with_header(lines) if self.shape == "raw" else lines

    def retrieved_only(self, retrieved_runs: Sequence[tuple[int, Sequence[str]]], retrieved_odl_ids: set[str]) -> list[str]:
        """가장 작게 줄인 표: 검색된 조각 그 자체와 머리글. 「표 일부」(partial)로도 프롬프트가 상한을 넘을 때 쓴다.

        채운 표 모양에서 partial은 검색된 조각과 글이 겹치는 표 원문 블록을 통째로 고르는데, 표 원문 블록 하나가 표 전체일 수
        있다(여러 쪽에 걸친 표). 여기서는 검색된 표 원문 블록만, 없으면 검색된 원문 청크의 표 줄을 원문 모양 그대로 쓴다.
        검색된 조각이 없으면 머리글만 남는다.
        """
        if self.shape == "odl":
            chosen = [piece for piece in self.odl_pieces if piece.chunk_id in retrieved_odl_ids]
            if chosen:
                lines, _ = join_odl_pieces(piece.text.split("\n") for piece in chosen)
                return self._with_header(lines)
            if retrieved_runs:
                return join_raw_pieces(lines for _, lines in sorted(retrieved_runs, key=lambda item: item[0]))
            return list(self.header)
        if not retrieved_runs:
            return list(self.header)
        return self._with_header(join_raw_pieces(lines for _, lines in sorted(retrieved_runs, key=lambda item: item[0])))

    def _with_header(self, lines: list[str]) -> list[str]:
        if not self.header or not lines:
            return lines
        if [_squash(line) for line in lines[:len(self.header)]] == [_squash(line) for line in self.header]:
            return lines
        return list(self.header) + lines


def document_known_keys(sources: Iterable[TableSource]) -> dict[int, set[str]]:
    """표 번호마다, 번호가 하나뿐인 원문 청크의 표 조각 행 열쇠. 표가 둘 이상 든 청크의 조각을 짝 짓는 데 쓴다."""
    known: dict[int, set[str]] = {}
    for source in sources:
        for piece in source.raw_pieces:
            if len(set(piece.numbers)) == 1:
                for run in table_runs(piece.text):
                    if run.is_piece:
                        known.setdefault(source.number, set()).update(run.keys)
    return known


def _notes_after(text: str, assignments: Sequence[tuple[Run, int]], number: int) -> list[str]:
    return [
        line for segment in split_segments(text, assignments)
        if segment.kind == NOTE and segment.table == number for line in segment.lines
    ]


def assemble_table(source: TableSource, known_keys: Mapping[int, set[str]]) -> AssembledTable | None:
    """표 하나의 조각을 이어 표 전체와 주석을 만든다. 조각이 없으면 None."""
    raw_runs: list[list[str]] = []
    notes: list[str] = []
    seen_notes: set[str] = set()
    for piece in sorted(source.raw_pieces, key=lambda item: item.chunk_index):
        assignments = assign_runs(piece.text, piece.numbers or (source.number,), known_keys)
        raw_runs += [list(run.lines) for run, number in assignments if number == source.number]
        for line in _notes_after(piece.text, assignments, source.number):
            if _squash(line) not in seen_notes:
                seen_notes.add(_squash(line))
                notes.append(line)
    key = (str(source.document_id), int(source.number))
    odl_pieces = sorted(source.odl_pieces, key=lambda item: item.order)
    if odl_pieces:
        full, repeated = join_odl_pieces(piece.text.split("\n") for piece in odl_pieces)
        header = full[:repeated] if repeated else full[:1]
        return AssembledTable(key, "odl", full, header, notes, odl_pieces)
    if not raw_runs:
        return None
    full = join_raw_pieces(raw_runs)
    return AssembledTable(key, "raw", full, header_lines(full), notes, [])


# ---------------------------------------------------------------- 근거 블록 조립


@dataclass(frozen=True)
class Evidence:
    """검색된 근거 하나. is_odl은 표 원문 블록 근거(글 전체가 표 하나)인지다."""

    chunk_id: str
    text: str
    document_id: str
    numbers: tuple[int, ...]
    is_odl: bool = False
    section_line: str = ""


@dataclass
class PlannedBlock:
    """조립한 블록 하나. plain이면 표가 아닌 블록(머리말과 본문은 main.py가 지금 모양으로 쓴다)."""

    evidence: Evidence
    rank: int
    plain: bool
    segments: list[Segment] = field(default_factory=list)
    tables: list[TableKey] = field(default_factory=list)  # 이 블록에 넣은 표

    def text_lines(self) -> list[str]:
        return [line for segment in self.segments for line in segment.lines]


class TableBlockAssembler:
    """근거를 순위대로 받아 블록을 만든다. 같은 표는 처음 나온(가장 높은 순위) 블록 하나에만 넣는다.

    load_sources(document_id, numbers)는 그 문서의 표 번호별 조각(TableSource)을 돌려준다. 아직 꺼내지 않은 번호가 나올 때만 부른다.
    """

    def __init__(self, load_sources: Callable[[str, Sequence[int]], Mapping[int, TableSource]]):
        self._load_sources = load_sources
        self._sources: dict[str, dict[int, TableSource]] = {}
        self.tables: dict[TableKey, AssembledTable] = {}
        self.blocks: list[PlannedBlock] = []
        self.placed: dict[TableKey, PlannedBlock] = {}
        self.dropped: list[Evidence] = []
        # 표마다 검색된 조각: 원문 청크 (chunk_index, 표 줄), 표 원문 블록 id
        self.retrieved_runs: dict[TableKey, list[tuple[int, list[str]]]] = {}
        self.retrieved_odl: dict[TableKey, set[str]] = {}
        self._rank = 0

    def _tables_for(self, evidence: Evidence) -> dict[int, AssembledTable]:
        document_id = evidence.document_id
        loaded = self._sources.setdefault(document_id, {})
        missing = [number for number in evidence.numbers if number not in loaded]
        if missing:
            for number, source in (self._load_sources(document_id, missing) or {}).items():
                loaded[int(number)] = source
            for number in missing:
                loaded.setdefault(number, TableSource(document_id, number))
            known = document_known_keys(loaded.values())
            for number, source in loaded.items():
                if (document_id, number) not in self.tables:
                    table = assemble_table(source, known)
                    if table is not None:
                        self.tables[(document_id, number)] = table
        return {number: self.tables[(document_id, number)] for number in evidence.numbers
                if (document_id, number) in self.tables}

    def add(self, evidence: Evidence) -> PlannedBlock | None:
        """근거 하나를 블록으로 만든다. 뒤 순위 블록을 뺄 기준에 걸리면 None(블록 수가 늘지 않는다)."""
        self._rank += 1
        tables = self._tables_for(evidence) if evidence.numbers and evidence.document_id else {}
        if not tables:
            block = PlannedBlock(evidence, self._rank, plain=True)
            self.blocks.append(block)
            return block
        document_id = evidence.document_id
        if evidence.is_odl:
            number = next(iter(tables))
            segments = [Segment(TABLE, [line for line in evidence.text.split("\n") if line.strip()], number)]
            self.retrieved_odl.setdefault((document_id, number), set()).add(evidence.chunk_id)
        else:
            known = document_known_keys(self._sources.get(document_id, {}).values())
            assignments = assign_runs(evidence.text, evidence.numbers, known)
            segments = split_segments(evidence.text, assignments)
            chunk_index = _chunk_number(evidence.chunk_id)
            for run, number in assignments:
                self.retrieved_runs.setdefault((document_id, number), []).append((chunk_index, list(run.lines)))
        own = {_squash(line) for line in evidence.text.split("\n")}
        out: list[Segment] = []
        placed_here: list[TableKey] = []
        for segment in segments:
            key = (document_id, segment.table) if segment.table is not None else None
            if segment.kind != TEXT and key not in self.tables:
                _append(out, Segment(TEXT, list(segment.lines)))  # 이을 표가 없으면 원문 그대로 둔다
                continue
            if segment.kind == TABLE:
                if key in self.placed or key in placed_here:
                    continue
                placed_here.append(key)
                out.append(Segment(TABLE, list(self.tables[key].full), segment.table))
                extra = [line for line in self.tables[key].notes if _squash(line) not in own]
                if extra:
                    _append(out, Segment(NOTE, extra, segment.table))
            elif segment.kind == NOTE:
                if key in placed_here:
                    _append(out, Segment(NOTE, list(segment.lines), segment.table))
            else:
                _append(out, Segment(TEXT, list(segment.lines)))
        block = PlannedBlock(evidence, self._rank, plain=False, segments=out, tables=placed_here)
        if not placed_here and self._drop_later_block(block, tables):
            self.dropped.append(evidence)
            return None
        for key in placed_here:
            self.placed[key] = block
        self.blocks.append(block)
        return block

    def _drop_later_block(self, block: PlannedBlock, tables: Mapping[int, AssembledTable]) -> bool:
        """표가 모두 앞 블록에 들어간 뒤 순위 블록을 뺄지(4번 규칙)."""
        remaining = [line for line in block.text_lines() if line.strip()]
        if not remaining:
            return True
        owners = [self.placed[table.key] for table in tables.values() if table.key in self.placed]
        prior = {_squash(line) for owner in owners for line in owner.text_lines()}
        new = [line for line in remaining if _squash(line) not in prior]
        if not new:
            return True
        section = _squash(block.evidence.section_line)
        first = next((line for line in block.evidence.text.split("\n") if line.strip()), "")
        return all(HEADING.match(line) or (section and line == first and _squash(line) == section) for line in new)


def _append(segments: list[Segment], segment: Segment) -> None:
    """같은 이름표가 이어지면(표 자리 제외) 한 조각으로 합친다."""
    if segments and segments[-1].kind == segment.kind and segment.kind != TABLE and segments[-1].table == segment.table:
        segments[-1].lines += segment.lines
    else:
        segments.append(segment)


def _chunk_number(chunk_id: str) -> int:
    tail = str(chunk_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def render_body(block: PlannedBlock, modes: Mapping[TableKey, str],
                reduced_lines: Mapping[TableKey, Mapping[str, list[str]]]) -> str:
    """블록 본문을 이름표와 함께 쓴다. modes[key]가 'full'이 아니면 그 표를 reduced_lines[key][mode](「표 일부:」)로 쓴다."""
    out: list[str] = []
    document_id = block.evidence.document_id
    for segment in block.segments:
        if segment.kind == TABLE:
            key = (document_id, segment.table)
            mode = modes.get(key, "full")
            if mode != "full":
                out += [TABLE_LABEL_PARTIAL, *reduced_lines[key][mode]]
            else:
                out += [TABLE_LABEL_FULL, *segment.lines]
        else:
            out += [LABELS[segment.kind], *segment.lines]
    return "\n".join(out)
