"""4회차 선호 쌍(ADR-0053): 학습한 모델 답 받기·종류 비율·답 가르기·Claude 답 판정·쌍 고르기. 가나대학 합성 데이터로."""

import json
import subprocess

import pytest

from corpus.cli import main
from corpus.trainset import judge, pairs, pipeline, prompts
from corpus.trainset.plan import parse_kinds, scale
from test_trainset import PROMPT, FakeSession, record

MODEL = "ax40light-r3:q4km"
REFUSAL = prompts.REFUSAL
# 목표 답의 값: 8월 18일·8월 29일(연락처 02-000-0000은 값으로 세지 않는다)
TARGET = record()["target_ga"]
GUIDE = f"{REFUSAL} 휴학 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"
RIGHT = "8월 29일까지 신청하면 됩니다.\n[출처 1]"


def test_probe_with_model_keeps_answers_apart_from_base_model(tmp_path):
    batch = tmp_path / "r4"
    pipeline.write(batch, "plan", [{"id": "r4-0001", "kind": "fact"}], mode="w")
    pipeline.write(batch, "attached", [{"id": "r4-0001", "prompt": PROMPT,
                                        "runtime": {"llm_model": "ax40light:q4km", "num_ctx": 12288, "num_predict": 512}}])
    session = FakeSession({"response": RIGHT})
    counts = pipeline.run_probe(batch, session, "http://o", samples=4, log=lambda line: None, model=MODEL)
    assert counts == {"probed": 1} and {body["model"] for _, body in session.sent} == {MODEL}
    assert {body["options"]["temperature"] for _, body in session.sent} == {0.7}  # 운영 문맥 길이에 표본 추출 온도
    assert (batch / "probes-ax40light-r3-q4km.jsonl").exists() and not (batch / "probes.jsonl").exists()
    assert "ax_samples" not in pipeline.merged(batch)[0]  # 학습 전 A.X의 아는 정도(ADR-0042)에 섞이지 않는다
    assert pipeline.read(batch, pipeline.probe_step(MODEL))["r4-0001"]["probe_generation"]["model"] == MODEL
    assert pipeline.run_probe(batch, session, "http://o", samples=4, log=lambda line: None, model=MODEL) == {}


def test_kinds_ratio_scales_to_round4_shares():
    kinds = parse_kinds("fact=10,procedure=9,table=40,multi=6,partial=5,refuse_guide=22,refuse_offtopic=8")
    quotas = scale(kinds, 600)
    assert quotas["table"] == 240 and quotas["refuse_guide"] + quotas["refuse_offtopic"] == 180 and sum(quotas.values()) == 600
    assert scale(parse_kinds("refuse_guide=3,refuse_offtopic=1"), 40) == {"refuse_guide": 30, "refuse_offtopic": 10}
    for bad in ("tabel=40", "table=-1", "table=many", "table=0"):
        with pytest.raises(ValueError):
            parse_kinds(bad)


def test_plan_rejects_unknown_kind_on_command_line(tmp_path):
    with pytest.raises(SystemExit):
        main(["--root", str(tmp_path / "corpus"), "trainset", "plan", "--batch", "r4", "--kinds", "tabel=40"])


@pytest.mark.parametrize("kind, target, answer, outcome", [
    ("fact", TARGET, RIGHT, "correct"),
    ("fact", TARGET, REFUSAL, "over_refusal"),
    ("fact", TARGET, GUIDE, "over_refusal"),  # 거절 뒤에 확인처만 — 연락처는 답한 값이 아니다
    ("fact", TARGET, f"{REFUSAL} 다만 휴학은 8월 29일까지 신청합니다.\n[출처 1]", "refusal_preamble"),
    ("fact", TARGET, "9월 5일까지입니다.\n[출처 1]", "wrong_value"),  # 목표 답의 값이 없고 근거에도 없는 값
    ("fact", TARGET, "1,200,000원입니다.\n[출처 2]", "undecided"),  # 근거의 다른 값(다른 칸·행일 수 있음)은 Claude가 본다
    ("fact", TARGET, "학사지원팀에 물어보세요.", "undecided"),
    ("procedure", "가나포털 학적 메뉴에서 신청합니다.\n[출처 1]", f"{REFUSAL}\n\n[출처 1]", "over_refusal"),
    ("procedure", "가나포털 학적 메뉴에서 신청합니다.\n[출처 1]", f"{REFUSAL} 가나포털에서 신청하세요.", "undecided"),
    ("partial", f"휴학 신청은 8월 29일까지입니다. 휴학 비용은 {REFUSAL}\n[출처 1]",
     "8월 29일까지입니다. 비용은 나와 있지 않습니다.", "correct"),
    ("partial", f"휴학 신청은 8월 29일까지입니다. 휴학 비용은 {REFUSAL}\n[출처 1]", RIGHT, "undecided"),  # 없는 쪽을 밝혔나
    ("refuse_guide", GUIDE, REFUSAL, "correct"),
    ("refuse_guide", GUIDE, "휴학 수수료는 10,000원입니다.", "fabrication"),
    ("refuse_guide", GUIDE, "휴학 수수료는 나와 있지 않습니다. 학사지원팀(02-000-0000)에 문의하세요.", "correct"),
    ("refuse_guide", GUIDE, "학사지원팀이 담당합니다.", "undecided"),
])
def test_classify_answer_by_rules(kind, target, answer, outcome):
    assert pairs.classify(record(kind=kind, target_ga=target), answer) == outcome


@pytest.mark.parametrize("kind, answer, verdict, outcome", [
    ("fact", RIGHT, "맞음", "correct"), ("fact", RIGHT, "틀림", "wrong_value"), ("fact", REFUSAL, "과잉 거절", "over_refusal"),
    ("fact", f"{REFUSAL} 가나포털에서 신청하세요.", "일부", "refusal_preamble"), ("fact", RIGHT, "일부", "incomplete"),
    ("fact", REFUSAL, "거절 맞음", "conflict"),  # 판정을 통과한 목표 답과 어긋남
    ("refuse_guide", REFUSAL, "거절 맞음", "correct"), ("refuse_guide", RIGHT, "틀림", "fabrication"),
    ("refuse_guide", RIGHT, "근거 있음", "conflict"), ("refuse_guide", RIGHT, "맞음", "conflict"),
])
def test_claude_verdict_becomes_pair_type(kind, answer, verdict, outcome):
    assert pairs.from_verdict(record(kind=kind), answer, verdict) == outcome


def write_batch(folder, rows, verdicts=(), prompt=PROMPT):
    """rows: (예시 번호, 종류, 질문, 목표 답, 3회차 답 넷[, 최종 판정])."""
    pipeline.write(folder, "plan", [{"id": row[0], "kind": row[1], "group_id": f"공지:{row[0]}", "ledger_id": f"www/{row[0]}"}
                                    for row in rows], mode="w")
    pipeline.write(folder, "questions", [{"id": row[0], "question": row[2], "possible": True, "user_actual": "재학생"}
                                         for row in rows])
    pipeline.write(folder, "attached", [{"id": row[0], "prompt": prompt} for row in rows])
    pipeline.write(folder, "targets", [{"id": row[0], "target_ga": row[3]} for row in rows])
    pipeline.write(folder, "checked", [{"id": row[0], "kind": row[1], "kind_planned": row[1], "keep": {"ga": True}}
                                       for row in rows], mode="w")
    pipeline.write(folder, "judged", [{"id": row[0], "verdict": row[5] if len(row) > 5 else "통과"} for row in rows])
    pipeline.write(folder, pipeline.probe_step(MODEL), [{"id": row[0], "ax_samples": row[4], "probe_generation": {"model": MODEL}}
                                                        for row in rows])
    pipeline.write(folder, pairs.verdict_step(MODEL), [{"id": answer_id, "verdict": verdict} for answer_id, verdict in verdicts])
    return folder


def two_batches(tmp_path, verdicts=(("a6#1", "틀림"), ("a7#1", "근거 있음"))):
    first = write_batch(tmp_path / "train" / "a", [
        ("a1", "fact", "가나대학 휴학 신청 마감일이 언제예요?", TARGET, [RIGHT, REFUSAL, "9월 5일까지입니다.", RIGHT]),
        ("a2", "fact", "휴학하려면 몇 월 며칠까지 내야 해?", TARGET, [REFUSAL, REFUSAL, GUIDE, RIGHT]),
        ("a3", "fact", "가나대 휴학계 기한", TARGET, [RIGHT] * 4),
        ("a4", "refuse_guide", "휴학 수수료 얼마야?", GUIDE, ["휴학 수수료는 10,000원입니다.", REFUSAL, REFUSAL, GUIDE]),
        ("a5", "fact", "휴학 신청 언제 끝나나요?", TARGET, [f"{REFUSAL} 다만 휴학은 8월 29일까지 신청합니다.\n[출처 1]", RIGHT, RIGHT, RIGHT]),
        ("a6", "fact", "2학기 휴학 접수 기간 알려 줘", TARGET, ["학사지원팀에 물어보세요.", RIGHT, RIGHT, RIGHT]),
        ("a7", "refuse_guide", "휴학생 기숙사 환불 규정은?", GUIDE, ["학사지원팀이 담당합니다.", REFUSAL, REFUSAL, REFUSAL]),
        ("a8", "fact", "휴학 신청 장소가 어디예요?", TARGET, [REFUSAL] * 4, "탈락"),
    ], verdicts)
    second = write_batch(tmp_path / "train" / "b", [
        ("b1", "fact", "가나대학 휴학 신청 마감일이 언제예요?", TARGET, [REFUSAL] * 4)])  # a1과 같은 질문
    return [first, second]


def test_build_one_pair_per_question_with_priority_and_balance(tmp_path):
    batches = two_batches(tmp_path)
    lines, manifest = pairs.build(batches, MODEL)
    # a1(과잉 거절 1번)과 a2(과잉 거절 3번) 중 지어내기 쌍 수(a4 하나)만큼, 더 자주 거절한 a2만 남는다
    assert [line["id"] for line in lines] == ["a2", "a4", "a5", "a6"]
    assert manifest["types"] == {"over_refusal": 1, "fabrication": 1, "refusal_preamble": 1, "wrong_value": 1}
    assert manifest["dropped_over_refusal"] == 1 and manifest["judged_by"] == {"규칙": 3, "Claude": 1}
    # a3은 4번 모두 맞힘, a7은 Claude가 근거에 답이 있다고 봐 문항째 뺌, a8은 목표 답이 탈락, b1은 a1과 질문이 겹침
    assert manifest["items"] == {"candidates": 7, "no_bad_answer": 1, "conflict": 1}
    assert manifest["legacy_prompts"] == 0 and manifest["old_refusal_left"] == 0
    a2 = lines[0]
    assert a2["prompt"] == [{"role": "user", "content": PROMPT}] and a2["chosen"] == [{"role": "assistant", "content": TARGET}]
    assert a2["rejected"] == [{"role": "assistant", "content": REFUSAL}]
    assert (a2["meta"]["pair"], a2["meta"]["sample"], a2["meta"]["type_samples"]) == ("over_refusal", 1, 3)
    assert a2["meta"]["group_id"] == "공지:a2" and a2["meta"]["model"] == MODEL
    # 한 문항에 과잉 거절과 틀린 값이 함께 있으면 순위가 앞선 과잉 거절을 고른다(a1의 2번째 답)
    a1 = pairs.candidates(batches[0], MODEL)[0]
    assert [result["outcome"] for result in pairs.assess(a1, a1["answers"], {})] == [
        "correct", "over_refusal", "wrong_value", "correct"]
    assert pairs.pair_line(a1, pairs.assess(a1, a1["answers"], {})[1], [], MODEL)["meta"]["sample"] == 2


def test_pending_lists_only_unjudged_undecided_answers(tmp_path):
    batches = two_batches(tmp_path, verdicts=())
    todo = pairs.pending(batches[0], MODEL)
    assert [item["id"] for item in todo] == ["a6#1", "a7#1"]
    assert todo[1]["종류"] == "답 없음" and todo[1]["목표 답"] == GUIDE and todo[1]["챗봇 답"] == "학사지원팀이 담당합니다."
    assert todo[0]["검색 근거"].startswith("[검색 근거]") and "[사용자 질문]" not in todo[0]["검색 근거"]
    pipeline.write(batches[0], pairs.verdict_step(MODEL), [{"id": "a6#1", "verdict": "틀림"}])
    assert [item["id"] for item in pairs.pending(batches[0], MODEL)] == ["a7#1"]


def test_run_answers_uses_answer_guide_and_its_verdicts(tmp_path):
    seen = []

    def runner(command, cwd):
        if command[:2] == ["claude", "--version"]:
            return subprocess.CompletedProcess(command, 0, "9.9.9 (Claude Code)", "")
        items = json.loads((cwd / "examples.json").read_text(encoding="utf-8"))
        seen.append(command)
        verdict = "통과" if any(item["id"].startswith("x") for item in items) else "과잉 거절"
        body = json.dumps({"verdicts": [{"id": item["id"], "verdict": verdict, "reason": "근거 1에 답"} for item in items]},
                          ensure_ascii=False)
        return subprocess.CompletedProcess(command, 0, json.dumps({"is_error": False, "result": body}), "")

    items = [judge.answer_example(record(id=f"{prefix}-1"), 1, REFUSAL) for prefix in ("r4", "x")]
    results, failed = judge.run_answers(items, tmp_path / "work", "claude-x", runner=runner, jobs=1, per_packet=1)
    assert [(result["id"], result["verdict"]) for result in results] == [("r4-1#1", "과잉 거절")]
    assert [name for name, _ in failed] == ["packet-002"]  # 답 판정 값이 아닌 '통과'는 받지 않는다
    assert judge.ANSWER_PROMPT in seen[0] and results[0]["judge"].endswith(f"판정 지침 {judge.ANSWER_GUIDE_VERSION}")


def test_pairs_command_writes_only_when_every_answer_is_judged(tmp_path, capsys):
    two_batches(tmp_path, verdicts=(("a6#1", "틀림"),))  # a7의 애매한 답은 아직 판정 전
    command = ["--root", str(tmp_path / "corpus"), "trainset", "pairs", "--batches", "a,b", "--probe-model", MODEL,
               "--out-dir", str(tmp_path / "round4")]
    assert main(command) == 1 and not (tmp_path / "round4").exists()
    assert "judge-probes" in capsys.readouterr().out
    pipeline.write(tmp_path / "train" / "a", pairs.verdict_step(MODEL), [{"id": "a7#1", "verdict": "거절 맞음"}])
    assert main(command) == 0
    manifest = json.loads((tmp_path / "round4" / "manifest.json").read_text(encoding="utf-8"))
    lines = (tmp_path / "round4" / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
    assert manifest["size"] == len(lines) == 4 and manifest["ids"] == [json.loads(line)["id"] for line in lines]


def test_pairs_refuse_prompts_with_legacy_rules(tmp_path):
    legacy = PROMPT.replace("[검색 근거]", f"{prompts.LEGACY_REFUSAL_RULES[0][0]}\n\n[검색 근거]")
    batch = write_batch(tmp_path / "train" / "old", [("o1", "refuse_guide", "휴학 수수료?", GUIDE,
                                                      ["휴학 수수료는 10,000원입니다.", REFUSAL, REFUSAL, REFUSAL])], prompt=legacy)
    lines, manifest = pairs.build([batch], MODEL)
    # 3회차 답은 지난 규칙으로 받은 답이라, 입력만 지금 규칙으로 바꾸면 쌍의 입력과 답이 어긋난다
    assert manifest["legacy_prompts"] == 1 and lines[0]["prompt"][0]["content"] != legacy


def copy_setup(tmp_path):
    """원본 묶음 s(답 있는 예시 셋)와 그 답없음 사본 묶음 c. s1은 3회차가 다 맞힘, s2는 한 번 과잉 거절, s3은 사본 근거에서도
    답이 나와 사본 종류가 바뀜. c1은 3회차가 사본에서 맞게 거절, c2는 사본에서 지어냄."""
    source = write_batch(tmp_path / "train" / "s", [
        ("s1", "fact", "휴학 언제까지 신청해?", TARGET, [RIGHT] * 4),
        ("s2", "fact", "가나대 휴학 마감 며칠이야?", TARGET, [REFUSAL, RIGHT, RIGHT, RIGHT]),
        ("s3", "fact", "휴학 신청 끝나는 날 알려 줘", TARGET, [RIGHT] * 4),
    ])
    pipeline.write(source, "questions", [{"id": item_id, "question": question, "hint": "8월 18일부터 8월 29일까지",
                                          "possible": True, "user_actual": "재학생"}
                                         for item_id, question in (("s1", "휴학 언제까지 신청해?"),
                                                                   ("s2", "가나대 휴학 마감 며칠이야?"),
                                                                   ("s3", "휴학 신청 끝나는 날 알려 줘"))])
    copies = write_batch(tmp_path / "train" / "c", [
        ("c1", "refuse_guide", "휴학 언제까지 신청해?", GUIDE, [GUIDE, REFUSAL, GUIDE, REFUSAL]),
        ("c2", "refuse_guide", "가나대 휴학 마감 며칠이야?", GUIDE, ["9월 5일까지입니다.", GUIDE, REFUSAL, REFUSAL]),
        ("c3", "fact", "휴학 신청 끝나는 날 알려 줘", TARGET, [RIGHT] * 4),
    ])
    pipeline.write(copies, "plan", [{"id": f"c{n}", "kind": "refuse_guide", "group_id": f"공지:s{n}", "ledger_id": f"www/s{n}",
                                     "source_id": f"s{n}"} for n in (1, 2, 3)])
    return source, copies


def test_no_answer_copies_take_question_and_hint_of_passed_answerable_items(tmp_path):
    source, _ = copy_setup(tmp_path)
    pipeline.write(source, "judged", [{"id": "s3", "verdict": "탈락"}])  # 목표 답이 탈락한 예시는 원본이 될 수 없다
    plans, questions = pairs.no_answer_copies([source, *two_batches(tmp_path)], "r4-c")
    assert [(plan["id"], plan["source_id"], plan["kind"]) for plan in plans] == [
        ("r4-c-0001", "s1", "refuse_guide"), ("r4-c-0002", "s2", "refuse_guide")]  # a·b 묶음은 답 근거가 없어 못 뺀다
    assert plans[0]["group_id"] == "공지:s1" and plans[0]["batch"] == "r4-c"  # 원본과 같은 문서 묶음(검증 몫에서 갈라지지 않게)
    assert questions[0] == {"id": "r4-c-0001", "question": "휴학 언제까지 신청해?", "hint": "8월 18일부터 8월 29일까지",
                            "user_actual": "재학생", "possible": True, "drafter": {"copied_from": "s1"}}


def test_copies_add_answer_and_refusal_pairs_for_the_same_question(tmp_path):
    source, copies = copy_setup(tmp_path)
    lines, manifest = pairs.build([source], MODEL, [copies])
    by_id = {(line["id"], line["meta"]["pair"]): line for line in lines}
    # s2는 3회차가 실제로 과잉 거절해 그 답으로 쌍이 있고, 사본 쌍만 더한다. s1은 사본에서 3회차가 한 거절로 원본 쌍을 짓는다
    assert sorted(by_id) == [("c1", "fabrication"), ("c2", "fabrication"), ("s1", "over_refusal"), ("s2", "over_refusal")]
    c1, s1, c2 = by_id["c1", "fabrication"], by_id["s1", "over_refusal"], by_id["c2", "fabrication"]
    assert c1["chosen"][0]["content"] == GUIDE and c1["rejected"][0]["content"] == RIGHT  # 원본에서 맞힌 답 = 사본에선 근거 없음
    assert (c1["meta"]["made_from"], c1["meta"]["source_id"]) == ("원본 답", "s1")
    assert s1["chosen"][0]["content"] == TARGET and s1["rejected"][0]["content"] == GUIDE  # 사본에서 한 거절(첫 거절 답)
    assert (s1["meta"]["made_from"], s1["meta"]["sample"]) == ("사본 거절", 1)
    assert (c2["rejected"][0]["content"], c2["meta"]["made_from"]) == ("9월 5일까지입니다.", "3회차 답")  # 실제로 지어낸 답이 먼저
    assert by_id["s2", "over_refusal"]["meta"]["made_from"] == "3회차 답"
    assert manifest["types"] == {"over_refusal": 2, "fabrication": 2} and manifest["dropped_over_refusal"] == 0
    assert manifest["copies"] == {"copies": 3, "copy_has_answer": 1, "twins": 2}  # c3은 사본 근거에서도 답이 나왔다
    assert manifest["made_from"] == {"3회차 답": 2, "원본 답": 1, "사본 거절": 1} and manifest["copy_batches"] == ["c"]


def test_pairs_command_waits_for_copy_answer_verdicts(tmp_path, capsys):
    source, copies = copy_setup(tmp_path)
    pipeline.write(copies, pipeline.probe_step(MODEL), [{"id": "c1", "ax_samples": ["학사지원팀이 담당합니다."] * 4}])
    command = ["--root", str(tmp_path / "corpus"), "trainset", "pairs", "--batches", "s", "--copies", "c",
               "--probe-model", MODEL, "--out-dir", str(tmp_path / "round4")]
    assert main(command) == 1 and not (tmp_path / "round4").exists()  # 사본의 애매한 답이 판정 전
    assert "judge-probes" in capsys.readouterr().out


def test_no_answer_copies_command_writes_plan_and_questions_once(tmp_path, capsys):
    copy_setup(tmp_path)
    command = ["--root", str(tmp_path / "corpus"), "trainset", "no-answer-copies", "--batch", "r4-c", "--from-batches", "s"]
    assert main(command) == 0 and "사본 3개" in capsys.readouterr().out
    merged = pipeline.merged(tmp_path / "train" / "r4-c")
    assert [(record["kind"], record["question"]) for record in merged][0] == ("refuse_guide", "휴학 언제까지 신청해?")
    assert main(command) == 1  # 이미 계획이 있으면 덮어쓰지 않는다
