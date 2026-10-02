"""HWP 5.0 글자 추출 (대장의 글자 수·표 수 계산용).

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.

HWP 5.0은 OLE 복합 문서이고, 본문은 `BodyText/SectionN` 스트림에 레코드로 들어 있다
(한컴 공개 문서 "HWP 5.0 파일 구조"). 글자는 `HWPTAG_PARA_TEXT` 레코드에 UTF-16LE로 있다.
표 구조를 살린 변환은 AI 서버 로더(`ai-server/format_loaders/hwp5.py`)가 한다. 여기서는 글자와 표 개수만 센다.
olefile은 BSD 라이선스다.
"""

import struct
import zlib
from dataclasses import dataclass

import olefile

HWPTAG_BEGIN = 0x10
HWPTAG_PARA_TEXT = HWPTAG_BEGIN + 51
HWPTAG_CTRL_HEADER = HWPTAG_BEGIN + 55
# 1글자짜리 제어 문자. 나머지 0~31 제어 문자는 8글자(16바이트)를 차지한다
CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


@dataclass
class HwpText:
    text: str
    tables: int
    compressed: bool
    encrypted: bool
    distribution: bool


def records(data: bytes):
    """(태그 ID, 레코드 본문)을 차례로 돌려준다."""
    offset = 0
    while offset + 4 <= len(data):
        (header,) = struct.unpack_from("<I", data, offset)
        offset += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, offset)
            offset += 4
        yield tag, data[offset:offset + size]
        offset += size


def para_text(buf: bytes) -> str:
    out: list[str] = []
    index, length = 0, len(buf) // 2
    while index < length:
        (code,) = struct.unpack_from("<H", buf, index * 2)
        if code < 32:
            if code in (10, 13):
                out.append("\n")
            elif code == 9:
                out.append("\t")
            index += 1 if code in CHAR_CONTROLS else 8
            continue
        if 0xD800 <= code <= 0xDBFF and index + 1 < length:
            # UTF-16 대리 문자 쌍(이모지·확장 한자 등)은 두 칸을 합쳐 한 글자로
            (low,) = struct.unpack_from("<H", buf, (index + 1) * 2)
            if 0xDC00 <= low <= 0xDFFF:
                out.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                index += 2
                continue
        out.append(chr(code))
        index += 1
    return "".join(out)


def extract(path: str) -> HwpText:
    ole = olefile.OleFileIO(path)
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        compressed, encrypted, distribution = bool(flags & 1), bool(flags & 2), bool(flags & 4)
        if encrypted or distribution:
            # 암호·배포용 문서는 본문이 따로 암호화되어 여기서 읽지 않는다
            return HwpText("", 0, compressed, encrypted, distribution)
        sections = sorted(
            (entry for entry in ole.listdir() if entry[0] == "BodyText"),
            key=lambda entry: int(entry[1].replace("Section", "") or 0),
        )
        texts: list[str] = []
        tables = 0
        for entry in sections:
            raw = ole.openstream(entry).read()
            data = zlib.decompress(raw, -15) if compressed else raw
            for tag, body in records(data):
                if tag == HWPTAG_PARA_TEXT:
                    texts.append(para_text(body))
                elif tag == HWPTAG_CTRL_HEADER and body[:4][::-1] == b"tbl ":
                    tables += 1
        return HwpText("\n".join(texts), tables, compressed, encrypted, distribution)
    finally:
        ole.close()
