"""수집 범위 (총괄계획 §4.6 안건 2, 2026-10-01 사용자 결정).

핵심 안내(본교 안내 페이지, 학사규정, 모집요강·입시결과, FAQ·입시 FAQ, 학과 사이트 안내 페이지,
장학금·취업 현황) + 본교·입학 공지 최근 3년(본문과 첨부). 학과 공지·학과 취업공고는 넣지 않는다.
주소와 번호는 2026-10-01 조사 때 확인한 값이다.
"""

import re
from dataclasses import dataclass

WWW = "https://www.inhatc.ac.kr"
IPSI = "https://ipsi.inhatc.ac.kr"
MAIN_SITEMAP = f"{WWW}/sitemap/kr/siteMapView.do"

# 공지는 최근 3년 치만 받는다
NOTICE_YEARS = 3
# 게시판 위젯을 뺀 본문이 이보다 짧고 그림도 없으면 안내 페이지로 보지 않는다(기능·목록 페이지)
PAGE_MIN_CHARS = 100
# 글 본문(view-con)이 이보다 짧으면 본문 행을 만들지 않는다(첨부만 있는 글)
POST_MIN_CHARS = 20
# 첨부 하나의 상한. 넘으면 받지 않고 실패 목록에 남긴다
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class Board:
    host: str
    site: str
    board_no: str
    label: str
    topic: str | None = None
    query: str = ""

    def list_url(self, page: int) -> str:
        extra = f"{self.query}&" if self.query else ""
        return f"{self.host}/bbs/{self.site}/{self.board_no}/artclList.do?{extra}page={page}"

    def view_url(self, seq: str) -> str:
        return f"{self.host}/bbs/{self.site}/{self.board_no}/{seq}/artclView.do"


# 본교 공지 5종(통합 공지의 구성) + 입학 공지
NOTICE_BOARDS = [
    Board(WWW, "kr", "11", "학사(11)", "학사"),
    Board(WWW, "kr", "17", "장학(17)", "장학·등록금"),
    Board(WWW, "kr", "18", "행사(18)", "학과·캠퍼스 생활"),
    Board(WWW, "kr", "19", "채용(19)", "기타"),
    Board(WWW, "kr", "33", "일반(33)", None),
    Board(IPSI, "ipsi", "9", "입학 공지(9)", "입시"),
]

# 정보목록 게시판의 '학사규정' 분류(bbsOpenWrdSeq=33)만. 예산·결산 등 다른 분류는 넣지 않는다
REGULATIONS = Board(WWW, "kr", "32", "정보목록(32)·학사규정", "학사", query="bbsOpenWrdSeq=33")


@dataclass(frozen=True)
class Faq:
    host: str
    site: str
    board_no: str
    menu_url: str
    topic: str | None
    group: str

    def list_url(self, page: int) -> str:
        return f"{self.host}/bbs/{self.site}/{self.board_no}/artclList.do?page={page}"


FAQS = [
    Faq(WWW, "kr", "579", f"{WWW}/kr/143/subview.do", None, "FAQ:학교"),
    Faq(IPSI, "ipsi", "38", f"{IPSI}/ipsi/403/subview.do", "입시", "FAQ:입시"),
]

# 입학 사이트는 사이트맵에 지원자 기능(원서접수·합격자 조회·등록금 환불 신청 등)이 섞여 있어 목록을 정해 둔다
IPSI_TRACKS = {
    "356": "수시1차", "362": "수시2차", "368": "정시", "414": "재외국민", "567": "산업체위탁",
    "571": "e-MU(전문학사)", "573": "e-MU(전공심화)", "575": "전공심화", "394": "편입학", "416": "외국인",
}
IPSI_PAGES = ["406", "420", "579", "408", "409"]  # 전년도 입시결과, 면접 안내, 학과소개, 입시 멘토링, 성공면접

# 본교 사이트맵에서 내용이 아닌 메뉴
WWW_SKIP_MENU = re.compile(r"사이트맵|로그인")
# 학과 사이트: 사이트맵에서 이 묶음은 넣지 않는다(학과 공지·갤러리·신청 기능·로그인)
DEPT_SKIP_SECTIONS = {"커뮤니티", "수강/민원신청", "이용안내"}
DEPT_SKIP_MENU = re.compile(r"공지|취업공고|갤러리|자료실|신청|예약|로그인|사이트맵")
# 사람 정보가 중심인 페이지(교수진·직원 연락처, 학생회, 임원): 받되 개인정보 '보류'로 두고 사용자가 정한다.
# 학교가 업무용으로 공개한 정보지만 챗봇 답에 개인 연락처를 쓸지는 아직 정하지 않았다(조사 보고서 §4)
PEOPLE_MENU = re.compile(r"교수진|교직원|행정직원|조교|학생회|임원현황|교내전화번호")
PEOPLE_REASON = "사람 정보 페이지(교수진·직원 연락처·학생회·임원): 사용 여부 결정 대기"
# 학과 이름이 바뀐 곳: 학과 사이트 기준 새 이름, 옛 이름은 별칭
DEPT_RENAMES = {"cs": "AI소프트웨어학과"}

SECTION_TOPICS = {"입학안내": "입시", "학사안내": "학사", "대학생활": "학과·캠퍼스 생활", "학과안내": "학과·캠퍼스 생활"}
