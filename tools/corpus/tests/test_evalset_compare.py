"""두 실행의 짝 비교(ADR-0025): 정확 이항 검정, 같은 판 확인, 애매 거부, 짝 짓기, 테스트셋은 합계만."""

import json

import pytest
from evalset_data import item, unanswerable_item

from corpus.evalset import compare, metrics, runner, schema

FEE = "gana/page/fee"
RIGHT, REFUSE, WRONG = "전형료는 30,000원입니다.", "문서에서 확인할 수 없습니다.", "전형료는 25,000원입니다."


def trace():
    found = [{"ledger_id": FEE, "text": "전형료 30,000원"}]
    return {"answer_path": "llm", "context": "전형료 30,000원", "prompt": "규칙\n전형료 30,000원",
            "stages": {"vector": found, "final": found}, "generation": {"done_reason": "stop"}}


def scored_run(tmp_path, name, evalset_path, answers: dict[str, str | None]):
    """실행 폴더를 만들어 채점한다. 답이 None인 문항은 묻지 않은 것(미실행)."""
    items = schema.load(evalset_path)
    run_dir = tmp_path / name
    run_dir.mkdir()
    manifest = {"evalset_sha256": schema.fingerprint(items), "evalset_version": "v3", "index": "gana", "top_k": 5,
                "system_prompt_sha256": runner.sha256(""), "git_commit": None, "runtime": None}
    (run_dir / runner.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    lines = [json.dumps({"id": item_id, "question": next(entry["question"] for entry in items if entry["id"] == item_id),
                         "answer": answer, "eval_trace": trace(), "elapsed": 1.0}, ensure_ascii=False)
             for item_id, answer in answers.items() if answer is not None]
    (run_dir / runner.ANSWERS).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    metrics.score_run(evalset_path, run_dir)
    return run_dir


@pytest.fixture
def evalset_path(tmp_path):
    items = [item(f"ev-00{number:02d}", part="dev") for number in range(1, 9)]
    items += [unanswerable_item("ev-0009", part="dev"), item("ev-0010", part="test", question="가나대 비밀 질문이에요?"),
              item("ev-0011", part="dev", set="쉬운", tags=["FAQ 제목", "글 근거"])]
    path = tmp_path / "evalset.jsonl"
    schema.save(path, items)
    return path


@pytest.mark.parametrize("b, c, p", [(0, 0, 1.0), (6, 0, 0.03125), (0, 6, 0.03125), (3, 3, 1.0), (1, 9, 22 / 1024),
                                     (5, 0, 0.0625)])
def test_mcnemar_exact(b, c, p):
    assert compare.mcnemar_exact(b, c) == pytest.approx(p)


def test_compare_counts_only_discordant_items_and_names_better_run(tmp_path, evalset_path):
    """B만 맞힌 문항 6개, 둘 다 맞힌 문항 1개, 둘 다 거절 1개 → 정답률은 의미 있는 차이(B가 나음)."""
    base = {f"ev-00{number:02d}": REFUSE for number in range(1, 8)} | {"ev-0008": RIGHT, "ev-0009": REFUSE,
                                                                      "ev-0010": RIGHT, "ev-0011": RIGHT}
    better = base | {f"ev-00{number:02d}": RIGHT for number in range(1, 7)}
    result = compare.compare(evalset_path, scored_run(tmp_path, "a", evalset_path, base),
                             scored_run(tmp_path, "b", evalset_path, better))
    accuracy = result["sets"]["본"]["정답률"]
    assert (accuracy["n"], accuracy["a_yes"], accuracy["b_yes"], accuracy["only_a"], accuracy["only_b"]) == (8, 1, 7, 0, 6)
    assert accuracy["verdict"] == "의미 있는 차이" and accuracy["dev_only_b"] == [f"ev-00{n:02d}" for n in range(1, 7)]
    refusal = result["sets"]["본"]["과잉 거절률"]
    assert (refusal["only_a"], refusal["only_b"], refusal["verdict"]) == (6, 0, "의미 있는 차이")
    assert result["sets"]["본"]["답없음 거절"]["n"] == 1 and result["sets"]["쉬운"]["정답률"]["n"] == 1
    lines = "\n".join(compare.summary_lines(result))
    assert "정답률: A 12.5% (1/8) · B 87.5% (7/8)" in lines and "의미 있는 차이 → B가 나음" in lines
    assert "과잉 거절률(낮을수록 좋음)" in lines and lines.count("B가 나음") == 2
    assert lines.count("답없음 거절") == 1  # 쉬운 묶음에는 답없음 문항이 없어 그 줄을 내지 않는다
    assert "출처 정확도: A 100.0% (8/8) · B 100.0% (8/8) · A만 0 · B만 0 · p 1.0 · 같은 수준" in lines


def test_hallucination_lower_is_better(tmp_path, evalset_path):
    answers = {f"ev-00{number:02d}": RIGHT for number in range(1, 12)} | {"ev-0009": REFUSE}
    worse = answers | {f"ev-00{number:02d}": WRONG for number in range(1, 7)}
    result = compare.compare(evalset_path, scored_run(tmp_path, "a", evalset_path, answers),
                             scored_run(tmp_path, "b", evalset_path, worse))
    hallucination = result["sets"]["본"]["오답률"]
    assert (hallucination["only_b"], hallucination["lower_better"]) == (6, True)
    assert "오답률(낮을수록 좋음): A 0.0% (0/9) · B 66.7% (6/9) · A만 0 · B만 6 · p 0.0312 · 의미 있는 차이 → A가 나음" \
        in "\n".join(compare.summary_lines(result))


def test_test_items_only_with_part_and_never_by_id(tmp_path, evalset_path):
    """기본은 개발셋만. --part all이면 테스트셋도 합계에 들지만 문항 ID·질문은 어디에도 나오지 않는다."""
    base = {f"ev-00{number:02d}": RIGHT for number in range(1, 12)} | {"ev-0009": REFUSE, "ev-0010": REFUSE}
    other = base | {"ev-0010": RIGHT}
    dir_a, dir_b = scored_run(tmp_path, "a", evalset_path, base), scored_run(tmp_path, "b", evalset_path, other)
    assert compare.compare(evalset_path, dir_a, dir_b)["sets"]["본"]["정답률"]["n"] == 8
    result = compare.compare(evalset_path, dir_a, dir_b, part="all")
    accuracy = result["sets"]["본"]["정답률"]
    assert (accuracy["n"], accuracy["only_b"], accuracy["dev_only_b"]) == (9, 1, [])
    shown = json.dumps(result, ensure_ascii=False) + "\n".join(compare.summary_lines(result))
    assert "ev-0010" not in shown and "비밀 질문" not in shown


def test_unscored_items_are_left_out_of_pairs(tmp_path, evalset_path):
    answers = {f"ev-00{number:02d}": RIGHT for number in range(1, 12)} | {"ev-0009": REFUSE}
    result = compare.compare(evalset_path, scored_run(tmp_path, "a", evalset_path, answers),
                             scored_run(tmp_path, "b", evalset_path, answers | {"ev-0001": None}))
    assert result["unpaired"] == 1 and result["sets"]["본"]["정답률"]["n"] == 7


def test_refuses_results_scored_with_other_evalset(tmp_path, evalset_path):
    answers = {f"ev-00{number:02d}": RIGHT for number in range(1, 12)}
    dir_a = scored_run(tmp_path, "a", evalset_path, answers)
    dir_b = scored_run(tmp_path, "b", evalset_path, answers)
    changed = schema.load(evalset_path)
    changed[0]["rev"] = 2
    schema.save(evalset_path, changed)
    with pytest.raises(ValueError, match="같은 판"):
        compare.compare(evalset_path, dir_a, dir_b)


def test_refuses_results_with_open_ambiguous(tmp_path, evalset_path):
    answers = {f"ev-00{number:02d}": RIGHT for number in range(1, 12)} | {"ev-0009": REFUSE}
    dir_a = scored_run(tmp_path, "a", evalset_path, answers)
    dir_b = scored_run(tmp_path, "b", evalset_path, answers | {"ev-0001": "전형료는 문서에 나와 있어요."})  # 규칙이 못 정함
    with pytest.raises(ValueError, match="B에 애매가 1개"):
        compare.compare(evalset_path, dir_a, dir_b)
