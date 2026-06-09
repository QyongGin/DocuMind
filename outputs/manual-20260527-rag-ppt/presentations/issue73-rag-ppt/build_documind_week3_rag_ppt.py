from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path("/Users/gim-yongjin/Developer/Project/DocuMind")
SOURCE = ROOT / "Assets/발표 PPT/DocuMind_3주차.pptx"
OUTPUT = ROOT / "Assets/발표 PPT/DocuMind_3주차_RAG구조분리_발표본.pptx"
WORKSPACE = ROOT / "outputs/manual-20260527-rag-ppt/presentations/issue73-rag-ppt"
ASSET_DIR = WORKSPACE / "assets"

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

NAVY = "#1A2E4A"
BLUE = "#0066CC"
LIGHT_BLUE = "#EAF3FF"
PALE = "#F6F9FC"
INK = "#172033"
MUTED = "#5A6778"
LINE = "#C9D5E4"
YELLOW = "#FFF1B8"
ORANGE = "#F28C38"
GREEN = "#2E9D62"
RED = "#C94F4F"
PURPLE = "#7266D8"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # AppleSDGothicNeo.ttc renders Korean reliably in local macOS.
    return ImageFont.truetype(FONT, size=size, index=8 if bold else 0)


def draw_bold(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: str, size: int) -> None:
    f = font(size, bold=True)
    x, y = xy
    draw.text((x, y), text, fill=fill, font=f)


def wrap_text(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        current = ""
        for token in raw.split(" "):
            if not current:
                current = token
            elif len(current) + 1 + len(token) <= max_chars:
                current += " " + token
            else:
                lines.append(current)
                current = token
        if current:
            lines.append(current)
    return lines


def text_block(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    width_chars: int,
    size: int,
    fill: str = INK,
    line_gap: int = 8,
    bullet: str | None = None,
) -> int:
    f = font(size)
    line_height = size + line_gap
    for line in wrap_text(text, width_chars):
        if bullet:
            draw.text((x, y), bullet, fill=fill, font=f)
            draw.text((x + 28, y), line, fill=fill, font=f)
        else:
            draw.text((x, y), line, fill=fill, font=f)
        y += line_height
    return y


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str = LINE,
    radius: int = 18,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def label(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, fill: str, color: str = WHITE) -> None:
    rounded(draw, box, fill=fill, outline=fill, radius=12, width=0)
    f = font(24, bold=True)
    x1, y1, x2, y2 = box
    tw = draw.textlength(text, font=f)
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + 9), text, fill=color, font=f)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = BLUE, width: int = 5) -> None:
    draw.line([start, end], fill=color, width=width)
    ex, ey = end
    sx, sy = start
    if abs(ex - sx) >= abs(ey - sy):
        direction = 1 if ex > sx else -1
        points = [(ex, ey), (ex - direction * 18, ey - 10), (ex - direction * 18, ey + 10)]
    else:
        direction = 1 if ey > sy else -1
        points = [(ex, ey), (ex - 10, ey - direction * 18), (ex + 10, ey - direction * 18)]
    draw.polygon(points, fill=color)


def node(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, body: str, fill: str, border: str) -> None:
    rounded(draw, box, fill=fill, outline=border, radius=18, width=3)
    x1, y1, x2, _ = box
    draw_bold(draw, (x1 + 24, y1 + 20), title, border, 26)
    text_block(draw, x1 + 24, y1 + 62, body, 24, 21, fill=INK, line_gap=7)


def make_problem_slide(path: Path) -> None:
    img = Image.new("RGBA", (1920, 934), WHITE)
    draw = ImageDraw.Draw(img)

    draw_bold(draw, (70, 42), "문제 정의", NAVY, 44)
    text_block(
        draw,
        70,
        104,
        "현재 RAG는 문서를 읽은 뒤 만든 chunk 하나를 검색, 답변 근거, 사용자 출처, 표 근거의 부모로 동시에 사용했습니다.",
        58,
        27,
        fill=MUTED,
        line_gap=9,
    )

    # Left: concrete problem statement
    rounded(draw, (70, 190, 820, 792), fill=PALE, outline=LINE, radius=22, width=2)
    label(draw, (104, 224, 322, 274), "현재 chunk의 역할", BLUE)
    y = 318
    items = [
        ("검색용 문장", "embedding/BM25가 찾는 text"),
        ("답변 근거", "LLM prompt에 들어가는 context"),
        ("사용자 출처", "/query sources[].content 미리보기"),
        ("표 근거", "table_fact가 참조하는 부모 text"),
    ]
    for title, body in items:
        rounded(draw, (110, y, 780, y + 74), fill=WHITE, outline="#D5E0ED", radius=14, width=2)
        draw_bold(draw, (138, y + 17), title, NAVY, 25)
        draw.text((330, y + 20), body, fill=MUTED, font=font(23))
        y += 92

    rounded(draw, (110, 694, 780, 748), fill=YELLOW, outline="#E3C85B", radius=14, width=2)
    draw_bold(draw, (138, 708), "결론", NAVY, 25)
    draw.text((230, 710), "한 text가 너무 많은 책임을 맡아 오류 위치를 분리하기 어려웠습니다.", fill=INK, font=font(23))

    # Right: flow diagram
    rounded(draw, (900, 190, 1850, 792), fill=WHITE, outline=LINE, radius=22, width=2)
    label(draw, (934, 224, 1110, 274), "오류가 생기는 흐름", ORANGE)

    node(draw, (960, 330, 1220, 450), "PDF / DOCX", "표, 제목, 목록, 본문이 섞인 입력", LIGHT_BLUE, BLUE)
    node(draw, (1320, 330, 1600, 450), "page_content", "검색과 출처가 같은 text를 공유", "#FFF7E6", ORANGE)
    node(draw, (1140, 570, 1420, 690), "ChromaDB 후보", "검색 결과가 prompt와 source로 재사용", "#F1F7F2", GREEN)
    arrow(draw, (1222, 390), (1316, 390), BLUE)
    arrow(draw, (1460, 452), (1320, 566), ORANGE)

    warning_items = [
        ("scope_loss", "상위 전형/섹션 문맥이 빠짐"),
        ("table_relation_loss", "행·열·범례 관계가 문장 안에서 흐려짐"),
        ("source_contamination", "검색용 가공 text가 출처처럼 보임"),
        ("retrieval miss", "문서에 있는 근거를 못 찾음"),
    ]
    y = 300
    for tag, desc in warning_items:
        rounded(draw, (1500, y, 1810, y + 66), fill="#FFF5F5", outline="#E6B0B0", radius=14, width=2)
        draw_bold(draw, (1520, y + 8), tag, RED, 22)
        draw.text((1520, y + 36), desc, fill=INK, font=font(19))
        y += 86

    rounded(draw, (934, 720, 1810, 760), fill="#EEF4FF", outline="#B9CCE8", radius=12, width=1)
    draw.text(
        (958, 729),
        "#72 기준선: P0 full 5/40. 답만 맞히는 문제가 아니라 근거 구조가 무너지는 문제로 확인.",
        fill=NAVY,
        font=font(22),
    )
    img.save(path)


def make_solution_slide(path: Path) -> None:
    img = Image.new("RGBA", (1920, 934), WHITE)
    draw = ImageDraw.Draw(img)

    draw_bold(draw, (70, 42), "그래서 어떻게 바꿨나", NAVY, 44)
    text_block(
        draw,
        70,
        104,
        "정답을 특정 질문에 맞춰 고친 것이 아니라, RAG 내부에서 '검색용 text'와 '사용자에게 보여줄 원문 출처'를 분리하는 계약을 만들었습니다.",
        60,
        27,
        fill=MUTED,
        line_gap=9,
    )

    rounded(draw, (70, 190, 1160, 802), fill=PALE, outline=LINE, radius=22, width=2)
    label(draw, (104, 224, 332, 274), "새 data contract", BLUE)

    # Contract flow
    contracts = [
        ((120, 336, 360, 438), "ParsedBlock", "파서가 읽은 최소 블록", BLUE),
        ((470, 336, 710, 438), "SourceBlock", "인용 가능한 원문 조각", GREEN),
        ((820, 336, 1080, 438), "SourceCitation", "사용자에게 보여줄 출처", PURPLE),
        ((120, 566, 360, 668), "SectionNode", "문서의 상위 문맥", BLUE),
        ((470, 566, 710, 668), "RetrievalChunk", "검색을 잘하기 위한 text", ORANGE),
        ((820, 566, 1080, 668), "SelectedContext", "LLM에 넣을 최종 근거", GREEN),
    ]
    for box, title, body, color in contracts:
        node(draw, box, title, body, WHITE, color)
    arrow(draw, (362, 386), (466, 386), GREEN)
    arrow(draw, (712, 386), (816, 386), PURPLE)
    arrow(draw, (362, 616), (466, 616), ORANGE)
    arrow(draw, (712, 616), (816, 616), GREEN)
    arrow(draw, (590, 440), (590, 562), "#7B8797")
    draw.text((616, 492), "원문 주소 연결", fill=MUTED, font=font(20))

    rounded(draw, (120, 708, 1080, 762), fill=YELLOW, outline="#E3C85B", radius=14, width=2)
    draw_bold(draw, (148, 722), "핵심", NAVY, 25)
    draw.text((238, 724), "검색용 문장을 바꿔도 사용자 출처는 SourceBlock 원문에서 만들 수 있게 준비했습니다.", fill=INK, font=font(23))

    # Right: actual work and next steps
    rounded(draw, (1220, 190, 1850, 802), fill=WHITE, outline=LINE, radius=22, width=2)
    label(draw, (1254, 224, 1452, 274), "이번 주 작업", ORANGE)

    y = 318
    work_items = [
        ("1", "trace-only preview", "기존 답변·검색 순위는 건드리지 않고 관찰값부터 노출"),
        ("2", "section path quality", "569명, 423만원 같은 제목 오염을 suspect로 표시"),
        ("3", "clean reindex 검증", "새 모집요강 색인에서 suspect 0 확인"),
        ("4", "source_blocks store", "검색 후보가 원문을 다시 찾는 별도 저장소 연결"),
    ]
    for number, title, body in work_items:
        rounded(draw, (1260, y, 1810, y + 78), fill="#F8FBFF", outline="#D7E4F5", radius=14, width=2)
        label(draw, (1280, y + 16, 1328, y + 62), number, BLUE)
        draw_bold(draw, (1350, y + 12), title, NAVY, 23)
        draw.text((1350, y + 43), body, fill=MUTED, font=font(19))
        y += 94

    rounded(draw, (1260, 704, 1810, 760), fill="#EEF8F1", outline="#BFE2CA", radius=14, width=2)
    draw_bold(draw, (1284, 718), "다음", GREEN, 24)
    draw.text((1360, 720), "/query sources를 SourceBlock 기반으로 교체 → typed TableFact", fill=INK, font=font(20))
    img.save(path)


def transparent_png() -> bytes:
    img = Image.new("RGBA", (2, 2), (255, 255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def patch_title(xml: str, title: str) -> str:
    return xml.replace("“Show me”", title)


def resize_first_picture_to_content(xml: str) -> str:
    pic_matches = list(re.finditer(r"<p:pic>.*?</p:pic>", xml, re.S))
    if not pic_matches:
        return xml
    first = pic_matches[0].group(0)
    first = re.sub(r'<a:off x="\d+" y="\d+"', '<a:off x="0" y="699187"', first, count=1)
    first = re.sub(r'<a:ext cx="\d+" cy="\d+"', '<a:ext cx="9144000" cy="4444313"', first, count=1)
    return xml[: pic_matches[0].start()] + first + xml[pic_matches[0].end() :]


def build_deck() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    slide5_img = ASSET_DIR / "slide5_problem.png"
    slide6_img = ASSET_DIR / "slide6_solution.png"
    make_problem_slide(slide5_img)
    make_solution_slide(slide6_img)
    replacements = {
        "ppt/media/image3.png": slide5_img.read_bytes(),
        "ppt/media/image4.png": transparent_png(),
        "ppt/media/image5.png": slide6_img.read_bytes(),
        "ppt/media/image6.png": transparent_png(),
    }

    with zipfile.ZipFile(SOURCE, "r") as zin:
        with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename in replacements:
                    data = replacements[item.filename]
                elif item.filename == "ppt/slides/slide5.xml":
                    xml = data.decode("utf-8")
                    xml = patch_title(xml, "문제 정의")
                    xml = resize_first_picture_to_content(xml)
                    data = xml.encode("utf-8")
                elif item.filename == "ppt/slides/slide6.xml":
                    xml = data.decode("utf-8")
                    xml = patch_title(xml, "해결 방향")
                    xml = resize_first_picture_to_content(xml)
                    data = xml.encode("utf-8")
                zout.writestr(item, data)

    print(OUTPUT)


if __name__ == "__main__":
    build_deck()
