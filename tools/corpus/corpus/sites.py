"""학교 누리집(K2Web CMS) 화면에서 메뉴·게시판 목록·FAQ·뷰어 파일을 읽는다. 네트워크는 쓰지 않는다.

구조는 2026-10-01 조사 때 받아 둔 실제 화면으로 확인했다
(`docs/rag/research/학교-문서-원천-조사-20261001.md`). 테스트는 같은 구조의 합성 화면으로 한다.
"""

import re
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit

from .extract import normalize_date, soup

SUBVIEW_RE = re.compile(r"^/(\w+)/(\d+)/subview\.do$")
VIEWER_DOWN_RE = re.compile(r"/viewer/\w+/(\d+)/fileDown(\d+)/fileDownload\.do$")
VIEWER_TMP_RE = re.compile(r"atchmnfl/viewer/(\d+)//?(temp_\d+\.tmp)")


@dataclass(frozen=True)
class MenuLink:
    site: str
    menu_no: str
    url: str
    name: str
    section: str | None


def menu_of(url: str) -> tuple[str, str] | None:
    """`/cs/1741/subview.do` → (`cs`, `1741`)."""
    match = SUBVIEW_RE.match(urlsplit(url).path)
    return (match.group(1), match.group(2)) if match else None


def sitemap_links(html: str, base_url: str) -> list[MenuLink]:
    """사이트맵의 메뉴 페이지 링크를 묶음(`stMp_Title`)과 함께 돌려준다.

    같은 페이지를 가리키는 링크는 하나로 줄이고, 이름은 가장 깊은 메뉴(마지막 링크) 이름을 쓴다.
    다른 호스트로 가는 링크는 `external_hosts`로 따로 읽는다.
    """
    document = soup(html)
    host = urlsplit(base_url).netloc
    found: dict[tuple[str, str], MenuLink] = {}
    for wrap in document.select("div._stMpWrap"):
        title = wrap.select_one(".stMp_Title")
        section = title.get_text(strip=True) if title else None
        for link in wrap.select("a[href]"):
            url = urljoin(base_url, link["href"]).split("#")[0]
            menu = menu_of(url)
            if menu is None or urlsplit(url).netloc != host:
                continue
            first = found.get(menu)
            found[menu] = MenuLink(menu[0], menu[1], url, link.get_text(strip=True), first.section if first else section)
    return list(found.values())


def external_hosts(html: str, base_url: str, section: str) -> list[tuple[str, str]]:
    """사이트맵 한 묶음에서 다른 호스트(학과 사이트)로 가는 링크: (호스트 첫 주소, 링크 이름)."""
    document = soup(html)
    host = urlsplit(base_url).netloc
    hosts: dict[str, str] = {}
    for wrap in document.select("div._stMpWrap"):
        title = wrap.select_one(".stMp_Title")
        if not title or title.get_text(strip=True) != section:
            continue
        for link in wrap.select("a[href]"):
            parts = urlsplit(urljoin(base_url, link["href"]))
            if parts.netloc and parts.netloc != host and parts.netloc.endswith(".inhatc.ac.kr"):
                hosts.setdefault(f"{parts.scheme}://{parts.netloc}/", link.get_text(strip=True))
    return list(hosts.items())


def refresh_target(html: str) -> str | None:
    """학과 사이트 첫 화면의 `<meta http-equiv="refresh" content="0; url=/cs/index.do">`."""
    match = re.search(r"http-equiv=[\"']refresh[\"'][^>]*url=([^\"'>\s]+)", html, re.I)
    return match.group(1) if match else None


def site_id_of(path: str) -> str | None:
    match = re.match(r"^/(\w+)/", path)
    return match.group(1) if match else None


def page_title(html: str) -> str:
    title = soup(html).find("title")
    return re.sub(r"\s+", " ", title.get_text(" ", strip=True)) if title else ""


@dataclass(frozen=True)
class ListRow:
    seq: str
    title: str
    posted_at: str | None
    pinned: bool


def board_rows(html: str) -> list[ListRow]:
    """게시판 목록의 글: 글 번호(seq)는 `artclView.do` 주소에서 읽는다. 고정 공지(`tr.notice`)도 포함."""
    rows = []
    for row in soup(html).select("table tbody tr"):
        link = row.select_one("td.td-subject a[href*='artclView.do']")
        if link is None:
            continue
        match = re.search(r"/(\d+)/artclView\.do", link["href"])
        if match is None:
            continue
        for marker in link.select(".new, .newArtcl, .icon-new"):
            marker.decompose()
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        title = re.sub(r"\s*새글$", "", title)
        date_cell = row.select_one("td.td-date")
        rows.append(ListRow(
            match.group(1),
            title,
            normalize_date(date_cell.get_text(" ", strip=True)) if date_cell else None,
            "notice" in (row.get("class") or []),
        ))
    return rows


def total_pages(html: str) -> int:
    node = soup(html).select_one("._totPage")
    try:
        return int(node.get_text(strip=True)) if node else 1
    except ValueError:
        return 1


@dataclass(frozen=True)
class FaqItem:
    question: str
    answer_html: str


def faq_items(html: str) -> list[FaqItem]:
    """FAQ 게시판(`div.board-faq`)의 질문·답. 글마다 주소가 없어 질문 문장으로 ID를 만든다."""
    items = []
    for entry in soup(html).select("div.board-faq li"):
        question = entry.select_one("a.question")
        answer = entry.select_one("div.answer")
        if question is None or answer is None:
            continue
        for hidden in question.select("span.hidden") + answer.select("span.hidden"):
            hidden.decompose()
        text = re.sub(r"\s+", " ", question.get_text(" ", strip=True))
        if text:
            items.append(FaqItem(text, str(answer)))
    return items


def widget_no(html: str, fnct_id: str) -> str | None:
    match = re.search(rf"fnctId={fnct_id},fnctNo=(\d+)", html)
    return match.group(1) if match else None


@dataclass(frozen=True)
class ViewerFile:
    viewer_no: str
    index: int
    url: str
    label: str


def viewer_files(html: str, base_url: str) -> list[ViewerFile]:
    """모집요강 뷰어 페이지의 내려받기 파일.

    출력용 PDF 링크(`/viewer/ipsi/N/fileDownK/fileDownload.do`)를 쓰고, 링크가 없는 전형은
    화면 속 PDF 뷰어가 불러오는 `/sites/ipsi/atchmnfl/viewer/N//temp_….tmp`를 쓴다.
    """
    files = []
    for link in soup(html).select("a[href*='fileDownload.do']"):
        url = urljoin(base_url, link["href"])
        match = VIEWER_DOWN_RE.search(urlsplit(url).path)
        if match:
            files.append(ViewerFile(match.group(1), int(match.group(2)), url, link.get_text(" ", strip=True)))
    if files:
        return files
    match = VIEWER_TMP_RE.search(html)
    if match is None:
        return []
    site = site_id_of(urlsplit(base_url).path) or "ipsi"
    url = urljoin(base_url, f"/sites/{site}/atchmnfl/viewer/{match.group(1)}//{match.group(2)}")
    return [ViewerFile(match.group(1), 1, url, "모집요강(뷰어 원본)")]


def static_files(html: str, base_url: str) -> list[tuple[str, str]]:
    """본문 영역의 정적 파일 링크(`/sites/…/*.pdf` 등): (주소, 링크 이름)."""
    article = soup(html).find("article", id="_contentBuilder")
    if article is None:
        return []
    found: dict[str, str] = {}
    for link in article.select("a[href]"):
        url = urljoin(base_url, link["href"])
        if re.search(r"/sites/\w+/.+\.(pdf|hwp|hwpx|docx|xlsx|pptx)$", urlsplit(url).path, re.I):
            found.setdefault(url, link.get_text(" ", strip=True))
    return list(found.items())


def disposition_filename(header: str | None) -> str | None:
    """`attachment; filename=%ED%95%99….hwp;` → 파일명. RFC 5987(`filename*=UTF-8''…`)도 읽는다."""
    if not header:
        return None
    match = re.search(r"filename\*=(?:UTF-8|utf-8)''([^;]+)", header)
    if match is None:
        match = re.search(r"filename=\"?([^\";]+)\"?", header)
    if match is None:
        return None
    name = unquote(match.group(1).strip())
    return name.rsplit("/", 1)[-1] or None
