"""테스트 공통: 네트워크 대신 쓰는 가짜 HTTP와 합성 학교 사이트.

저장소가 공개라서 학교 화면을 그대로 넣지 않는다. `fixtures/`의 화면은 실제 화면의 구조(클래스 이름·
중첩)만 따르고 글은 지어낸 것이다.
"""

import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import scope  # noqa: E402
from corpus.ledger import Ledger  # noqa: E402
from corpus.polite import KST, PoliteSession  # noqa: E402
from pdfgen import make_pdf  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 10, 2)
# 금요일 밤 10시: 업무 시간(평일 9~18시) 밖
EVENING = datetime(2026, 10, 2, 22, 0, tzinfo=KST)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status: int, content: bytes, headers: dict | None = None, url: str = ""):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def iter_content(self, size: int):
        for start in range(0, len(self.content), size):
            yield self.content[start:start + size]

    def close(self) -> None:
        pass


class FakeHttp:
    """주소 → 응답. 없는 주소는 404. 요청한 주소와 헤더를 기록한다."""

    def __init__(self, routes: dict | None = None):
        self.routes = routes or {}
        self.requested: list[str] = []
        self.headers: list[dict] = []

    def get(self, url: str, headers=None, timeout=None, stream=False):
        self.requested.append(url)
        self.headers.append(headers or {})
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(404, b"not found", url=url)
        if callable(route):
            route = route()
        status, content, extra = route
        if isinstance(content, str):
            content = content.encode("utf-8")
        return FakeResponse(status, content, extra, url)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_session(http: FakeHttp, now: datetime = EVENING, **kwargs) -> PoliteSession:
    clock = FakeClock()
    session = PoliteSession(http=http, clock=clock.clock, sleep=clock.sleep, now=lambda: now, **kwargs)
    session.fake_clock = clock
    return session


def ok(body, filename: str | None = None):
    headers = {"Content-Disposition": f"attachment; filename={quote(filename)};"} if filename else {}
    return (200, body, headers)


def k2_page(title: str, body: str, updated: str | None = None) -> str:
    """K2Web 안내 페이지 틀(합성)."""
    footer = f"<footer>최종수정일 : {updated}</footer>" if updated else ""
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'><title>{title}</title></head><body>"
        f"<nav>메뉴</nav><article id='_contentBuilder'><div class='_obj _objHtml'><div class='wrapper'>{body}"
        f"</div></div></article>{footer}</body></html>"
    )


def k2_article(seq: str, title: str, written: str, body: str, files: list[tuple[str, str]], board: str = "11",
               site: str = "kr", modified: str | None = None) -> str:
    """K2Web 글 보기 틀(합성). files = [(파일 번호, 파일 이름)]."""
    items = "".join(f"<li><a href='/bbs/{site}/{board}/{seq_}/download.do'>{name}</a></li>" for seq_, name in files)
    return (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'><title>게시판</title></head><body>"
        "<div class='board-view-info'><div class='view-info'>"
        f"<dl class='view-num'><dt>글번호</dt><dd>{seq}</dd></dl><h2 class='view-title'>{title}</h2></div>"
        f"<div class='view-detail'><div class='view-util'><dl class='writer'><dt>작성일</dt><dd>{written}</dd></dl>"
        + (f"<dl class='modify'><dt>수정일</dt><dd>{modified}</dd></dl>" if modified else "")
        + "</div></div></div>"
        f"<div class='view-con'>{body}</div>"
        f"<div class='view-file'><ul>{items}</ul></div></body></html>"
    )


def board_list(rows: list[tuple[str, str, str]], total: int = 1, board: str = "11", site: str = "kr") -> str:
    """K2Web 게시판 목록 틀(합성). rows = [(글 번호, 제목, 작성일)]."""
    trs = "".join(
        f"<tr><td class='td-num'>1</td><td class='td-subject'><a href='/bbs/{site}/{board}/{seq}/artclView.do'>"
        f"<strong>{title}</strong></a></td><td class='td-date'>{written}</td></tr>"
        for seq, title, written in rows
    )
    return (
        f"<html><body><table><tbody>{trs}</tbody></table>"
        f"<div class='_paging'><p class='_pageState'><span class='_curPage'>1</span>"
        f"<span class='_totPage'>{total}</span></p></div></body></html>"
    )


LONG = "학생이 알아야 할 안내 문장이다. 기간과 장소와 방법을 차례로 적는다. " * 4

PDF_GUIDE = make_pdf(["Course change guide. Period: Sep 22 to Sep 26. " * 6])
PDF_ONLY_ATTACH = make_pdf(["Attachment only notice body. " * 12])
PDF_RULE = make_pdf(["Regulation article 1 purpose. Article 2 scope. " * 10])
PDF_ADMISSION = make_pdf(["2027 admission guide. Quota and schedule. " * 10, "Page two of the guide. " * 10])
PDF_FORM = make_pdf(["Eligibility form " * 5])
PDF_EMU = make_pdf(["e-MU admission guide " * 20])
PDF_RESULT = make_pdf(["Admission result 2026 applicants and grades " * 8])
PDF_PHONE = make_pdf(["Contact 010-1234-5678 for the list " * 8])


def school_routes() -> dict:
    """합성 학교 사이트 전체. 테스트마다 필요한 부분만 수집 대상으로 고른다."""
    www, ipsi = scope.WWW, scope.IPSI
    routes = {
        f"{www}/robots.txt": (200, fixture("robots_www.txt"), {}),
        scope.MAIN_SITEMAP: ok(fixture("sitemap_main.html")),
        # 본교 안내 페이지
        f"{www}/kr/157/subview.do": ok(k2_page("총장인사말", LONG, "2026.03.02.")),
        f"{www}/kr/166/subview.do": ok(k2_page("교내전화번호", "부서별 전화번호 표. 학사 담당 032-870-0001. " * 6)),
        f"{www}/kr/104/subview.do": ok(fixture("page_board_widget.html")),
        f"{www}/kr/123/subview.do": ok(fixture("page_calendar.html")),
        f"{www}/kr/232/subview.do": ok(fixture("page_content.html")),
        f"{www}/kr/143/subview.do": ok(fixture("faq.html")),
        f"{www}/mecha/3730/subview.do": ok(k2_page("전공심화과정소개", LONG)),
        # 학과 사이트
        "https://alpha.inhatc.ac.kr/": ok(fixture("dept_landing.html")),
        "https://alpha.inhatc.ac.kr/sitemap/alpha/siteMapView.do": ok(fixture("dept_sitemap.html")),
        "https://alpha.inhatc.ac.kr/alpha/2001/subview.do": ok(k2_page("학과소개", LONG)),
        "https://alpha.inhatc.ac.kr/alpha/2002/subview.do": ok(k2_page("교수진", "교수 연구실과 업무 전화 안내. " * 8)),
        "https://alpha.inhatc.ac.kr/alpha/2010/subview.do": ok(k2_page("교과목개요", LONG)),
        "https://alpha.inhatc.ac.kr/alpha/2012/subview.do": ok(k2_page("로드맵", "<img src='/roadmap.png' alt='로드맵'>")),
        "https://cs.inhatc.ac.kr/": ok(fixture("dept_landing.html").replace("/alpha/", "/cs/")),
        "https://cs.inhatc.ac.kr/sitemap/cs/siteMapView.do": ok(
            "<div class='_stMpWrap'><a class='stMp_Title' href='/cs/1741/subview.do'>학과안내</a>"
            "<a href='/cs/1741/subview.do'>학과소개</a></div>"
        ),
        "https://cs.inhatc.ac.kr/cs/1741/subview.do": ok(k2_page("학과소개", LONG)),
        # 공지(학사)
        f"{www}/bbs/kr/11/artclList.do?page=1": ok(fixture("board_list.html")),
        f"{www}/bbs/kr/11/artclList.do?page=2": ok(fixture("board_list_p2.html")),
        f"{www}/bbs/kr/11/artclList.do?page=3": ok(fixture("board_list_p3.html")),
        f"{www}/bbs/kr/11/1003/artclView.do": ok(fixture("article.html")),
        f"{www}/bbs/kr/11/5001/download.do": ok(PDF_GUIDE, "수강신청 변경 안내문.pdf"),
        f"{www}/bbs/kr/11/5003/download.do": ok(PDF_GUIDE, "수강신청 변경 안내문(사본).pdf"),
        f"{www}/bbs/kr/11/1001/artclView.do": ok(k2_article(
            "1001", "상담 신청 안내", "2025.01.10.", "<p>상담 신청은 담당자 휴대전화 010-9876-5432로 문자를 보낸다.</p>", [])),
        f"{www}/bbs/kr/11/1000/artclView.do": ok(k2_article(
            "1000", "첨부만 있는 공지", "2023.11.01.", "<p>&nbsp;</p>", [("5010", "안내 첨부.pdf")],
            modified="2026.03.03.")),
        f"{www}/bbs/kr/11/5010/download.do": ok(PDF_ONLY_ATTACH, "안내 첨부.pdf"),
        # 학사규정
        f"{www}/bbs/kr/32/artclList.do?bbsOpenWrdSeq=33&page=1": ok(board_list(
            [("2981", "[학사규정] 학력증명발급규정", "2014.06.01.")], board="32")),
        f"{www}/bbs/kr/32/2981/artclView.do": ok(k2_article(
            "2981", "[학사규정]\n   학력증명발급규정", "2014.06.01.", "", [("7001", "학력증명발급규정(20240902).pdf")],
            board="32")),
        f"{www}/bbs/kr/32/7001/download.do": ok(PDF_RULE, "학력증명발급규정(20240902).pdf"),
        # 입학
        f"{ipsi}/ipsi/362/subview.do": ok(fixture("viewer.html")),
        f"{ipsi}/viewer/ipsi/14/fileDown1/fileDownload.do": ok(PDF_ADMISSION, "2027 신입생 모집요강(출력용).pdf"),
        f"{ipsi}/viewer/ipsi/14/fileDown2/fileDownload.do": ok(PDF_FORM, "지원자격 확인서.pdf"),
        f"{ipsi}/ipsi/571/subview.do": ok(fixture("viewer_tmp.html")),
        f"{ipsi}/sites/ipsi/atchmnfl/viewer/19//temp_1760000000000100.tmp": ok(PDF_EMU),
        f"{ipsi}/ipsi/406/subview.do": ok(fixture("ipsi_results.html")),
        f"{ipsi}/sites/ipsi/files/result_2026total.pdf": ok(PDF_RESULT),
    }
    return routes


@pytest.fixture
def small_scope(monkeypatch):
    """수집 범위를 합성 사이트에 맞게 줄인다(학사 공지 하나, FAQ 하나, 입학 전형 둘)."""
    monkeypatch.setattr(scope, "NOTICE_BOARDS", [scope.NOTICE_BOARDS[0]])
    monkeypatch.setattr(scope, "FAQS", [scope.FAQS[0]])
    monkeypatch.setattr(scope, "IPSI_TRACKS", {"362": "수시2차", "571": "e-MU(전문학사)"})
    monkeypatch.setattr(scope, "IPSI_PAGES", ["406"])


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(tmp_path / "ledger.sqlite")
    yield book
    book.close()
