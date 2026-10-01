"""화면 해석: 합성 고정 화면(fixtures/)으로, 네트워크 없이."""

from conftest import fixture

from corpus import extract, sites

BASE = "https://www.inhatc.ac.kr/sitemap/kr/siteMapView.do"


def test_sitemap_links_dedupes_and_keeps_section():
    links = {(link.site, link.menu_no): link for link in sites.sitemap_links(fixture("sitemap_main.html"), BASE)}
    # 같은 페이지(/kr/157) 링크 셋은 하나로, 이름은 가장 깊은 메뉴
    assert links[("kr", "157")].name == "총장인사말"
    assert links[("kr", "157")].section == "대학안내"
    assert links[("kr", "123")].name == "학사일정"
    # 주소의 #조각은 떼고 같은 페이지로 본다
    assert links[("kr", "232")].url == "https://www.inhatc.ac.kr/kr/232/subview.do"
    # 같은 호스트의 다른 사이트(학과 하위·입학)도 돌려주고, 다른 호스트·로그인은 뺀다
    assert ("mecha", "3730") in links and ("ipsi", "356") in links
    assert all("inhatc.ac.kr" in link.url and "ssoLogin" not in link.url for link in links.values())


def test_external_hosts_reads_department_sites():
    hosts = sites.external_hosts(fixture("sitemap_main.html"), BASE, "학과안내")
    assert hosts == [("https://alpha.inhatc.ac.kr/", "알파공학과"), ("https://cs.inhatc.ac.kr/", "컴퓨터정보공학과")]


def test_refresh_target_and_site_id():
    assert sites.refresh_target(fixture("dept_landing.html")) == "/alpha/index.do"
    assert sites.site_id_of("/alpha/index.do") == "alpha"
    assert sites.page_title(fixture("page_content.html")) == "휴학ㆍ복학"


def test_board_rows_reads_pinned_and_strips_new_marker():
    rows = sites.board_rows(fixture("board_list.html"))
    assert [row.seq for row in rows] == ["900", "1003", "1002", "1001"]
    assert rows[0].pinned and not rows[1].pinned
    assert rows[1].title == "2026-2학기 수강신청 변경 안내"
    assert rows[1].posted_at == "2026-09-20"
    assert sites.total_pages(fixture("board_list.html")) == 5


def test_post_parts_title_date_body_and_attachments():
    parts = extract.post_parts(fixture("article.html"))
    assert parts.title == "2026-2학기 수강신청 변경 안내"
    assert parts.posted_at == "2026-09-20"  # 게시일은 작성일
    assert parts.modified_at == "2026-09-21"
    assert "수강신청 변경 기간" in parts.body_html
    assert "이전 글" not in parts.body_html and "<script" not in parts.body_html
    assert [(a.file_seq, a.name) for a in parts.attachments] == [
        ("5001", "수강신청 변경 안내문.pdf"), ("5002", "변경 대상자 명단.hwp"), ("5003", "수강신청 변경 안내문(사본).pdf"),
    ]
    assert parts.body_chars > 20


def test_post_parts_normalizes_category_prefix():
    html = fixture("article.html").replace("2026-2학기   수강신청 변경 안내", "[학사규정]\n      학력증명발급규정")
    assert extract.post_parts(html).title == "[학사규정] 학력증명발급규정"


def test_page_body_keeps_content_and_drops_frame():
    body = extract.page_body(fixture("page_content.html"))
    chars, tables, images, text = extract.html_metrics(body.html)
    assert body.updated_at == "2026-08-14"
    assert "휴학은 학업을" in text and "메뉴 글자" not in text and "tracking" not in text
    assert tables == 1 and images == 0 and chars > 100


def test_page_body_keeps_widget_content_after_input():
    # 학사일정 위젯: 입력칸 뒤 내용이 html.parser에서 입력칸 안으로 들어가도 사라지면 안 된다
    body = extract.page_body(fixture("page_calendar.html"))
    chars, tables, _, text = extract.html_metrics(body.html)
    assert body.widgets == ["schdulmanage"]
    assert "1학기 개강" in text and tables == 2
    assert "fnctId" not in text


def test_page_body_drops_board_widget():
    body = extract.page_body(fixture("page_board_widget.html"))
    assert body.widgets == ["bbs"]
    assert extract.html_metrics(body.html)[0] == 0


def test_faq_items():
    items = sites.faq_items(fixture("faq.html"))
    assert [item.question for item in items] == ["학생증은 어디서 받나요?", "등록금 분할 납부가 되나요?"]
    assert "질문" not in items[0].question
    text = extract.html_metrics(items[0].answer_html)[3]
    assert text.startswith("학생증은") and "답변" not in text


def test_viewer_files_prefers_download_links():
    files = sites.viewer_files(fixture("viewer.html"), "https://ipsi.inhatc.ac.kr/ipsi/362/subview.do")
    assert [(f.viewer_no, f.index, f.label) for f in files] == [("14", 1, "모집요강(출력용)"), ("14", 2, "지원자격 확인서")]
    assert files[0].url == "https://ipsi.inhatc.ac.kr/viewer/ipsi/14/fileDown1/fileDownload.do"


def test_viewer_files_falls_back_to_embedded_pdf():
    files = sites.viewer_files(fixture("viewer_tmp.html"), "https://ipsi.inhatc.ac.kr/ipsi/571/subview.do")
    assert len(files) == 1
    assert files[0].url == "https://ipsi.inhatc.ac.kr/sites/ipsi/atchmnfl/viewer/19//temp_1760000000000100.tmp"


def test_static_files():
    found = sites.static_files(fixture("ipsi_results.html"), "https://ipsi.inhatc.ac.kr/ipsi/406/subview.do")
    assert found[0] == ("https://ipsi.inhatc.ac.kr/sites/ipsi/files/result_2026total.pdf", "지원/성적현황")
    assert len(found) == 2


def test_disposition_filename():
    header = "attachment; filename=%ED%95%99%EC%B9%99%2820240902%29.pdf;"
    assert sites.disposition_filename(header) == "학칙(20240902).pdf"
    assert sites.disposition_filename("attachment; filename*=UTF-8''%EA%B7%9C%EC%A0%95.hwp") == "규정.hwp"
    assert sites.disposition_filename(None) is None


def test_suggestions():
    assert extract.semester_end("2026-03-05") == "2026-08-31"
    assert extract.semester_end("2026-09-20") == "2027-02-28"
    assert extract.semester_end("2027-01-10") == "2027-02-28"
    assert extract.semester_end("2027-10-01") == "2028-02-29"  # 윤년
    assert extract.suggest_year("2027 신입생 모집요강(출력용).pdf", None) == 2027
    assert extract.suggest_year("2026-2학기 수강신청 변경 안내", "2026-09-20") == 2026
    assert extract.suggest_year("학력증명발급규정(20240902).pdf", "2014-06-01") == 2014
    assert extract.revised_from_name("학력증명발급규정(20240902).pdf") == "2024-09-02"
    assert extract.group_name("[재공지] 2026학년도 2학기 국가장학금 신청 안내") == "국가장학금신청안내"
    assert extract.group_name("학력증명발급규정(20240902).pdf") == "학력증명발급규정"
    assert extract.suggest_topic("2026-2학기 등록금 분할납부 안내", "학사") == "장학·등록금"
    assert extract.suggest_topic("면접 일정", "입시") == "입시"
    assert extract.suggest_topic("도서관 이용 시간", None) == "학과·캠퍼스 생활"
    assert extract.suggest_topic("교명 변경 안내", None) == "기타"
    assert extract.suggest_topic("강의실 에어컨 고장·냉방", None) == "학과·캠퍼스 생활"  # '강의'보다 시설 낱말 먼저
    assert extract.suggest_topic("출결·공결 인정", None) == "학사"


def test_formats():
    assert extract.file_format("규정.HWP") == "hwp"
    assert extract.file_format("포스터.jpeg") == "image"
    assert extract.sniff_format("temp_1.tmp", b"%PDF-1.4") == "pdf"
    assert extract.sniff_format("noext", b"\xd0\xcf\x11\xe0\xa1\xb1") == "hwp"
    assert extract.file_ext("a.b.PDF") == "pdf"
