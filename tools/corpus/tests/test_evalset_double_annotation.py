"""이중 라벨링(결정 ⑦-1~⑦-4): 원본 읽기, 작업 단위 묶기, 이중 라벨링 세션 실행(가짜), 출력 읽기, 규칙 기반 채점, 세션 격리 시험."""

import json
import subprocess
from datetime import date

import pytest
from evalset_data import build_corpus, item, unanswerable_item

from corpus.evalset import double_annotation

TODAY = date(2026, 10, 6)
PASSED = {"errors": [], "warnings": []}


def checked(entry: dict) -> dict:
    entry["validation"] = dict(PASSED)
    return entry


def envelope(answers: list[dict], **extra) -> str:
    """`claude -p --output-format json`의 출력 모양. 답 JSON 앞뒤에 말이 붙어도 읽어야 한다."""
    result = "확인했습니다.\n```json\n" + json.dumps({"answers": answers}, ensure_ascii=False) + "\n```"
    return json.dumps({"type": "result", "is_error": False, "result": result, **extra}, ensure_ascii=False)


class FakeClaude:
    """이중 라벨링 세션 대신: 작업 단위 폴더를 기록하고 정해 둔 답을 돌려준다."""

    def __init__(self, answers: dict[str, str]):
        self.answers = answers
        self.calls = []

    def __call__(self, command, cwd):
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, "2.1.205 (Claude Code)\n", "")
        questions = json.loads((cwd / "questions.json").read_text(encoding="utf-8"))["questions"]
        self.calls.append({"cwd": cwd, "command": command, "questions": questions,
                           "files": sorted(path.relative_to(cwd).as_posix() for path in cwd.rglob("*") if path.is_file())})
        reply = [{"id": question["id"], "answer": self.answers[question["id"]], "quote": "원문", "where": "1쪽", "note": ""}
                 for question in questions if question["id"] in self.answers]
        return subprocess.CompletedProcess(command, 0, envelope(reply), "")


def test_clean_html_drops_decoration_but_keeps_merged_cells():
    html = """<div class="wrap" style="color:red"><script>track()</script><style>.a{}</style>
    <table class="tbl"><tr><th rowspan="2" class="h">구분</th><th colspan="2" style="x">수시</th></tr>
    <tr><td>1차</td><td>2차</td></tr></table><img src="a.png" alt="전형 일정표"><!-- 숨은 글 -->
    <form><input value="검색"><button>찾기</button></form><p onclick="go()">원서 접수 9. 8.</p></div>"""
    cleaned = double_annotation.clean_html(html)
    assert 'rowspan="2"' in cleaned and 'colspan="2"' in cleaned
    for gone in ("track()", ".a{}", "class=", "style=", "onclick", "숨은 글", "검색", "찾기", "<div", "<form"):
        assert gone not in cleaned
    assert "[그림: 전형 일정표]" in cleaned and "<p>원서 접수 9. 8.</p>" in cleaned


def test_write_source_reads_each_format_without_service_conversion(ledger, tmp_path):
    build_corpus(ledger, tmp_path)
    dest = tmp_path / "out"
    html = double_annotation.write_source(ledger, tmp_path, "gana/page/fee", dest / "fee")
    assert html.reader == double_annotation.READERS["html"] and html.files == ["gana__page__fee.html"]
    assert "<td>30,000원</td>" in (dest / "fee" / "gana__page__fee.html").read_text(encoding="utf-8")

    pdf = double_annotation.write_source(ledger, tmp_path, "gana/viewer/guide", dest / "guide", scale=0.5)
    assert pdf.files == [f"gana__viewer__guide/page-00{page}.{kind}" for page in (1, 2) for kind in ("png", "txt")]
    assert (dest / "guide" / "gana__viewer__guide" / "page-001.png").read_bytes()[:4] == b"\x89PNG"
    assert "Fee 30000" in (dest / "guide" / "gana__viewer__guide" / "page-002.txt").read_text(encoding="utf-8")

    with pytest.raises(double_annotation.AnnotationError, match="원본 파일이 대장에 없음"):
        double_annotation.write_source(ledger, tmp_path, "gana/page/none", dest / "none")


def test_plan_groups_by_documents_and_skips_unchecked_or_done():
    items = [
        checked(item("ev-0001")),
        checked(item("ev-0002", question="실기 추가 비용은?")),
        checked(item("ev-0003", evidence=[{"doc": "gana/page/leave", "quote": "휴학원서 1부"},
                                          {"doc": "gana/page/fee", "quote": "전형료 30,000원"}])),
        checked(unanswerable_item("ev-0004")),
        checked(unanswerable_item("ev-0005", unanswerable={"kind": "자료 없음", "near": None,
                                                 "check": {"terms": ["정원"], "hits": 0}})),
        item("ev-0006"),  # 자동 검증 전
        {**checked(item("ev-0007")), "validation": {"errors": ["인용 없음"], "warnings": []}},
        {**checked(item("ev-0008")), "second_annotation": {"verdict": "일치"}},  # 이미 풀었음
    ]
    packets, no_doc, skipped = double_annotation.plan(items, max_per_packet=2)
    assert [(packet.docs, [q["id"] for q in packet.questions]) for packet in packets] == [
        (("gana/page/fee",), ["ev-0001", "ev-0002"]),
        (("gana/page/fee",), ["ev-0004"]),
        (("gana/page/fee", "gana/page/leave"), ["ev-0003"]),
    ]
    assert [entry["id"] for entry in no_doc] == ["ev-0005"] and skipped == ["ev-0006", "ev-0007"]
    for packet in packets:  # 작업 단위에는 질문만 들어간다(정답·인용 위치 없음)
        assert all(set(question) == {"id", "question"} for question in packet.questions)


def test_parse_output_reads_answers_and_rejects_bad_output():
    answers = double_annotation.parse_output(envelope([{"id": "ev-0001", "answer": "3만 원"}]))
    assert answers == [{"id": "ev-0001", "answer": "3만 원"}]
    for bad, message in (("not json", "JSON이 아님"),
                         (json.dumps({"is_error": True, "result": "한도 초과"}), "Claude Code 오류"),
                         (json.dumps({"result": "답을 못 찾음"}), "JSON이 없음"),
                         (json.dumps({"result": '{"answers": [{"id": 1}]}'}), "id·answer")):
        with pytest.raises(double_annotation.AnnotationError, match=message):
            double_annotation.parse_output(bad)


def test_run_fills_second_annotation_and_keeps_ground_truth_out(ledger, tmp_path):
    build_corpus(ledger, tmp_path)
    items = [
        checked(item("ev-0001")),
        checked(item("ev-0002", question="가나대 실기 추가 비용은?", tags=["표 근거"], forbidden=[],
                     answer="실기 추가 비용은 15,000원입니다.",
                     facts=[{"name": "실기 추가", "values": ["15,000원"]}],
                     evidence=[{"doc": "gana/page/fee", "quote": "실기 추가 15,000원"}])),
        checked(unanswerable_item("ev-0003")),
        checked(item("ev-0004", question="휴학 서류는?", shape="목록", tags=["글 근거"], forbidden=[],
                     answer="휴학원서와 보호자 동의서입니다.",
                     facts=[{"name": "서류1", "values": ["휴학원서"]}, {"name": "서류2", "values": ["보호자 동의서"]}],
                     evidence=[{"doc": "gana/page/leave", "quote": "휴학원서 1부, 보호자 동의서 1부"}])),
        checked(item("ev-0005", question="가나대 수시 원서비는?")),
    ]
    fake = FakeClaude({"ev-0001": "전형료는 30,000원입니다.", "ev-0002": "실기 추가는 25,000원입니다.",
                       "ev-0003": double_annotation.NOT_FOUND, "ev-0005": "25,000원입니다."})  # ev-0004는 답하지 않음
    work, record = tmp_path / "work", tmp_path / "record"
    result = double_annotation.run(items, ledger, tmp_path, record, work, "claude-test", TODAY, runner=fake, jobs=1)

    by_id = {entry["id"]: entry for entry in items}
    assert by_id["ev-0001"]["second_annotation"]["verdict"] == "일치" and by_id["ev-0001"]["second_annotation"]["label"] == "맞음"
    assert by_id["ev-0002"]["second_annotation"]["verdict"] == "애매"  # 필수 사실이 없는 다른 값: 규칙이 못 정해 사람에게
    assert by_id["ev-0005"]["second_annotation"]["verdict"] == "불일치" and by_id["ev-0005"]["second_annotation"]["label"] == "틀림"  # 금지 값
    assert by_id["ev-0003"]["second_annotation"]["verdict"] == "일치"  # 답 없는 문항: 문서에 없다고 답함
    assert "second_annotation" not in by_id["ev-0004"] and result["unanswered"] == ["ev-0004"]
    assert by_id["ev-0001"]["second_annotation"]["model"] == "claude-test · 다른 세션 · Claude Code 2.1.205"
    assert by_id["ev-0001"]["second_annotation"]["reader"] == double_annotation.READERS["html"] and by_id["ev-0001"]["second_annotation"]["at"] == "2026-10-06"
    assert by_id["ev-0001"]["second_annotation"]["note"] is None  # 빈 덧붙임은 없음으로
    assert result["verdicts"] == {"일치": 2, "애매": 1, "불일치": 1} and result["failed"] == []

    for call in fake.calls:  # 이중 라벨링 세션이 받은 폴더에 정답·인용이 없다
        assert call["command"][:2] == ["claude", "-p"] and "--restricted" in call["command"]
        assert call["files"][0] == "docs/gana__page__fee.html" or call["files"][0] == "docs/gana__page__leave.html"
        packet_text = "".join((call["cwd"] / name).read_text(encoding="utf-8") for name in call["files"])
        assert "정답" not in json.dumps(call["questions"], ensure_ascii=False)
        assert "30,000원입니다" not in packet_text and "15,000원입니다" not in packet_text
    saved = json.loads((record / "p001" / "packet.json").read_text(encoding="utf-8"))
    assert saved["questions"][0]["id"] == "ev-0001" and "answer" not in json.dumps(saved["questions"])
    assert (record / "p001" / "output.json").exists()

    again = double_annotation.run(items, ledger, tmp_path, tmp_path / "record2", tmp_path / "work2", "claude-test", TODAY,
                      runner=FakeClaude({"ev-0004": "휴학원서, 보호자 동의서"}), jobs=1)
    assert again["asked"] == 1 and by_id["ev-0004"]["second_annotation"]["verdict"] == "일치"  # 남은 문항만 다시 푼다


def test_failed_packet_is_reported_and_record_can_be_applied_later(ledger, tmp_path):
    build_corpus(ledger, tmp_path)
    items = [checked(item("ev-0001"))]

    def broken(command, cwd):
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, "2.1.205 (Claude Code)", "")
        return subprocess.CompletedProcess(command, 1, json.dumps({"is_error": True, "result": "로그인 필요"}), "")

    result = double_annotation.run(items, ledger, tmp_path, tmp_path / "record", tmp_path / "work", "m", TODAY, runner=broken)
    assert result["failed"] == [("p001", "Claude Code 오류: 로그인 필요")] and "second_annotation" not in items[0]

    (tmp_path / "record" / "p001" / "output.json").write_text(
        envelope([{"id": "ev-0001", "answer": "3만 원이에요"}]), encoding="utf-8")
    applied = double_annotation.apply_record(items, tmp_path / "record", TODAY)
    assert applied["failed"] == [] and items[0]["second_annotation"]["verdict"] == "일치"
    assert items[0]["second_annotation"]["model"] == "m · 다른 세션 · Claude Code 2.1.205"


def test_repo_marker_finds_repository_above(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "CLAUDE.md").write_text("지침", encoding="utf-8")
    assert double_annotation.repo_marker(tmp_path / "repo" / "a" / "b") == tmp_path / "repo" / "CLAUDE.md"
    assert double_annotation.repo_marker(tmp_path / "elsewhere") is None


@pytest.mark.parametrize("leak, read_inside, passed", [(False, True, True), (True, True, False), (False, False, False)])
def test_isolation_passes_only_when_inside_read_and_outside_hidden(tmp_path, leak, read_inside, passed):
    def session(command, cwd):
        notice = (cwd / "docs" / "notice.txt").read_text(encoding="utf-8")
        key = json.loads((cwd.parent / "answer_key.json").read_text(encoding="utf-8"))["ev-0001"]["answer"]
        result = (notice if read_inside else "못 읽음") + (key if leak else " 밖은 막힘")
        assert "--restricted" in command and "--safe-mode" in command and command[command.index("--tools") + 1] == "Read,Grep,Glob"
        return subprocess.CompletedProcess(command, 0, json.dumps(
            {"result": result, "permission_denials": [{"tool_name": "Read"}]}, ensure_ascii=False), "")

    result = double_annotation.isolation_test(tmp_path, "m", runner=session)
    assert (result["passed"], result["leaked"], result["read_inside"]) == (passed, leak, read_inside)
    assert result["denials"] == 1


def test_apply_answers_keeps_first_answer_and_existing_results():
    items = [checked(item("ev-0001")), {**checked(item("ev-0002")), "second_annotation": {"verdict": "불일치", "answer": "전"}}]
    packet = double_annotation.Packet("p001", ("gana/page/fee",), [{"id": "ev-0001", "question": "q"}, {"id": "ev-0002", "question": "q"}])
    missing = double_annotation.apply_answers(items, packet, [
        {"id": "ev-0001", "answer": "30,000원", "note": "단위는 원"}, {"id": "ev-0001", "answer": "25,000원"},  # 같은 문항 두 번
        {"id": "ev-0002", "answer": "30,000원"}, {"id": "ev-9999", "answer": "작업 단위에 없는 문항"},
    ], "m", "r", TODAY)
    assert missing == [] and items[0]["second_annotation"]["answer"] == "30,000원" and items[0]["second_annotation"]["verdict"] == "일치"
    assert items[0]["second_annotation"]["note"] == "단위는 원"
    assert items[1]["second_annotation"] == {"verdict": "불일치", "answer": "전"}  # 이미 채운 결과는 그대로
