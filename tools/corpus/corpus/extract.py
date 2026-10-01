"""본문 추출, 글자 수·표 수 측정, 대장 '내용 판단' 칸의 자동 제안.

자동 제안은 사람이 확인하기 전의 초안이다(reviewed=0). 답변 로직이 아니라 대장 정리용이다.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from html import escape as html_escape

import pypdfium2
from bs4 import BeautifulSoup

from . import hwp

FORMAT_BY_EXT = {
    "html": "html", "htm": "html", "pdf": "pdf", "hwp": "hwp", "hwpx": "hwpx",
    "docx": "docx", "xlsx": "xlsx", "pptx": "pptx",
    "jpg": "image", "jpeg": "image", "png": "image", "gif": "image", "bmp": "image",
}
DATE_RE = re.compile(r"(20\d\d)[.\-/](\d{1,2})[.\-/](\d{1,2})")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def normalize_date(text: str | None) -> str | None:
    if not text:
        return None
    match = DATE_RE.search(text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def widget_type(node) -> str | None:
    """K2Web 기능 위젯 종류(`bbs`·`viewer`·`qna`·`schdulmanage`·`sbjMng` …)."""
    info = node.select_one("div.widgetInfo")
    match = re.search(r"fnctId=(\w+)", info.get_text()) if info else None
    return match.group(1) if match else None


@dataclass
class PageBody:
    html: str | None
    widgets: list[str]
    updated_at: str | None


def page_body(page_html: str) -> PageBody:
    """안내 페이지에서 본문 영역(`article#_contentBuilder`)만 꺼낸다. 메뉴·바닥글은 버린다.

    게시판 위젯(`bbs`)은 목록 표뿐이라 뺀다(게시판 글은 따로 수집한다). 학사일정(`schdulmanage`)·
    교과목개요(`sbjMng`)·종합민원 부서표(`qna`)는 위젯 안에 본문이 있어 남긴다.
    입력칸(`input`)은 지우지 않는다: html.parser가 그 뒤 내용을 입력칸 안에 넣는 경우가 있다.
    """
    document = soup(page_html)
    article = document.find("article", id="_contentBuilder")
    updated = re.search(r"최종수정일\s*:?\s*(20\d\d\.\d\d\.\d\d)", document.get_text(" "))
    updated_at = normalize_date(updated.group(1)) if updated else None
    if article is None:
        return PageBody(None, [], updated_at)
    widgets = []
    for widget in article.select("div._objWidget"):
        kind = widget_type(widget)
        if kind:
            widgets.append(kind)
        if kind == "bbs":
            widget.decompose()
    for hidden in article.select("div.widgetInfo, script, style, noscript"):
        hidden.decompose()
    return PageBody(str(article), widgets, updated_at)


@dataclass
class Attachment:
    file_seq: str
    name: str
    href: str


@dataclass
class PostParts:
    title: str
    posted_at: str | None
    body_html: str
    body_chars: int
    attachments: list[Attachment] = field(default_factory=list)
    modified_at: str | None = None


def post_parts(article_html: str) -> PostParts:
    """게시판 글에서 제목·작성일·본문(view-con)·첨부 목록을 꺼낸다. 게시판 틀은 버린다."""
    document = soup(article_html)
    title_node = document.select_one(".view-title")
    title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)) if title_node else ""
    title = re.sub(r"^\[([^\]]+)\]\s*", r"[\1] ", title)
    # 작성일은 `.view-util dl.writer`(실제 화면 2026-10 기준)에 있다
    header = document.select_one(".board-view-info") or document
    header_text = header.get_text(" ")
    written = re.search(r"작성일\s*(20\d\d\.\d\d?\.\d\d?)", header_text)
    posted = normalize_date(written.group(1)) if written else None
    modified = re.search(r"수정일\s*(20\d\d\.\d\d?\.\d\d?)", header_text)
    body = document.select_one(".view-con")
    for hidden in (body.select("script, style") if body is not None else []):
        hidden.decompose()
    body_html = f"<h1>{html_escape(title)}</h1>\n{body if body is not None else ''}"
    attachments = []
    for link in document.select(".view-file a[href*='download.do']"):
        match = re.search(r"/(\d+)/download\.do", link.get("href", ""))
        name = link.get_text(" ", strip=True)
        if match and name:
            attachments.append(Attachment(match.group(1), name, link["href"]))
    body_chars = len(re.sub(r"\s+", "", body.get_text())) if body is not None else 0
    return PostParts(title, posted, body_html, body_chars, attachments,
                     normalize_date(modified.group(1)) if modified else None)


def faq_document(question: str, answer_html: str) -> str:
    """FAQ 한 건 = 질문 제목 + 답 본문. 문답 하나가 검색 단위가 되게 따로 저장한다."""
    return f"<h1>{html_escape(question)}</h1>\n{answer_html}"


def html_metrics(body_html: str) -> tuple[int, int, int, str]:
    """(글자 수, 표 수, 그림 수, 글) — 공백을 하나로 줄인 글 기준."""
    document = soup(body_html)
    text = re.sub(r"\s+", " ", document.get_text(" ")).strip()
    return len(text), len(document.find_all("table")), len(document.find_all("img")), text


def pdf_metrics(path: str) -> tuple[int, int, str]:
    """(글자 수, 쪽 수, 글). pypdfium2(BSD-3·Apache-2.0)로 읽는다."""
    document = pypdfium2.PdfDocument(path)
    try:
        texts = []
        for page in document:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        text = re.sub(r"\s+", " ", " ".join(texts)).strip()
        return len(text), len(document), text
    finally:
        document.close()


def hwp_metrics(path: str) -> tuple[int, int, str, str | None]:
    """(글자 수, 표 수, 글, 비고). 암호·배포용 문서는 글을 읽지 못한다고 비고에 남긴다."""
    result = hwp.extract(path)
    note = None
    if result.encrypted or result.distribution:
        note = "암호 또는 배포용 HWP라 글자를 읽지 못함"
    text = re.sub(r"\s+", " ", result.text).strip()
    return len(text), result.tables, text, note


def image_heavy_pdf(chars: int, pages: int) -> bool:
    return pages > 0 and chars / pages < 200


def image_heavy_html(chars: int, images: int) -> bool:
    return chars < 300 and images > 0


def file_format(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return FORMAT_BY_EXT.get(ext, "etc")


def file_ext(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
    return re.sub(r"[^a-z0-9]", "", ext) or "bin"


# ---- 자동 제안 (사람 확인 전) ----

def semester_end(posted_at: str | None) -> str | None:
    """공지의 유효 기간 기본값: 게시 학기 끝. 1학기(3~8월) → 8월 31일, 2학기(9~2월) → 다음 해 2월 말."""
    if not posted_at:
        return None
    year, month = int(posted_at[:4]), int(posted_at[5:7])
    if 3 <= month <= 8:
        return f"{year}-08-31"
    end_year = year + 1 if month >= 9 else year
    leap = end_year % 4 == 0 and (end_year % 100 != 0 or end_year % 400 == 0)
    return f"{end_year}-02-{29 if leap else 28}"


def suggest_year(title: str, posted_at: str | None) -> int | None:
    """학년도 제안: 제목의 `2027학년도`·`2026년` → 제목의 다른 네 자리 연도(`2026-2학기`) → 게시 연도."""
    match = re.search(r"(20\d\d)\s*(?:학년도|년)", title) or re.search(r"(?<!\d)(20\d\d)(?!\d)", title)
    if match:
        return int(match.group(1))
    return int(posted_at[:4]) if posted_at else None


def revised_from_name(name: str) -> str | None:
    """규정 첨부 파일명의 개정일(예: `학력증명발급규정(20240902).pdf`)."""
    match = re.search(r"\((20\d\d)(\d\d)(\d\d)\)", name)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else None


def group_name(title: str) -> str:
    """문서 묶음 대표 이름: 연도·날짜·재공지 표시·괄호 말머리·확장자·공백을 뺀다."""
    name = re.sub(r"\.(pdf|hwp|hwpx|docx|xlsx|pptx|html?)$", "", title, flags=re.I)
    name = re.sub(r"\((?:재공지|수정|추가|연장|정정)[^)]*\)|\[(?:재공지|수정|추가|연장|정정)[^\]]*\]", "", name)
    name = re.sub(r"\(20\d{6}\)", "", name)
    name = re.sub(r"20\d\d\s*(?:학년도|년도|년)?", "", name)
    name = re.sub(r"\d{1,2}\s*(?:학기|월)", "", name)
    name = re.sub(r"^\s*\[[^\]]*\]\s*", "", name)
    return re.sub(r"\s+", "", name).strip("-_·.") or re.sub(r"\s+", "", title)


CAMPUS = "학과·캠퍼스 생활"
# 위에서부터 먼저 맞는 주제. 시설·계정 낱말을 학사 낱말(강의 등)보다 먼저 본다
TOPIC_KEYWORDS = [
    ("장학·등록금", re.compile(r"장학|등록금|학자금")),
    (CAMPUS, re.compile(r"강의실|에어컨|냉방|난방|주차|셔틀|통학|식당|기숙사|생활관|도서관|와이파이|WiFi|계정|로그인|홈페이지|앱|포털")),
    ("입시", re.compile(r"입학|모집|전형|수시|정시|신입생|편입")),
    ("학사", re.compile(r"수강|성적|휴학|복학|졸업|학점|학적|전과|출석|출결|공결|수업|강의|시험|학사|교과|교양|전공|"
                       r"계절학기|이러닝|학위|규정|학칙")),
    (CAMPUS, re.compile(r"동아리|버스|예비군|병무|취업|상담|시설|보건|학생증|공모전|경진대회|캠프|현장실습|민원|증명서|분실")),
]


def suggest_topic(title: str, fixed: str | None = None, section_topic: str | None = None) -> str:
    """주제 제안: 입학 사이트는 입시로 고정, 그 밖은 제목의 장학·등록금 낱말이 먼저, 다음 게시판·메뉴 묶음, 다음 낱말."""
    if fixed == "입시":
        return fixed
    if TOPIC_KEYWORDS[0][1].search(title):
        return TOPIC_KEYWORDS[0][0]
    if fixed:
        return fixed
    if section_topic:
        return section_topic
    for topic, pattern in TOPIC_KEYWORDS[1:]:
        if pattern.search(title):
            return topic
    return "기타"


def sniff_format(name: str, head: bytes) -> str:
    """파일명 확장자로 형식을 정하고, 확장자가 없거나 낯설면 앞부분 바이트로 본다."""
    found = file_format(name)
    if found != "etc":
        return found
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    return "etc"


def index_status(pii_status: str, valid_until: str | None, today: date) -> str:
    """서비스 색인 여부 규칙: 개인정보 보류·제외 → 제외, 유효 기간 지남 → 보관, 그 밖 → 색인."""
    if pii_status in ("보류", "제외"):
        return "제외"
    if valid_until and valid_until != "until_replaced" and valid_until < today.isoformat():
        return "보관"
    return "색인"
