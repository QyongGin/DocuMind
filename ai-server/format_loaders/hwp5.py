"""HWP 5.0 문서를 글·표 블록으로 읽는다.

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

HWP 5.0은 OLE 복합 문서다. 본문은 `BodyText/SectionN` 스트림에 레코드로 들어 있고(압축 표시가 있으면 deflate),
레코드마다 (태그, 수준, 크기) 머리 뒤에 내용이 온다. 문단(PARA_HEADER) 바로 아래 수준에 글자(PARA_TEXT)와
컨트롤(CTRL_HEADER)이 오고, 표 컨트롤('tbl ') 아래에 표(TABLE)와 칸(LIST_HEADER)이, 칸 아래에 다시 문단이 온다.

공개 문서와 다르게 실측한 것(수집한 HWP 467개, 자바 hwplib과 표 2,276개 구조 일치로 확인):
- 칸 머리(LIST_HEADER)의 문단 수는 4바이트라, 속성 4바이트 뒤 8바이트 자리부터 열·행 주소와 병합 수가 온다.
- 표 컨트롤과 TABLE 레코드 사이에 컨트롤 데이터(태그 87)나 캡션 문단이 낄 수 있다.

파일을 읽기만 하고 고치지 않는다. olefile은 BSD 라이선스다.
"""

from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass

import olefile

from .errors import UnsupportedDocumentError
from .table_grid import Block, TableCell, TableGrid

logger = logging.getLogger(__name__)

HWPTAG_BEGIN = 0x10
PARA_HEADER = HWPTAG_BEGIN + 50
PARA_TEXT = HWPTAG_BEGIN + 51
CTRL_HEADER = HWPTAG_BEGIN + 55
LIST_HEADER = HWPTAG_BEGIN + 56
TABLE = HWPTAG_BEGIN + 61

# 1글자(2바이트)짜리 제어 문자. 나머지 0~31 제어 문자는 8글자(16바이트)를 차지한다(공개 문서 "제어 문자")
_CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}
# 본문이 아닌 컨트롤: 머리말·꼬리말
_SKIP_CONTROLS = {b"head", b"foot"}
_SIGNATURE = b"HWP Document File"


@dataclass(frozen=True)
class Record:
    tag: int
    level: int
    data: bytes


def read_header_flags(header: bytes) -> tuple[bool, bool, bool]:
    """FileHeader 스트림에서 (압축, 암호, 배포용) 표시를 읽는다."""
    if not header.startswith(_SIGNATURE) or len(header) < 40:
        raise UnsupportedDocumentError("HWP 파일 머리를 읽을 수 없습니다. 깨진 파일인지 확인해 주세요.")
    (flags,) = struct.unpack_from("<I", header, 36)
    return bool(flags & 1), bool(flags & 2), bool(flags & 4)


def iter_records(data: bytes) -> list[Record]:
    """섹션 스트림을 레코드 목록으로 나눈다."""
    records: list[Record] = []
    offset = 0
    while offset + 4 <= len(data):
        (header,) = struct.unpack_from("<I", data, offset)
        offset += 4
        tag, level, size = header & 0x3FF, (header >> 10) & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, offset)
            offset += 4
        records.append(Record(tag, level, data[offset:offset + size]))
        offset += size
    return records


def para_text(buf: bytes) -> str:
    """PARA_TEXT(UTF-16LE)에서 글자만 꺼낸다. 확장 제어 문자 자리와 사용자 정의 영역 기호는 버린다.

    묶음 빈칸(30)·고정폭 빈칸(31)은 빈칸으로, 하이픈(24)은 '-'로 둔다. 버리면 단어가 붙는다
    (수집 HWP 67개 파일에 고정폭 빈칸 869개).
    """
    out: list[str] = []
    index, length = 0, len(buf) // 2
    while index < length:
        (code,) = struct.unpack_from("<H", buf, index * 2)
        if code < 32:
            if code in (10, 13):
                out.append("\n")
            elif code in (9, 30, 31):
                out.append(" ")
            elif code == 24:
                out.append("-")
            index += 1 if code in _CHAR_CONTROLS else 8
            continue
        if 0xD800 <= code <= 0xDBFF and index + 1 < length:
            (low,) = struct.unpack_from("<H", buf, (index + 1) * 2)
            if 0xDC00 <= low <= 0xDFFF:
                out.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                index += 2
                continue
        if not 0xE000 <= code <= 0xF8FF:
            # 사용자 정의 영역(한컴 전용 기호)은 한글 밖에서 뜻이 없어 버린다
            out.append(chr(code))
        index += 1
    return "".join(out).strip()


class _SectionParser:
    """레코드 수준을 따라 문단·표·컨트롤을 블록으로 모은다."""

    def __init__(self, records: list[Record]):
        self.records = records

    def paragraphs(self, index: int, level: int, limit: int | None = None) -> tuple[list[Block], int]:
        """level 수준의 문단들을 읽는다. 문단 글 다음에 그 문단에 든 표·글상자 내용을 둔다."""
        blocks: list[Block] = []
        count = 0
        records = self.records
        while index < len(records) and records[index].tag == PARA_HEADER and records[index].level == level:
            if limit is not None and count >= limit:
                break
            index += 1
            count += 1
            text = ""
            inner: list[Block] = []
            while index < len(records) and records[index].level > level:
                record = records[index]
                if record.tag == PARA_TEXT and record.level == level + 1:
                    text = para_text(record.data)
                    index += 1
                elif record.tag == CTRL_HEADER and record.level == level + 1:
                    control = record.data[:4][::-1]
                    if control == b"tbl ":
                        table_blocks, index = self.table(index, record.level)
                        inner.extend(table_blocks)
                    else:
                        control_blocks, index = self.control(index, record.level, control)
                        inner.extend(control_blocks)
                else:
                    index += 1
            if text:
                blocks.append(text)
            blocks.extend(inner)
        return blocks, index

    def control(self, index: int, level: int, control: bytes) -> tuple[list[Block], int]:
        """표가 아닌 컨트롤(글상자·각주 등) 안의 문단을 꺼낸다. 머리말·꼬리말은 버린다."""
        index += 1
        blocks: list[Block] = []
        while index < len(self.records) and self.records[index].level > level:
            record = self.records[index]
            if record.tag == PARA_HEADER:
                inner, index = self.paragraphs(index, record.level)
                if control not in _SKIP_CONTROLS:
                    blocks.extend(inner)
            else:
                index += 1
        return blocks, index

    def table(self, index: int, level: int) -> tuple[list[Block], int]:
        """표 컨트롤 하나를 읽어 [캡션 글..., 표]로 돌려준다."""
        index += 1
        records = self.records
        blocks: list[Block] = []
        # TABLE 레코드 앞에 컨트롤 데이터나 캡션 문단이 올 수 있다
        while index < len(records) and records[index].level > level and records[index].tag != TABLE:
            record = records[index]
            if record.tag == PARA_HEADER:
                caption, index = self.paragraphs(index, record.level)
                blocks.extend(caption)
            else:
                index += 1
        rows = cols = 0
        if index < len(records) and records[index].tag == TABLE and records[index].level > level:
            rows, cols = struct.unpack_from("<HH", records[index].data, 4)
            index += 1
        cells: list[TableCell] = []
        while index < len(records) and records[index].level > level:
            record = records[index]
            if record.tag == LIST_HEADER and record.level == level + 1:
                (paragraph_count,) = struct.unpack_from("<i", record.data, 0)
                col, row, col_span, row_span = struct.unpack_from("<4H", record.data, 8)
                cell_blocks, index = self.paragraphs(index + 1, level + 1, limit=max(paragraph_count, 1))
                cells.append(TableCell(row, col, max(row_span, 1), max(col_span, 1), cell_blocks))
            else:
                index += 1
        blocks.append(TableGrid(rows, cols, cells, strict=True))
        return blocks, index


def parse_section(data: bytes) -> list[Block]:
    """압축을 푼 섹션 스트림을 글·표 블록으로 읽는다."""
    records = iter_records(data)
    parser = _SectionParser(records)
    blocks, index = parser.paragraphs(0, 0)
    while index < len(records):
        # 맨 위 수준에 문단이 아닌 레코드가 오면(수집 HWP에는 없었다) 건너뛰고 다음 문단부터 다시 읽는다
        index += 1
        while index < len(records) and not (records[index].tag == PARA_HEADER and records[index].level == 0):
            index += 1
        more, index = parser.paragraphs(index, 0)
        blocks.extend(more)
    return blocks


def _section_text_only(data: bytes) -> list[Block]:
    """구조 해석이 실패한 섹션에서 글자만 꺼낸다(수집기와 같은 방식)."""
    texts: list[Block] = []
    for record in iter_records(data):
        if record.tag == PARA_TEXT:
            text = para_text(record.data)
            if text:
                texts.append(text)
    return texts


def read_hwp5_blocks(path: str) -> list[Block]:
    """HWP 5.0 파일을 글·표 블록 목록으로 읽는다.

    암호·배포용 문서와 HWP 3.0은 UnsupportedDocumentError로 거절한다. 섹션의 표 구조 해석이 실패하면
    그 섹션은 글만 꺼내고 경고를 남긴다(업로드는 계속된다).
    """
    if not olefile.isOleFile(path):
        with open(path, "rb") as file:
            head = file.read(32)
        if head.startswith(b"HWP Document File V3"):
            raise UnsupportedDocumentError(
                "HWP 3.0 문서는 읽을 수 없습니다. 한글에서 HWP(5.0 이상) 또는 PDF로 다시 저장해 올려 주세요."
            )
        raise UnsupportedDocumentError("HWP 5.0 파일이 아닙니다. 확장자와 파일 내용이 맞는지 확인해 주세요.")

    try:
        ole = olefile.OleFileIO(path)
    except OSError as error:
        raise UnsupportedDocumentError("HWP 파일을 열 수 없습니다. 깨진 파일인지 확인해 주세요.") from error
    with ole:
        if not ole.exists("FileHeader"):
            raise UnsupportedDocumentError("HWP 파일 머리를 찾을 수 없습니다. 깨진 파일인지 확인해 주세요.")
        compressed, encrypted, distribution = read_header_flags(ole.openstream("FileHeader").read())
        if encrypted or distribution:
            raise UnsupportedDocumentError(
                "암호가 걸렸거나 배포용으로 저장된 HWP 문서는 읽을 수 없습니다. "
                "한글에서 일반 문서나 PDF로 다시 저장해 올려 주세요."
            )
        sections = sorted(
            (entry for entry in ole.listdir() if len(entry) == 2 and entry[0] == "BodyText"),
            key=lambda entry: int(entry[1].replace("Section", "") or 0),
        )
        blocks: list[Block] = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            try:
                data = zlib.decompress(raw, -15) if compressed else raw
            except zlib.error as error:
                raise UnsupportedDocumentError("HWP 본문 압축을 풀 수 없습니다. 깨진 파일인지 확인해 주세요.") from error
            try:
                blocks.extend(parse_section(data))
            except (struct.error, IndexError, ValueError, RecursionError):
                logger.warning("[hwp5] 표 구조 해석에 실패해 글만 꺼냅니다. path=%s section=%s", path, "/".join(entry), exc_info=True)
                blocks.extend(_section_text_only(data))
        return blocks
