"""수집 통합: 합성 학교 사이트(conftest)를 가짜 HTTP로 돌린다. 네트워크는 쓰지 않는다."""

import csv
from datetime import date, datetime

import pytest
from conftest import PDF_PHONE, TODAY, FakeHttp, make_session, ok, school_routes

from corpus import scope
from corpus.collect import Collector, three_years_before
from corpus.ledger import CSV_COLUMNS
from corpus.polite import KST, Stop

WWW, IPSI = scope.WWW, scope.IPSI


def run(tmp_path, ledger, targets, routes=None, now=None):
    http = FakeHttp(routes or school_routes())
    session = make_session(http, now=now) if now else make_session(http)
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


def test_business_hours_stop_keeps_progress(tmp_path, ledger, small_scope):
    with pytest.raises(Stop):
        run(tmp_path, ledger, ["notices"], now=datetime(2026, 10, 5, 10, 0, tzinfo=KST))
    assert ledger.stats()["rows"] == 0


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
