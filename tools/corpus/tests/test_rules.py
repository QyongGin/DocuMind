"""개인정보 규칙, 대장 ID, HWP 레코드, 수집 예절(간격·robots·오류 연속)."""

import struct
import zlib

import pytest
from conftest import FakeHttp, fixture, make_session

from corpus import hwp, ids, pii
from corpus.polite import MAX_INTERVAL, RobotsDisallowed, Stop, wildcard_disallows

# ---- 개인정보 ----


@pytest.mark.parametrize("title", ["2026 장학생 선발자 명단", "합격자 발표", "버스탑승대상자.hwp", "인증자 확인", "경품 당첨 안내"])
def test_first_pass_title_keywords(title):
    assert pii.judge(title, None)[0] == "보류"
    assert pii.judge(title, None)[1].startswith("1차")


@pytest.mark.parametrize("text, name", [
    ("학번 20261234 확인", "학번형 숫자"),
    ("연락처 010-1234-5678", "휴대전화"),
    ("01098765432로 연락", "휴대전화"),
    ("900101-1234567", "주민등록번호 형식"),
    ("홍*동 학생", "가린 이름"),
    ("김○수", "가린 이름"),
])
def test_second_pass_patterns(text, name):
    status, reason = pii.judge("안내", text)
    assert status == "보류" and name in reason


@pytest.mark.parametrize("text", [
    "학사 담당 032-870-1234",          # 학교 업무 전화
    "기간 2026.03.02 ~ 2026.03.20",   # 날짜
    "등록금 4,500,000원",
    "공고 번호 2026-15",
])
def test_second_pass_ignores_school_phone_and_dates(text):
    assert pii.judge("안내", text) == ("통과", None)


# ---- 대장 ID ----


def test_ids_follow_original_addresses():
    assert ids.page_id("kr", 236) == "www/page/236"
    assert ids.page_id("cs", 1741) == "cs/page/1741"
    post = ids.post_id("kr", 11, 110588)
    assert post == "www/bbs/11/110588"
    assert ids.attach_id(post, 162900) == "www/bbs/11/110588/a162900"
    assert ids.viewer_id("ipsi", 13) == "ipsi/viewer/13"
    assert ids.viewer_id("ipsi", 14, 2) == "ipsi/viewer/14/f2"
    assert ids.file_id("ipsi", "/sites/ipsi/files/result_2026total.pdf") == "ipsi/file/result_2026total"
    assert ids.raw_relpath(post, "post", "html") == "www/bbs/11/110588/body.html"
    assert ids.raw_relpath(ids.attach_id(post, 1), "attach", "hwp") == "www/bbs/11/110588/a1.hwp"


def test_faq_id_is_stable_across_whitespace():
    assert ids.faq_id("kr", 579, "학생증은 어디서 받나요?") == ids.faq_id("kr", 579, " 학생증은  어디서\n받나요? ")
    assert ids.faq_id("kr", 579, "가") != ids.faq_id("kr", 579, "나")


# ---- HWP 5.0 레코드 ----


def record(tag: int, body: bytes) -> bytes:
    size = len(body)
    if size >= 0xFFF:
        return struct.pack("<I", tag | (0xFFF << 20)) + struct.pack("<I", size) + body
    return struct.pack("<I", tag | (size << 20)) + body


def test_hwp_records_and_para_text():
    text = "규정 제1조".encode("utf-16-le")
    # 표 같은 확장 제어 문자(11)는 8글자(16바이트)를 차지한다
    control = struct.pack("<H", 11) + b"\x00" * 14
    para = text + control + struct.pack("<H", 13)
    long_para = ("가" * 3000).encode("utf-16-le")
    data = record(hwp.HWPTAG_PARA_TEXT, para) + record(hwp.HWPTAG_CTRL_HEADER, b" lbt" + b"\x00" * 4) \
        + record(hwp.HWPTAG_PARA_TEXT, long_para)
    parsed = list(hwp.records(data))
    assert [tag for tag, _ in parsed] == [hwp.HWPTAG_PARA_TEXT, hwp.HWPTAG_CTRL_HEADER, hwp.HWPTAG_PARA_TEXT]
    assert hwp.para_text(parsed[0][1]) == "규정 제1조\n"
    assert parsed[1][1][:4][::-1] == b"tbl "
    assert len(hwp.para_text(parsed[2][1])) == 3000


class FakeStream:
    def __init__(self, data: bytes):
        self.data = data

    def read(self) -> bytes:
        return self.data


class FakeOle:
    def __init__(self, streams: dict):
        self.streams = streams

    def openstream(self, name):
        key = name if isinstance(name, str) else "/".join(name)
        return FakeStream(self.streams[key])

    def listdir(self):
        return [key.split("/") for key in self.streams if key.startswith("BodyText/")]

    def close(self):
        pass


def file_header(flags: int) -> bytes:
    return b"HWP Document File".ljust(32, b"\x00") + struct.pack("<I", 0x05000000) + struct.pack("<I", flags)


def deflate(data: bytes) -> bytes:
    packer = zlib.compressobj(wbits=-15)
    return packer.compress(data) + packer.flush()


def test_hwp_extract_reads_compressed_sections(monkeypatch):
    section = record(hwp.HWPTAG_PARA_TEXT, "둘째 구역".encode("utf-16-le"))
    first = record(hwp.HWPTAG_PARA_TEXT, "첫 구역".encode("utf-16-le")) + record(hwp.HWPTAG_CTRL_HEADER, b" lbt")
    streams = {"FileHeader": file_header(1), "BodyText/Section1": deflate(section), "BodyText/Section0": deflate(first)}
    monkeypatch.setattr(hwp.olefile, "OleFileIO", lambda path: FakeOle(streams))
    result = hwp.extract("x.hwp")
    assert result.text == "첫 구역\n둘째 구역"
    assert result.tables == 1 and result.compressed and not result.encrypted


def test_hwp_extract_skips_encrypted(monkeypatch):
    streams = {"FileHeader": file_header(1 | 2), "BodyText/Section0": b"secret"}
    monkeypatch.setattr(hwp.olefile, "OleFileIO", lambda path: FakeOle(streams))
    result = hwp.extract("x.hwp")
    assert result.encrypted and result.text == ""


# ---- 수집 예절 ----


def test_requests_are_spaced_by_interval():
    http = FakeHttp({"https://example.inhatc.ac.kr/a": (200, "a", {}), "https://example.inhatc.ac.kr/b": (200, "b", {})})
    session = make_session(http)
    session.get("https://example.inhatc.ac.kr/a")
    session.get("https://example.inhatc.ac.kr/b")
    # robots.txt, a, b: 세 요청의 시작 사이가 모두 2초 이상
    assert http.requested == ["https://example.inhatc.ac.kr/robots.txt", "https://example.inhatc.ac.kr/a",
                              "https://example.inhatc.ac.kr/b"]
    assert session.fake_clock.sleeps == [2.0, 2.0]
    assert all("DocuMind" in headers["User-Agent"] for headers in http.headers)
    assert "@" not in http.headers[0]["User-Agent"]  # 이메일을 넣지 않는다


def test_robots_wildcard_rules_are_enforced():
    robots = fixture("robots_www.txt")
    patterns = wildcard_disallows(robots, "DocuMind-corpus-collector/0.1")
    assert any(p.match("/kr/topMngr/list.do") for p in patterns)
    http = FakeHttp({"https://www.inhatc.ac.kr/robots.txt": (200, robots, {})})
    session = make_session(http)
    assert not session.allowed("https://www.inhatc.ac.kr/kr/topMngr/list.do")
    assert not session.allowed("https://www.inhatc.ac.kr/admin/x")
    assert session.allowed("https://www.inhatc.ac.kr/kr/236/subview.do")
    with pytest.raises(RobotsDisallowed):
        session.get("https://www.inhatc.ac.kr/admin/x")
    assert http.requested == ["https://www.inhatc.ac.kr/robots.txt"]  # robots.txt는 호스트마다 한 번


def test_consecutive_errors_widen_interval_then_stop():
    http = FakeHttp({"https://example.inhatc.ac.kr/x": (503, "busy", {})})
    session = make_session(http)
    for expected in (4.0, 8.0, 16.0, MAX_INTERVAL):
        session.get("https://example.inhatc.ac.kr/x")
        assert session.interval == expected
    with pytest.raises(Stop):
        session.get("https://example.inhatc.ac.kr/x")


def test_success_resets_backoff():
    http = FakeHttp({"https://example.inhatc.ac.kr/bad": (429, "", {}), "https://example.inhatc.ac.kr/ok": (200, "", {})})
    session = make_session(http)
    session.get("https://example.inhatc.ac.kr/bad")
    assert session.interval == 4.0
    session.get("https://example.inhatc.ac.kr/ok")
    assert session.interval == 2.0 and session.consecutive_errors == 0


def test_request_cap_stops_run():
    http = FakeHttp({"https://example.inhatc.ac.kr/a": (200, "", {})})
    session = make_session(http, max_requests=2)
    session.get("https://example.inhatc.ac.kr/a")  # robots + a
    with pytest.raises(Stop):
        session.get("https://example.inhatc.ac.kr/a")


def test_hwp_para_text_joins_surrogate_pairs():
    text = "규정 😀 끝"
    assert hwp.para_text(text.encode("utf-16-le")) == text
    text.encode("utf-8")  # 대리 문자가 홀로 남으면 여기서 실패한다
