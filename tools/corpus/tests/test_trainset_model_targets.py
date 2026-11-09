"""목표 답이 떨어진 문항에서 학습한 모델의 답을 목표 답 후보로 쓴다(ADR-0056). 가나대학 합성 데이터로."""

from corpus.cli import main
from corpus.trainset import judge, model_targets, pairs, pipeline, prompts
from test_trainset import record

MODEL = "ax40light-r4:q4km"
REFUSAL = prompts.REFUSAL
GOOD = record()["target_ga"]  # 자동 검사를 통과하는 목표 답(8월 18일~8월 29일, 학사지원팀)
RIGHT = "휴학은 8월 29일까지 신청하면 됩니다. 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"
RIGHT_SHORT = "8월 29일까지입니다.\n[출처 1]"
OUTSIDE = "9월 5일까지입니다.\n[출처 1]"  # 근거에 없는 날짜 — 자동 검사에서 떨어진다
QUESTIONS = {"g1": "휴학 언제까지 신청해?", "g2": "가나대 휴학 신청 마감일 알려줘", "g3": "휴학계 내는 기간이 언제부터야",
             "g4": "휴학 신청 기간", "g5": "2학기 휴학 접수 마감", "g6": "휴학하려면 며칠까지 내야 해요"}


def make_batch(folder, rows):
    """rows: (번호, Gemma 목표 답, Claude 판정(None이면 판정 전), 판정 종류, 4회차 답들[, 답 근거])."""
    pipeline.write(folder, "plan", [{**{key: value for key, value in record(id=row[0]).items()
                                         if key in ("id", "kind", "document_id", "chunks")}, "user": "재학생"}
                                    for row in rows], mode="w")
    pipeline.write(folder, "questions", [{"id": row[0], "question": QUESTIONS[row[0]], "possible": True,
                                          "hint": row[5] if len(row) > 5 else record()["hint"], "user_actual": "재학생"}
                                         for row in rows])
    pipeline.write(folder, "attached", [{"id": row[0], "prompt": record()["prompt"], "retrieved": record()["retrieved"]}
                                        for row in rows])
    pipeline.write(folder, "targets", [{"id": row[0], "target_ga": row[1], "target_generation": {"model": "gemma4:12b-it-qat"}}
                                       for row in rows])
    pipeline.run_checks(folder)
    pipeline.write(folder, "judged", [{"id": row[0], "verdict": row[2], "category": row[3]} for row in rows if row[2]])
    pipeline.write(folder, pipeline.probe_step(MODEL), [{"id": row[0], "ax_samples": row[4]} for row in rows])
    return folder


def rows():
    return [
        ("g1", OUTSIDE, None, "", [OUTSIDE, OUTSIDE, RIGHT, RIGHT]),  # 목표 답이 자동 검사(근거 대조)에서 떨어짐
        ("g2", GOOD, "탈락", "값 틀림", [RIGHT_SHORT, RIGHT_SHORT, OUTSIDE, RIGHT]),  # 판정에서 떨어짐
        ("g3", GOOD, "통과", "", [RIGHT] * 4),  # 목표 답이 통과 — 대상 아님
        ("g4", GOOD, "탈락", "질문 어색", [RIGHT] * 4),  # 질문 탓 — 대상 아님
        ("g5", OUTSIDE, None, "", [RIGHT] * 4, "9월 1일부터 9월 5일까지"),  # 답 근거가 프롬프트에 없음(지워진 정답) — 근거 탓
        ("g6", GOOD, "탈락", "안내 빠짐", [OUTSIDE] * 4),  # 대상이지만 자동 검사를 통과한 후보가 없음
    ]


def test_candidates_are_model_answers_of_answer_side_failures_that_pass_checks(tmp_path):
    batch = make_batch(tmp_path / "a", rows())
    found = model_targets.candidates(batch, MODEL)
    # g1: 근거에 없는 날짜(1번)는 자동 검사에서 빠지고 2·4번은 앞 답과 글이 같다. g2: 2번은 1번과 같고 3번은 근거에 없다
    assert [candidate["id"] for candidate in found] == ["g1#3", "g2#1", "g2#4"]
    assert found[0]["target_ga"] == RIGHT and found[0]["item"] == "g1" and found[0]["sample"] == 3
    assert found[0]["result"]["ga"]["drop"] is False
    example = judge.example(found[0])  # 판정자에게는 후보만 목표 답으로 보인다
    assert example["id"] == "g1#3" and example["목표 답"] == RIGHT and OUTSIDE not in str(example)


def test_promote_puts_first_passing_answer_in_target_and_pairs_use_it(tmp_path):
    batch = make_batch(tmp_path / "train" / "a", rows())
    pipeline.write(batch, model_targets.verdict_step(MODEL), [
        {"id": "g1#3", "verdict": "통과", "category": ""}, {"id": "g2#1", "verdict": "탈락", "category": "안내 빠짐"}])
    assert [candidate["id"] for candidate in model_targets.pending(batch, MODEL)] == ["g2#4"]
    counts = model_targets.promote(batch, MODEL)
    assert counts == {"대상": 3, "올림": 1, "판정 전": 1, "자동 검사를 통과한 후보 없음": 1}
    g1 = next(item for item in pipeline.merged(batch) if item["id"] == "g1")
    assert g1["target_ga"] == RIGHT and g1["target_generation"] == {"from": MODEL, "sample": 3}
    assert pipeline.final_verdict(g1) == "통과" and g1["keep"]["ga"] is True  # 자동 검사를 다시 매겼다
    # 다시 돌려도 같은 문항을 또 올리지 않는다
    assert model_targets.promote(batch, MODEL)["대상"] == 2 and model_targets.candidates(batch, MODEL)[0]["item"] == "g2"
    lines, manifest = pairs.build([batch], MODEL)
    g1_line = next(line for line in lines if line["id"] == "g1")
    assert g1_line["chosen"][0]["content"] == RIGHT and g1_line["rejected"][0]["content"] == OUTSIDE
    assert (g1_line["meta"]["pair"], g1_line["meta"]["chosen_from"]) == ("wrong_value", MODEL)
    assert manifest["chosen_from"] == {MODEL: 1}
    found = next(item for item in pairs.candidates(batch, MODEL) if item["id"] == "g1")
    results = pairs.assess(found, found["answers"], {})
    assert [(result["outcome"], result["by"]) for result in results][2:] == [("correct", "규칙")] * 2  # 올린 그 답


def test_items_whose_candidates_all_fail_are_counted(tmp_path):
    batch = make_batch(tmp_path / "a", rows())
    pipeline.write(batch, model_targets.verdict_step(MODEL), [
        {"id": answer_id, "verdict": "탈락", "category": "값 틀림"} for answer_id in ("g1#3", "g2#1", "g2#4")])
    assert model_targets.promote(batch, MODEL) == {"대상": 3, "통과한 후보 없음": 2, "자동 검사를 통과한 후보 없음": 1}
    assert all(not (item.get("target_generation") or {}).get("from") for item in pipeline.merged(batch))


def test_gemma_target_pairs_record_their_source(tmp_path):
    batch = make_batch(tmp_path / "train" / "a", [("g3", GOOD, "통과", "", [OUTSIDE, RIGHT, RIGHT, RIGHT])])
    lines, manifest = pairs.build([batch], MODEL)
    assert lines[0]["meta"]["chosen_from"] == "gemma4:12b-it-qat" and manifest["chosen_from"] == {"gemma4:12b-it-qat": 1}


def test_judge_command_with_as_target_judges_then_promotes(tmp_path, monkeypatch, capsys):
    make_batch(tmp_path / "train" / "a", rows())
    seen = []

    def fake_run(records, work, model, jobs=2):
        seen.extend(record["id"] for record in records)
        return [{"id": record["id"], "verdict": "통과" if record["id"] == "g2#4" else "탈락", "category": ""}
                for record in records], []

    monkeypatch.setattr(judge, "run", fake_run)
    command = ["--root", str(tmp_path / "corpus"), "trainset", "judge", "--batch", "a", "--as-target", MODEL,
               "--work", str(tmp_path / "work")]
    assert main(command) == 0
    assert seen == ["g1#3", "g2#1", "g2#4"]
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last == "대상 3 · 올림 1 · 통과한 후보 없음 1 · 자동 검사를 통과한 후보 없음 1 · 판정 전 0 · 실패한 작업 단위 0"
    g2 = next(item for item in pipeline.merged(tmp_path / "train" / "a") if item["id"] == "g2")
    assert g2["target_ga"] == RIGHT and g2["target_generation"]["sample"] == 4
    seen.clear()
    assert main(command) == 0 and seen == []  # 판정한 후보는 다시 판정하지 않는다
