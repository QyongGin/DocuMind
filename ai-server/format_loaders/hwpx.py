"""HWPX(한컴 OWPML, KS X 6101) 문서를 글·표 블록으로 읽는다.

HWPX는 ZIP 안의 XML이다. 본문은 `Contents/sectionN.xml`의 문단(`hp:p`) → 글 조각(`hp:run`) → 글자(`hp:t`)·표(`hp:tbl`)·
그리기 개체로 이어진다. 표 칸(`hp:tc`)마다 칸 주소(`hp:cellAddr`)와 병합 수(`hp:cellSpan`)가 있어 HWP 5.0과 같은
표 격자로 옮긴다. 칸의 '제목 칸' 표시(`header`)는 HWP 5.0처럼 거의 쓰이지 않아(수집 HWP 표 2,315개 중 15개)
머리 판단에 쓰지 않는다. 같은 문서를 HWP와 HWPX로 저장해도 같은 마크다운이 나오게 하기 위해서다.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from .errors import UnsupportedDocumentError
from .table_grid import Block, TableCell, TableGrid

_SECTION_NAME = re.compile(r"Contents/section(\d+)\.xml")
# 머리말·꼬리말은 본문이 아니다
_SKIP_CONTROLS = {"header", "footer"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int(element: ET.Element | None, name: str, default: int = 0) -> int:
    try:
        return int(element.get(name, default)) if element is not None else default
    except (TypeError, ValueError):
        return default


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local(child.tag) == name), None)


def _text_of_t(element: ET.Element) -> str:
    """`hp:t`의 글자. 탭은 빈칸, 줄바꿈은 줄바꿈으로 둔다."""
    parts = [element.text or ""]
    for child in element:
        name = _local(child.tag)
        if name == "tab":
            parts.append(" ")
        elif name == "lineBreak":
            parts.append("\n")
        parts.append(child.tail or "")
    return "".join(parts)


def _draw_texts(element: ET.Element) -> Iterator[ET.Element]:
    """그리기 개체(글상자·묶음 개체) 안의 `hp:drawText`를 찾는다. 다른 문단 구조 안으로는 내려가지 않는다."""
    for child in element:
        name = _local(child.tag)
        if name == "drawText":
            yield child
        elif name not in ("p", "subList", "tbl"):
            yield from _draw_texts(child)


def _sublist_paragraphs(element: ET.Element | None) -> list[Block]:
    blocks: list[Block] = []
    sublist = _child(element, "subList") if element is not None else None
    if sublist is not None:
        for paragraph in sublist:
            if _local(paragraph.tag) == "p":
                blocks.extend(_paragraph(paragraph))
    return blocks


def _table(element: ET.Element) -> list[Block]:
    """`hp:tbl` 하나를 [캡션 글..., 표]로 읽는다."""
    blocks: list[Block] = _sublist_paragraphs(_child(element, "caption"))
    cells: list[TableCell] = []
    for row in element:
        if _local(row.tag) != "tr":
            continue
        for cell in row:
            if _local(cell.tag) != "tc":
                continue
            address = _child(cell, "cellAddr")
            span = _child(cell, "cellSpan")
            cells.append(TableCell(
                row=_int(address, "rowAddr"),
                col=_int(address, "colAddr"),
                row_span=max(_int(span, "rowSpan", 1), 1),
                col_span=max(_int(span, "colSpan", 1), 1),
                blocks=_sublist_paragraphs(cell),
            ))
    blocks.append(TableGrid(_int(element, "rowCnt"), _int(element, "colCnt"), cells, strict=True))
    return blocks


def _paragraph(element: ET.Element) -> list[Block]:
    """문단 하나: 문단 글 다음에 그 문단에 든 표·글상자 내용을 둔다(HWP 5.0 로더와 같은 순서)."""
    texts: list[str] = []
    inner: list[Block] = []
    for run in element:
        if _local(run.tag) != "run":
            continue
        for child in run:
            name = _local(child.tag)
            if name == "t":
                texts.append(_text_of_t(child))
            elif name == "tbl":
                inner.extend(_table(child))
            elif name == "ctrl":
                for control in child:
                    if _local(control.tag) not in _SKIP_CONTROLS:
                        inner.extend(_sublist_paragraphs(control))
            else:
                for draw_text in _draw_texts(child):
                    inner.extend(_sublist_paragraphs(draw_text))
    blocks: list[Block] = []
    text = "".join(texts).strip()
    if text:
        blocks.append(text)
    blocks.extend(inner)
    return blocks


def read_hwpx_blocks(path: str) -> list[Block]:
    """HWPX 파일을 글·표 블록 목록으로 읽는다."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise UnsupportedDocumentError("HWPX 파일을 열 수 없습니다. 확장자와 파일 내용이 맞는지 확인해 주세요.") from error
    with archive:
        sections = sorted(
            (name for name in archive.namelist() if _SECTION_NAME.fullmatch(name)),
            key=lambda name: int(_SECTION_NAME.fullmatch(name).group(1)),
        )
        if not sections:
            raise UnsupportedDocumentError("HWPX 본문(Contents/section*.xml)을 찾을 수 없습니다.")
        blocks: list[Block] = []
        for name in sections:
            data = archive.read(name)
            if b"<!DOCTYPE" in data[:2048]:
                # 외부 개체 선언은 HWPX에 쓰이지 않는다. XML 개체 확장 공격을 막기 위해 거절한다
                raise UnsupportedDocumentError("HWPX 본문에 허용하지 않는 문서 형식 선언이 있습니다.")
            try:
                root = ET.fromstring(data)
            except ET.ParseError as error:
                raise UnsupportedDocumentError("HWPX 본문 XML을 읽을 수 없습니다. 깨진 파일인지 확인해 주세요.") from error
            for paragraph in root:
                if _local(paragraph.tag) == "p":
                    blocks.extend(_paragraph(paragraph))
        return blocks
