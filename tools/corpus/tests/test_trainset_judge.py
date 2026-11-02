"""학습 예시 판정(`trainset judge`)·사람 표본 화면·판정 기록 합치기. Claude는 부르지 않고 가짜 실행기로."""

import json
import subprocess

import pytest

from corpus.trainset import judge, pipeline, review
from test_trainset import PROMPT, record


def judged(item_id, kind, verdict, **extra):
    return record(id=item_id, kind=kind, verdict=verdict, category="" if verdict == "통과" else "값 틀림",
                  reason="근거 1에 있음", user="재학생", **extra)


def test_example_hides_hint_and_student_answer():
    shown = judge.example(record(hint="정답 줄", ax_answer="학습 전 답", user="재학생",
                                 result={"ga": {"judge_notes": ["확인 메모"]}}))
    assert shown["챗봇 입력"] == PROMPT and shown["종류"] == "답 · 사실 하나" and shown["자동 검사 메모"] == ["확인 메모"]
    assert "정답 줄" not in json.dumps(shown, ensure_ascii=False) and "학습 전 답" not in json.dumps(shown, ensure_ascii=False)


def envelope(verdicts, is_error=False):
    return json.dumps({"is_error": is_error, "result": "판정입니다\n" + json.dumps({"verdicts": verdicts}, ensure_ascii=False)})


def test_parse_output_requires_every_example_with_known_verdict():
    good = envelope([{"id": "a", "verdict": "통과", "category": "", "reason": "맞음"},
                     {"id": "b", "verdict": "탈락", "category": "값 틀림", "reason": "다른 해"}])
    assert [entry["verdict"] for entry in judge.parse_output(good, ["a", "b"])] == ["통과", "탈락"]
    with pytest.raises(judge.JudgeError):
        judge.parse_output(envelope([{"id": "a", "verdict": "통과"}]), ["a", "b"])  # b가 빠짐
    with pytest.raises(judge.JudgeError):
        judge.parse_output(envelope([{"id": "a", "verdict": "아마도"}]), ["a"])  # 정해진 값이 아님
    with pytest.raises(judge.JudgeError):  # 판정이 다 있어도 Claude Code가 오류라고 하면 쓰지 않는다
        judge.parse_output(envelope([{"id": "a", "verdict": "통과"}], is_error=True), ["a"])


def test_run_judges_in_isolated_packets(tmp_path):
    seen = []

    def runner(command, cwd):
        if command[:2] == ["claude", "--version"]:
            return subprocess.CompletedProcess(command, 0, "9.9.9 (Claude Code)", "")
        examples = json.loads((cwd / "examples.json").read_text(encoding="utf-8"))
        seen.append((cwd.name, [example["id"] for example in examples], command))
        return subprocess.CompletedProcess(command, 0, envelope(
            [{"id": example["id"], "verdict": "통과", "category": "", "reason": "맞음"} for example in examples]), "")

    records = [record(id=f"r-{n}", user="재학생") for n in range(10)]
    results, failed = judge.run(records, tmp_path / "work", "claude-x", runner=runner, jobs=1, per_packet=4)
    assert failed == [] and len(results) == 10 and results[0]["judge"].startswith("claude-x · Claude Code 9.9.9")
    assert [len(ids) for _, ids, _ in seen] == [4, 4, 2]
    command = seen[0][2]
    assert "--restricted" in command and "--safe-mode" in command and "Read,Grep,Glob" in command
    assert judge.PROMPT in command  # 판정 지침을 지시문으로


def test_run_refuses_work_folder_inside_repo(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("규칙", encoding="utf-8")
    with pytest.raises(judge.JudgeError):
        judge.run([record(user="재학생")], tmp_path / "work", runner=lambda c, w: None)


def test_sample_keeps_failures_and_spreads_kinds():
    records = [judged(f"p-{n}", kind, "통과") for n, kind in enumerate(["fact", "table", "procedure"] * 10)]
    records += [judged(f"f-{n}", "fact", "탈락") for n in range(20)]
    chosen = review.sample(records, 30, seed=1)
    assert len(chosen) == 30
    assert sum(item["verdict"] == "탈락" for item in chosen) == 15  # 탈락은 절반까지
    passed_kinds = [item["kind"] for item in chosen if item["verdict"] == "통과"]
    assert {kind: passed_kinds.count(kind) for kind in set(passed_kinds)} == {"fact": 5, "table": 5, "procedure": 5}
    few = review.sample(records[:3] + records[30:], 10, seed=1)  # 통과가 3개뿐이면 남은 자리를 탈락으로
    assert len(few) == 10 and sum(item["verdict"] == "통과" for item in few) == 3


def test_page_embeds_examples_and_hides_nothing_needed():
    html = review.page([judged("r-1", "fact", "통과", target_ga="8월 29일까지입니다. </script>\n[출처 1]")], "r1-first")
    data = json.loads(html.split("const D=", 1)[1].split(";\nconst KEY", 1)[0])
    example = data["examples"][0]
    assert data["batch"] == "r1-first" and example["claude"]["verdict"] == "통과"
    assert [block["cited"] for block in example["blocks"]] == [True, False]
    assert ("8월 29일까지", "c0") in painted(example["target"], example["target_marks"])
    assert html.count("</script>") == 1  # 데이터 속 닫는 태그가 화면의 스크립트를 끊지 않게(본래 닫는 태그 하나만)


def painted(text, marks):
    return [(text[start:end], tag) for start, end, tag in marks]


def test_highlight_pairs_answer_and_evidence_by_sentence():
    blocks = {1: "가나대학 휴학 신청 기간은 8월 18일부터 8월 29일까지이다.\n문의는 학사지원팀 02-000-0000.",
              2: "1. 등록금: 신입생 행 정보는 금액=1,200,000원이다."}
    target = "가나대학 휴학은 8월 29일까지 신청합니다. 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"
    marks = review.highlight(target, "가나대학 휴학 언제까지 신청해?", blocks)
    answer = painted(target, marks["target"])
    assert ("8월 29일까지", "c0") in answer and ("02-000-0000", "c1") in answer  # 문장마다 다른 색
    assert all("가나대학" not in text for text, _ in answer)  # 근거에 있어도 질문을 되풀이한 말은 칠하지 않음
    assert all("출처" not in text for text, _ in answer)
    evidence = painted(blocks[1], marks["blocks"][1])
    assert ("8월 29일까지", "c0") in evidence and ("02-000-0000", "c1") in evidence
    assert marks["blocks"][2] == []


def test_highlight_marks_sentence_missing_from_evidence_but_not_refusal():
    blocks = {1: "휴학 신청 기간은 8월 18일부터 8월 29일까지이다."}
    target = "제공된 문서에서는 확인할 수 없습니다. 자세한 내용은 학과 홈페이지 공지를 보세요.\n[출처 1]"
    marks = review.highlight(target, "복학 언제 해?", blocks)
    assert painted(target, marks["target"]) == [("자세한 내용은 학과 홈페이지 공지를 보세요.", "miss")]


def test_highlight_skips_generic_endings_and_falls_back_to_restated_words():
    blocks = {1: "어학 장학금 대상: OPIc IM 등급, TOEIC 700점. 학생지원팀에 신청할 수 있습니다."}
    target = "OPIc IM 등급이면 어학 장학금을 받을 수 있습니다.\n[출처 1]"
    marks = review.highlight(target, "OPIc IM 등급이면 어학 장학금 받을 수 있어?", blocks)
    answer = painted(target, marks["target"])
    assert ("OPIc IM 등급", "c0") in answer  # 새 글이 없는 '네' 답은 되풀이한 글이라도 칠한다
    assert all("있습니다" not in text for text, _ in answer)  # 근거에 있어도 말끝만인 글은 칠하지 않음


def test_highlight_underlines_question_words_when_target_only_refuses():
    blocks = {1: "가나대학 기숙사 신청은 생활관 홈페이지에서 한다."}
    question = "가나대학 기숙사 식비 얼마예요?"
    marks = review.highlight("제공된 문서에서는 확인할 수 없습니다.\n[출처 1]", question, blocks)
    assert painted(question, marks["question"]) == [("가나대학 기숙사", "qw")]
    assert painted(blocks[1], marks["blocks"][1]) == [("가나대학 기숙사", "qw")]
    answered = review.highlight("기숙사 신청은 생활관 홈페이지에서 합니다.", question, blocks)
    assert answered["question"] == []  # 답한 예시는 질문 낱말을 따로 표시하지 않는다
    crowded = {1: "가나대학 기숙사 안내\n" * 6}  # 근거 곳곳에 나오는 낱말은 주제일 뿐이라 표시하지 않는다
    assert review.highlight("제공된 문서에서는 확인할 수 없습니다.", question, crowded)["question"] == []


def test_highlight_splits_evidence_marks_at_line_breaks():
    blocks = {1: "휴학 신청 기간은\n8월 29일까지이다."}
    marks = review.highlight("휴학 신청 기간은 8월 29일까지입니다.", "휴학 언제까지?", blocks)
    assert painted(blocks[1], marks["blocks"][1]) == [("휴학 신청 기간은", "c0"), ("8월 29일까지", "c0")]


def test_merge_review_counts_disagreements(tmp_path):
    file = tmp_path / "판정기록.jsonl"
    file.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in [
        {"id": "a", "human": "통과", "memo": ""}, {"id": "b", "human": "탈락", "memo": "다른 해 값"},
        {"id": "c", "human": "통과", "memo": ""}]) + "\n", encoding="utf-8")
    human = review.read_record(file)
    records = [judged("a", "fact", "통과"), judged("b", "fact", "통과"), judged("c", "fact", "탈락")]
    result = review.agreement(records, human)
    assert result["differ"] == 2 and result["claude_pass_human_fail"] == 1 and result["next"] == "판정 지침을 고치고 새 30개"
    assert review.agreement(records[:2], {"a": human["a"], "b": {"human": "통과", "memo": ""}})["next"] == "나머지는 Claude 판정만"
    file.write_text(json.dumps({"id": "a", "human": "몰라"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        review.read_record(file)


def test_export_prefers_human_over_claude(tmp_path):
    batch = tmp_path / "r1"
    pipeline.write(batch, "plan", [{"id": "a", "kind": "fact", "user": "재학생", "style": "정중체", "chunks": []},
                                   {"id": "b", "kind": "fact", "user": "재학생", "style": "정중체", "chunks": []}], mode="w")
    pipeline.write(batch, "attached", [{"id": "a", "prompt": PROMPT}, {"id": "b", "prompt": PROMPT}])
    pipeline.write(batch, "targets", [{"id": "a", "target_ga": "답 가\n[출처 1]"}, {"id": "b", "target_ga": "답 나\n[출처 1]"}])
    pipeline.write(batch, "checked", [{"id": "a", "keep": {"ga": True}}, {"id": "b", "keep": {"ga": True}}], mode="w")
    pipeline.write(batch, "judged", [{"id": "a", "verdict": "통과"}, {"id": "b", "verdict": "통과"}])
    pipeline.write(batch, "human", [{"id": "b", "human": "탈락", "memo": "값 틀림"}])
    assert pipeline.verdicts(batch) == {"a": "통과", "b": "탈락"}
    assert pipeline.export(batch, tmp_path / "out.jsonl", verdicts=pipeline.verdicts(batch)) == 1


def test_pick_for_judge_keeps_kind_ratio():
    records = []
    for kind, count in (("fact", 20), ("table", 2), ("refuse_guide", 20)):
        records += [{"id": f"{kind}-{n}", "kind": kind, "keep": {"ga": True}} for n in range(count)]
    records.append({"id": "dropped", "kind": "fact", "keep": {"ga": False}})
    records.append({"id": "done", "kind": "fact", "keep": {"ga": True}, "verdict": "통과"})
    chosen = pipeline.pick_for_judge(records, 40)
    kinds = [record["kind"] for record in chosen]
    # 40개 비율로 사실 7 · 표 7 · 거절 + 확인처 8 — 표가 2개뿐이라 남은 자리는 다른 종류로 채움
    assert len(chosen) == 40 and kinds.count("table") == 2 and "dropped" not in kinds and "done" not in [r["id"] for r in chosen]
    small = [record["kind"] for record in pipeline.pick_for_judge(records, 10)]
    # 10개 비율로 사실 2 · 표 2 · 거절 + 확인처 2, 없는 종류의 자리(4)는 계획 순서대로 남은 예시(사실)로 채움
    assert len(small) == 10 and small.count("table") == 2 and small.count("refuse_guide") == 2 and small.count("fact") == 6


def test_judge_prompt_accepts_real_user_phrasing():
    # 질문 말투를 실제 사용자처럼 바꿨으므로(ADR-0044) 판정 지침도 검색어형·줄임말을 탈락시키지 않는다
    assert "검색어처럼 낱말만" in judge.PROMPT and "공식 명칭" in judge.PROMPT
