"""수집 통합: 합성 학교 사이트(conftest)를 가짜 HTTP로 돌린다. 네트워크는 쓰지 않는다."""

import csv
from datetime import date

from conftest import PDF_PHONE, TODAY, FakeHttp, make_session, ok, school_routes

from corpus import scope
from corpus.collect import Collector, three_years_before
from corpus.ledger import CSV_COLUMNS

WWW, IPSI = scope.WWW, scope.IPSI


def run(tmp_path, ledger, targets, routes=None):
    http = FakeHttp(routes or school_routes())
    session = make_session(http)
    collector = Collector(session, ledger, tmp_path, TODAY, log=lambda message: None)
    collector.run(targets)
    return http, collector


def rows_by_id(ledger):
    return {row["doc_id"]: dict(row) for row in ledger.con.execute("SELECT * FROM ledger")}


def test_cutoff_is_three_years():
    assert three_years_before(date(2026, 10, 2)) == date(2023, 10, 2)
    assert three_years_before(date(2028, 2, 29)) == date(2025, 2, 28)


def test_notices_follow_cutoff_rules_and_pii(tmp_path, ledger, small_scope):
    http, collector = run(tmp_path, ledger, ["notices"])
    rows = rows_by_id(ledger)
    requested = set(http.requested)

    # 3년 기준일(2023-10-02)보다 오래된 글(고정 공지 포함)은 열지 않고, 모두 오래된 3쪽에서 멈춘다
    for old in ("900", "999", "998"):
        assert f"{WWW}/bbs/kr/11/{old}/artclView.do" not in requested
    assert f"{WWW}/bbs/kr/11/artclList.do?page=3" in requested
    assert f"{WWW}/bbs/kr/11/artclList.do?page=4" not in requested

    # 글 본문: 제목 + 본문, 학교 업무 전화는 통과, 작성일·학기 끝 유효 기간·주제 제안
    post = rows["www/bbs/11/1003"]
    assert post["kind"] == "post" and post["format"] == "html" and post["pii_status"] == "통과"
    assert (post["posted_at"], post["valid_until"], post["topic"], post["academic_year"]) == (
        "2026-09-20", "2027-02-28", "학사", 2026)
    assert post["file_path"] == "raw/www/bbs/11/1003/body.html"
    body = (tmp_path / post["file_path"]).read_text(encoding="utf-8")
    assert "<h1>2026-2학기 수강신청 변경 안내</h1>" in body and "이전 글" not in body
    assert post["index_status"] == "색인"

    # 개인정보 1차(제목): 글을 열지 않고 보류 행만
    held_post = rows["www/bbs/11/1002"]
    assert f"{WWW}/bbs/kr/11/1002/artclView.do" not in requested
    assert (held_post["pii_status"], held_post["index_status"], held_post["file_path"]) == ("보류", "제외", None)
    assert held_post["pii_reason"] == "1차 제목·파일명: 명단"  # 키워드 목록 순서상 먼저 걸린 낱말

    # 개인정보 1차(첨부 파일명): 내려받지 않는다
    held = rows["www/bbs/11/1003/a5002"]
    assert f"{WWW}/bbs/kr/11/5002/download.do" not in requested
    assert (held["pii_status"], held["file_path"], held["format"]) == ("보류", None, "hwp")
    assert held["parent_id"] == "www/bbs/11/1003" and held["posted_at"] == "2026-09-20"

    # 개인정보 2차(본문 휴대전화)
    phone = rows["www/bbs/11/1001"]
    assert phone["pii_status"] == "보류" and "휴대전화" in phone["pii_reason"]

    # 첨부: 상위 글의 게시일·묶음을 물려받고, 같은 내용은 파일을 한 번만 둔다
    first, twin = rows["www/bbs/11/1003/a5001"], rows["www/bbs/11/1003/a5003"]
    assert first["format"] == "pdf" and first["text_chars"] > 100 and first["image_heavy"] == 0
    assert first["group_id"] == post["group_id"]
    assert twin["file_path"] == first["file_path"] and twin["sha256"] == first["sha256"]
    assert "내용 중복: www/bbs/11/1003/a5001" in twin["notes"] and twin["index_status"] == "제외"
    assert len(list((tmp_path / "raw/www/bbs/11/1003").glob("a*.pdf"))) == 1

    # 본문이 빈 글은 본문 행 없이 첨부만
    assert "www/bbs/11/1000" not in rows
    only_attach = rows["www/bbs/11/1000/a5010"]
    assert only_attach["posted_at"] == "2023-11-01"
    # 해마다 고쳐 쓰는 글: 유효 기간 제안은 늦은 날(수정일 2026-03-03) 기준 학기 끝
    assert (only_attach["academic_year"], only_attach["valid_until"]) == (2023, "2026-08-31")
    assert collector.counts.failed == 0


def test_resume_skips_finished_posts(tmp_path, ledger, small_scope):
    run(tmp_path, ledger, ["notices"])
    http, collector = run(tmp_path, ledger, ["notices"])
    assert not [url for url in http.requested if "artclView" in url or "download" in url]
    assert collector.counts.saved == 0 and collector.counts.skipped >= 3


def test_approved_attachment_is_downloaded_and_rechecked(tmp_path, ledger, small_scope):
    run(tmp_path, ledger, ["notices"])
    # 사용자가 1차 보류(파일명 '대상자')를 확인해 통과로 바꿨다
    path = tmp_path / "review.csv"
    ledger.export_review(path)
    with open(path, encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    for record in records:
        if record["doc_id"] == "www/bbs/11/1003/a5002":
            record.update(pii_status="통과", pii_reason="", index_status="색인", reviewed="1")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    ledger.import_review(path)

    routes = school_routes()
    routes[f"{WWW}/bbs/kr/11/5002/download.do"] = ok(PDF_PHONE, "변경 대상자 명단.pdf")
    http, _ = run(tmp_path, ledger, ["notices"], routes)
    assert f"{WWW}/bbs/kr/11/5002/download.do" in http.requested
    saved = ledger.get("www/bbs/11/1003/a5002")
    # 받은 내용에서 휴대전화가 나와 다시 확인 대기로 돌아간다
    assert saved["file_path"] and saved["pii_status"] == "보류" and saved["reviewed"] == 0
    assert "확인 뒤 받은 내용" in saved["pii_reason"]


def test_regulations(tmp_path, ledger, small_scope):
    run(tmp_path, ledger, ["regulations"])
    rows = rows_by_id(ledger)
    assert "www/bbs/32/2981" not in rows  # 본문이 빈 규정 글
    rule = rows["www/bbs/32/2981/a7001"]
    assert (rule["revised_at"], rule["valid_until"], rule["group_id"], rule["topic"]) == (
        "2024-09-02", "until_replaced", "규정:학력증명발급규정", "학사")
    assert rule["board"] == "정보목록(32)·학사규정" and rule["posted_at"] == "2014-06-01"


def test_pages_rules(tmp_path, ledger, small_scope):
    http, collector = run(tmp_path, ledger, ["pages"])
    rows = rows_by_id(ledger)
    assert set(rows) == {"www/page/157", "www/page/166", "www/page/123", "www/page/232"}
    assert f"{WWW}/kr/154/subview.do" not in http.requested  # 사이트맵 메뉴는 받지 않는다
    assert not [url for url in http.requested if "/ipsi/" in url or "/mecha/" in url]
    page = rows["www/page/232"]
    assert (page["title"], page["posted_at"], page["topic"], page["valid_until"], page["group_id"]) == (
        "휴학ㆍ복학", "2026-08-14", "학사", "until_replaced", "안내:휴학ㆍ복학")
    assert page["table_count"] == 1
    assert rows["www/page/123"]["table_count"] == 2  # 학사일정 위젯 내용
    people = rows["www/page/166"]
    assert people["pii_status"] == "보류" and people["pii_reason"] == scope.PEOPLE_REASON
    assert collector.counts.empty == 2  # 게시판 목록만 있는 페이지 둘(/kr/104, /kr/143)


def test_faq_rows(tmp_path, ledger, small_scope):
    run(tmp_path, ledger, ["faq"])
    rows = [row for row in rows_by_id(ledger).values() if row["kind"] == "faq"]
    assert len(rows) == 2
    by_title = {row["title"]: row for row in rows}
    card = by_title["학생증은 어디서 받나요?"]
    assert card["doc_id"].startswith("www/faq/579/q") and card["group_id"] == "FAQ:학교"
    assert card["pii_status"] == "통과" and card["url"] == f"{WWW}/kr/143/subview.do"
    assert by_title["등록금 분할 납부가 되나요?"]["topic"] == "장학·등록금"
    text = (tmp_path / card["file_path"]).read_text(encoding="utf-8")
    assert text.startswith("<h1>학생증은 어디서 받나요?</h1>")


def test_ipsi_viewers_and_results(tmp_path, ledger, small_scope):
    http, collector = run(tmp_path, ledger, ["ipsi"])
    rows = rows_by_id(ledger)
    guide = rows["ipsi/viewer/14"]
    assert (guide["title"], guide["academic_year"], guide["valid_until"], guide["group_id"]) == (
        "2027 신입생 모집요강(출력용).pdf", 2027, "2027-02-28", "모집요강:수시2차")
    assert guide["text_chars"] > 100 and guide["format"] == "pdf"
    assert rows["ipsi/viewer/14/f2"]["title"] == "지원자격 확인서.pdf"
    emu = rows["ipsi/viewer/19"]
    assert emu["title"] == "e-MU(전문학사) 모집요강(뷰어 원본).pdf" and emu["format"] == "pdf"
    assert emu["academic_year"] is None  # 학년도를 알 수 없으면 비워 사람이 확인
    result = rows["ipsi/file/result_2026total"]
    assert result["academic_year"] == 2026 and result["kind"] == "file"
    assert rows["ipsi/page/406"]["topic"] == "입시"
    # 없는 파일(2025)은 실패 목록에
    failures = ledger.con.execute("SELECT url, error FROM failures").fetchall()
    assert [(url, error) for url, error in failures] == [(f"{IPSI}/sites/ipsi/files/result_2025total.pdf", "HTTP 404")]
    # 모집요강 다운로드는 뷰어 페이지를 Referer로 보낸다
    index = http.requested.index(f"{IPSI}/viewer/ipsi/14/fileDown1/fileDownload.do")
    assert http.headers[index]["Referer"] == f"{IPSI}/ipsi/362/subview.do"


def test_departments(tmp_path, ledger, small_scope):
    http, _ = run(tmp_path, ledger, ["depts"])
    rows = rows_by_id(ledger)
    assert {"alpha/page/2001", "alpha/page/2002", "alpha/page/2010", "alpha/page/2012", "cs/page/1741",
            "mecha/page/3730"} == set(rows)
    roadmap = rows["alpha/page/2012"]  # 글 없이 그림만 있는 페이지도 '그림 위주'로 남긴다
    assert roadmap["image_heavy"] == 1 and roadmap["text_chars"] < 100
    assert "https://alpha.inhatc.ac.kr/alpha/2011/subview.do" not in http.requested  # 학과 취업공고
    assert "https://alpha.inhatc.ac.kr/alpha/2020/subview.do" not in http.requested  # 커뮤니티
    intro = rows["alpha/page/2001"]
    assert (intro["title"], intro["topic"], intro["group_id"]) == ("학과소개(알파공학과)", "학과·캠퍼스 생활", "학과:알파공학과:학과소개")
    assert rows["alpha/page/2002"]["pii_status"] == "보류"  # 교수진
    renamed = rows["cs/page/1741"]
    assert (renamed["title"], renamed["aliases"]) == ("학과소개(AI소프트웨어학과)", "컴퓨터정보공학과")


def test_stats_report_attachment_sizes(tmp_path, ledger, small_scope):
    run(tmp_path, ledger, ["notices"])
    stats = ledger.stats()
    assert stats["attachments"]["pdf"]["files"] == 3
    assert stats["pii_status"]["보류"] == 3
    assert stats["failures"] == 0


def test_faq_first_pass_hit_keeps_no_original(tmp_path, ledger, small_scope):
    routes = school_routes()
    extra = ("<li><a class='question' href='#none'><span class='hidden'>질문</span>합격자 발표는 언제인가요?</a>"
             "<div class='answer-box'><div class='answer'><p>발표 일정은 모집요강을 따른다.</p></div></div></li></ul>")
    status, body, headers = routes[f"{WWW}/kr/143/subview.do"]
    routes[f"{WWW}/kr/143/subview.do"] = (status, body.replace("</ul>", extra, 1), headers)
    run(tmp_path, ledger, ["faq"], routes)
    held = [row for row in rows_by_id(ledger).values() if row["title"] == "합격자 발표는 언제인가요?"][0]
    assert (held["pii_status"], held["file_path"], held["index_status"]) == ("보류", None, "제외")
    assert len(list((tmp_path / "raw/www/faq/579").glob("*.html"))) == 2


def edge_routes():
    """그림만 있는 글, 내용 없는 글, 첨부만 있는 글, 빈 첨부, .hwp로 올린 HWPX."""
    from conftest import PDF_ONLY_ATTACH, board_list, k2_article, make_hwpx

    routes = {f"{WWW}/robots.txt": (200, "User-agent: *\nAllow: /\n", {})}
    routes[f"{WWW}/bbs/kr/11/artclList.do?page=1"] = ok(board_list([
        ("2001", "포스터 공지", "2026.09.10."), ("2002", "동영상 공지", "2026.09.11."),
        ("2003", "첨부만 공지", "2026.09.12."), ("2004", "빈 첨부 공지", "2026.09.13."),
        ("2005", "HWPX 첨부 공지", "2026.09.14."),
    ]))
    article = f"{WWW}/bbs/kr/11/{{}}/artclView.do"
    routes[article.format(2001)] = ok(k2_article("2001", "포스터 공지", "2026.09.10.", "<p><img src='/p.png'></p>", []))
    routes[article.format(2002)] = ok(k2_article("2002", "동영상 공지", "2026.09.11.", "<iframe src='/v'></iframe>", []))
    routes[article.format(2003)] = ok(k2_article("2003", "첨부만 공지", "2026.09.12.", "", [("6003", "안내.pdf")]))
    routes[article.format(2004)] = ok(k2_article("2004", "빈 첨부 공지", "2026.09.13.", "<p>첨부 서식을 내려받아 제출한다. 기한은 이번 달 말이다.</p>",
                                                 [("6001", "신청서.hwp")]))
    routes[article.format(2005)] = ok(k2_article("2005", "HWPX 첨부 공지", "2026.09.14.", "<p>세부 내용은 붙임 문서를 참고한다. 문의는 담당 부서로 한다.</p>",
                                                 [("6002", "세부 안내.hwp")]))
    routes[f"{WWW}/bbs/kr/11/6003/download.do"] = ok(PDF_ONLY_ATTACH, "안내.pdf")
    routes[f"{WWW}/bbs/kr/11/6001/download.do"] = ok(b"", "신청서.hwp")
    routes[f"{WWW}/bbs/kr/11/6002/download.do"] = ok(make_hwpx(["신청 기간은 9월 말까지이다."], tables=1), "세부 안내.hwp")
    return routes


def test_every_post_is_recorded(tmp_path, ledger, small_scope):
    run(tmp_path, ledger, ["notices"], edge_routes())
    rows = rows_by_id(ledger)
    poster = rows["www/bbs/11/2001"]  # 그림만 있는 글도 행으로(그림 위주)
    assert poster["image_heavy"] == 1 and poster["index_status"] == "색인" and poster["pii_status"] == "통과"
    video = rows["www/bbs/11/2002"]  # 글·그림·첨부가 모두 없는 글도 출처로 남기되 색인 제외
    assert video["index_status"] == "제외" and "본문 글·그림·첨부 없음" in video["notes"]
    assert "www/bbs/11/2003" not in rows and "www/bbs/11/2003/a6003" in rows  # 첨부만 있는 글은 첨부 행으로
    empty = rows["www/bbs/11/2004/a6001"]  # 0바이트 첨부: 원본 없이 행만
    assert (empty["size_bytes"], empty["file_path"], empty["index_status"], empty["pii_status"]) == (0, None, "제외", "통과")
    assert empty["notes"].startswith("빈 파일(0바이트)")
    hwpx = rows["www/bbs/11/2005/a6002"]  # 이름은 .hwp, 내용은 HWPX
    assert hwpx["format"] == "hwpx" and hwpx["file_path"].endswith(".hwpx")
    assert hwpx["text_chars"] > 0 and hwpx["table_count"] == 1 and hwpx["pii_status"] == "통과"


def test_visited_post_without_rows_is_redone(tmp_path, ledger, small_scope):
    # 예전 판 수집기가 끝냈다고 적었지만 대장에 남지 않은 글(그림 포스터)은 다시 처리한다
    ledger.mark_visited("www/bbs/11/2001")
    run(tmp_path, ledger, ["notices"], edge_routes())
    assert ledger.has("www/bbs/11/2001")
    # 대장에 남은 글은 다시 열지 않는다
    http, _ = run(tmp_path, ledger, ["notices"], edge_routes())
    assert not [url for url in http.requested if "artclView" in url or "download" in url]


def test_remeasure_fixes_unread_rows(tmp_path, ledger):
    from conftest import make_hwpx

    from corpus.collect import EMPTY_FILE_NOTE, remeasure

    raw = tmp_path / "raw" / "www" / "bbs" / "1" / "1"
    raw.mkdir(parents=True)
    (raw / "a1.hwp").write_bytes(make_hwpx(["규정 안내 문서이다."]))
    (raw / "a3.hwp").write_bytes(b"")
    unread = {"site": "www", "kind": "attach", "url": "u", "collected_at": "2026-10-02", "format": "hwp",
              "pii_status": "보류", "pii_reason": "2차 검사 못 함(형식 hwp, 글자 추출 실패: NotOleFileError)",
              "index_status": "제외"}
    ledger.upsert({"doc_id": "www/bbs/1/1/a1", "title": "안내.hwp", "file_path": "raw/www/bbs/1/1/a1.hwp",
                   "notes": "글자 추출 실패: NotOleFileError", **unread})
    ledger.upsert({"doc_id": "www/bbs/2/1/a2", "title": "안내.hwp", "file_path": "raw/www/bbs/1/1/a1.hwp",
                   "notes": "글자 추출 실패: NotOleFileError / 내용 중복: www/bbs/1/1/a1", **unread})
    (raw / "a4.hwp").write_bytes(b"not an ole file")
    ledger.upsert({"doc_id": "www/bbs/1/1/a3", "title": "빈.hwp", "file_path": "raw/www/bbs/1/1/a3.hwp", **unread})
    ledger.upsert({"doc_id": "www/bbs/3/1/a5", "title": "빈.hwp", "file_path": "raw/www/bbs/1/1/a3.hwp", **unread})
    ledger.upsert({"doc_id": "www/bbs/1/1/a4", "title": "확인함.hwp", "file_path": "raw/www/bbs/1/1/a4.hwp", **unread})
    ledger.con.execute("UPDATE ledger SET reviewed = 1 WHERE doc_id = 'www/bbs/1/1/a4'")
    report = remeasure(ledger, tmp_path, TODAY)
    assert report == {"checked": 3, "format_fixed": 2, "now_readable": 2, "empty_files": 1}
    first, twin = ledger.get("www/bbs/1/1/a1"), ledger.get("www/bbs/2/1/a2")
    assert first["format"] == "hwpx" and first["file_path"] == "raw/www/bbs/1/1/a1.hwpx"
    assert (tmp_path / first["file_path"]).exists() and not (raw / "a1.hwp").exists()
    assert first["text_chars"] > 0 and first["pii_status"] == "통과" and first["notes"] is None
    assert first["index_status"] == "색인"
    assert twin["file_path"] == first["file_path"] and twin["notes"] == "내용 중복: www/bbs/1/1/a1"
    assert twin["index_status"] == "제외" and twin["pii_status"] == "통과"
    for doc_id in ("www/bbs/1/1/a3", "www/bbs/3/1/a5"):  # 0바이트 파일은 지우고, 같은 파일을 가리키던 행도 함께
        empty = ledger.get(doc_id)
        assert (empty["file_path"], empty["notes"], empty["index_status"]) == (None, EMPTY_FILE_NOTE, "제외")
    assert not (raw / "a3.hwp").exists()
    reviewed = ledger.get("www/bbs/1/1/a4")  # 사람이 확인한 행은 건드리지 않는다
    assert reviewed["notes"] is None and reviewed["pii_status"] == "보류" and reviewed["text_chars"] is None


def test_remeasure_keeps_empty_file_used_by_reviewed_row(tmp_path, ledger):
    from corpus.collect import remeasure

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "e.hwp").write_bytes(b"")
    base = {"site": "www", "kind": "attach", "url": "u", "collected_at": "2026-10-02", "format": "hwp",
            "title": "빈.hwp", "file_path": "raw/e.hwp", "pii_status": "보류", "pii_reason": "2차 검사 못 함(형식 hwp)"}
    ledger.upsert({"doc_id": "www/bbs/1/1/a1", **base})
    ledger.upsert({"doc_id": "www/bbs/1/1/a2", **base})
    ledger.con.execute("UPDATE ledger SET reviewed = 1 WHERE doc_id = 'www/bbs/1/1/a2'")
    remeasure(ledger, tmp_path, TODAY)
    assert (raw / "e.hwp").exists()  # 확인한 행(a2)이 가리키므로 남긴다
    assert ledger.get("www/bbs/1/1/a1")["file_path"] is None and ledger.get("www/bbs/1/1/a2")["file_path"] == "raw/e.hwp"


def test_approved_post_with_keyword_title_gets_its_attachment(tmp_path, ledger, small_scope):
    """사람이 통과로 확인한 글은 제목에 키워드(대상자)가 있어도 다시 보류하지 않고 첨부를 받는다."""
    from conftest import PDF_ONLY_ATTACH, board_list, k2_article

    routes = {f"{WWW}/robots.txt": (200, "User-agent: *\nAllow: /\n", {})}
    routes[f"{WWW}/bbs/kr/11/artclList.do?page=1"] = ok(board_list([("3001", "장학금 지원대상자 선발 안내", "2026.09.15.")]))
    routes[f"{WWW}/bbs/kr/11/3001/artclView.do"] = ok(k2_article(
        "3001", "장학금 지원대상자 선발 안내", "2026.09.15.", "<p>신청 자격과 기간을 안내한다. 자세한 내용은 붙임 공고를 본다.</p>",
        [("8001", "지원대상자 선발 공고.pdf")]))
    routes[f"{WWW}/bbs/kr/11/8001/download.do"] = ok(PDF_ONLY_ATTACH, "지원대상자 선발 공고.pdf")
    run(tmp_path, ledger, ["notices"], routes)  # 1차: 글을 열지 않고 보류
    assert ledger.get("www/bbs/11/3001")["file_path"] is None
    # 사람이 글을 통과로 확인 → 다음 수집에서 글을 받는다. 첨부는 파일명 키워드로 다시 1차 보류
    ledger.con.execute("UPDATE ledger SET pii_status='통과', reviewed=1 WHERE doc_id='www/bbs/11/3001'")
    run(tmp_path, ledger, ["notices"], routes)
    assert ledger.get("www/bbs/11/3001")["file_path"]
    attach = "www/bbs/11/3001/a8001"
    assert ledger.get(attach)["pii_status"] == "보류" and ledger.get(attach)["file_path"] is None
    # 사람이 첨부도 통과로 확인 → 제목에 키워드가 있는 글이어도 첨부를 받는다
    ledger.con.execute("UPDATE ledger SET pii_status='통과', reviewed=1 WHERE doc_id=?", (attach,))
    http, _ = run(tmp_path, ledger, ["notices"], routes)
    assert f"{WWW}/bbs/kr/11/8001/download.do" in http.requested
    assert ledger.get(attach)["file_path"]
