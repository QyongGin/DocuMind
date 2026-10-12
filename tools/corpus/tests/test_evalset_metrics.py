"""실행 채점과 지표(M1 11번): 실패 위치, 출처 정확도, 답 잘림, 사람 판정 재사용, 신뢰구간, 테스트셋 봉인."""

import json

import pytest
from evalset_data import item, unanswerable_item

from corpus.evalset import metrics, runner, schema

FEE = "gana/page/fee"  # 전형료 문항(item)의 근거 문서
OTHER = "gana/page/leave"


def trace(retrieved=(), final=(), context="", done="stop", path="llm"):
    """평가용 기록(eval_trace). retrieved·final은 (대장 ID, 글) 목록."""
    entry = lambda pair: {"ledger_id": pair[0], "text": pair[1]}  # noqa: E731
    return {"answer_path": path, "context": context, "prompt": "규칙\n" + context,
            "stages": {"vector": [entry(pair) for pair in retrieved], "final": [entry(pair) for pair in final]},
            "generation": {"done_reason": done}}


def record(answer, eval_trace, **extra):
    return {"id": "ev-0001", "answer": answer, "eval_trace": eval_trace, "elapsed": 1.0, **extra}


FOUND = [(FEE, "전형료 30,000원")]


@pytest.mark.parametrize("answer, eval_trace, location", [
    ("전형료는 30,000원입니다.", trace(FOUND, FOUND, "전형료 30,000원"), "통과"),
    ("문서에서 확인할 수 없습니다.", trace(), "검색 실패"),
    ("문서에서 확인할 수 없습니다.", trace(FOUND, [(OTHER, "휴학 안내")], "휴학 안내"), "후보 탈락"),
    ("문서에서 확인할 수 없습니다.", trace(FOUND, FOUND, "다른 글"), "문맥 탈락"),
    ("문서에서 확인할 수 없습니다.", trace(FOUND, FOUND, "전형료 30,000원"), "생성 실패"),
    # 필수 사실이 허용 근거가 아닌 문서에만 있으면 검색은 실패다(다른 문서의 같은 숫자에 기대지 않음)
    ("문서에서 확인할 수 없습니다.", trace([(OTHER, "전형료 30,000원")], [(OTHER, "전형료 30,000원")], "전형료 30,000원"),
     "검색 실패"),
])
def test_failure_location_follows_stages(answer, eval_trace, location):
    row = metrics.score_record(item("ev-0001"), record(answer, eval_trace), {})
    assert row["location"] == location


def test_correct_answer_without_retrieval_is_memorized():
    """검색 단계에 근거가 없는데 맞으면 '외운 답 의심'. 숫자 답이면 프롬프트에 없는 숫자라 먼저 애매(지어낸 숫자)가 된다."""
    office = item("ev-0001", facts=[{"name": "부서", "values": ["재무팀"]}], forbidden=[])
    assert metrics.score_record(office, record("재무팀에서 합니다.", trace()), {})["location"] == "외운 답 의심"
    number = metrics.score_record(item("ev-0001"), record("전형료는 30,000원입니다.", trace()), {})
    assert (number["label"], number["invented"], number["location"]) == ("애매", ["30000원"], "검색 실패")


def test_also_documents_count_as_evidence():
    key = item("ev-0001", also=[OTHER])
    found = [(OTHER, "30,000원")]
    row = metrics.score_record(key, record("30,000원입니다.", trace(found, found, "30,000원")), {})
    assert row["location"] == "통과" and row["source_any"] is True


def test_source_accuracy_truncation_and_invented_number():
    eval_trace = trace(FOUND, [(FEE, "전형료 30,000원"), (OTHER, "휴학"), (OTHER, "휴학 2")], "전형료 30,000원", done="length")
    row = metrics.score_record(item("ev-0001"), record("전형료 30,000원에 실기 15,000원을 더 냅니다.", eval_trace), {})
    assert (row["source_any"], row["source_share"], row["truncated"]) == (True, 0.333, True)
    assert row["invented"] == ["15000원"] and row["label"] == "애매"  # 프롬프트에 없는 숫자


def test_unanswerable_items_get_no_stage_location():
    key = unanswerable_item("ev-0009")
    good = metrics.score_record(key, record("문서에서 확인할 수 없습니다.", trace()), {})
    bad = metrics.score_record(key, record("2028학년도 정원은 40명입니다.", trace()), {})
    assert (good["label"], good["location"]) == ("맞음", None)
    assert (bad["label"], bad["location"]) == ("틀림", "지어낸 답")


def test_human_judgment_is_reused_only_for_same_revision_and_answer(tmp_path):
    answer = "원서 접수 때 냅니다"  # 규칙으로는 애매
    key = item("ev-0001")
    judgments = tmp_path / "judgments.jsonl"
    judgments.write_text(json.dumps({"key": metrics.judgment_key(key, answer), "label": "모름", "reason": "값 없음"},
                                    ensure_ascii=False) + "\n", encoding="utf-8")
    loaded = metrics.load_judgments(judgments)
    reused = metrics.score_record(key, record(answer, trace()), loaded)
    assert (reused["label"], reused["rule_label"], reused["judged"]) == ("모름", "애매", True)
    revised = metrics.score_record(item("ev-0001", rev=2), record(answer, trace()), loaded)
    assert (revised["label"], revised["judged"]) == ("애매", False)
    spaced = metrics.score_record(key, record("원서  접수 때  냅니다", trace()), loaded)
    assert spaced["judged"]  # 띄어쓰기만 다른 답은 같은 답


def test_wilson_interval():
    assert metrics.wilson(60, 100) == pytest.approx([0.502, 0.6906], abs=1e-3)
    assert metrics.wilson(0, 30)[0] == 0 and metrics.wilson(0, 0) is None


def test_aggregate_rates():
    rows = [metrics.score_record(item("ev-0001"), record("30,000원", trace(FOUND, FOUND, "전형료 30,000원")), {}),
            metrics.score_record(item("ev-0002"), record("문서에서 확인할 수 없습니다.", trace()), {}),
            metrics.score_record(item("ev-0003"), record("25,000원", trace()), {}),
            metrics.score_record(unanswerable_item("ev-0009"), record("문서에서 확인할 수 없습니다.", trace()), {}),
            metrics.score_record(item("ev-0004"), None, {})]
    result = metrics.aggregate(rows)
    assert (result["scored"], result["not_run"]) == (4, 1)
    assert (result["accuracy"]["k"], result["accuracy"]["n"]) == (1, 3)
    assert (result["over_refusal"]["k"], result["hallucination"]["k"], result["hallucination"]["n"]) == (1, 1, 4)
    assert result["unanswerable_refusal"]["k"] == 1 and result["locations"]["검색 실패"] == 2


def write_run(run_dir, evalset_items, answers):
    run_dir.mkdir()
    manifest = {"evalset_sha256": schema.fingerprint(evalset_items), "evalset_version": "v2", "index": "gana",
                "top_k": 5, "system_prompt_sha256": runner.sha256(""), "git_commit": None, "runtime": None}
    (run_dir / runner.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / runner.ANSWERS).write_text("".join(json.dumps(answer, ensure_ascii=False) + "\n" for answer in answers),
                                          encoding="utf-8")


def test_score_run_seals_test_items(tmp_path):
    secret = "가나대 테스트셋 비밀 질문이에요?"
    evalset_items = [item("ev-0001", part="dev"), item("ev-0002", question=secret, part="test"),
                     item("ev-0003", question="쉬운 질문", set="쉬운", tags=["FAQ 제목", "글 근거"], part="dev")]
    path = tmp_path / "evalset.jsonl"
    schema.save(path, evalset_items)
    answers = [dict(record("30,000원", trace(FOUND, FOUND, "전형료 30,000원")), id=entry["id"]) for entry in evalset_items]
    write_run(tmp_path / "run", evalset_items, answers)
    result = metrics.score_run(path, tmp_path / "run")
    assert set(result["groups"]) == {"본/dev", "본/test", "쉬운/dev"}
    dev_ids = [json.loads(line)["id"] for line in (tmp_path / "run" / metrics.DEV_RESULTS).read_text().splitlines()]
    assert dev_ids == ["ev-0001", "ev-0003"]
    sealed = (tmp_path / "run" / metrics.TEST_RESULTS).read_text(encoding="utf-8")
    assert secret in sealed
    shown = "\n".join(metrics.summary_lines(result)) + json.dumps(result, ensure_ascii=False)
    assert secret not in shown and "ev-0002" not in shown  # 화면·지표 파일에는 테스트셋 문항이 없다
    assert result["groups"]["본/test"]["accuracy"]["k"] == 1


def test_score_run_refuses_other_evalset_version(tmp_path):
    path = tmp_path / "evalset.jsonl"
    schema.save(path, [item("ev-0001", part="dev")])
    write_run(tmp_path / "run", [item("ev-0001", part="test")], [])
    with pytest.raises(ValueError, match="지문"):
        metrics.score_run(path, tmp_path / "run")


def test_judgment_can_mark_stalled_generation_as_empty(tmp_path):
    """한두 글자에서 멈춘 답(문맥이 차서 1토큰 생성)은 사람이 '빈 답'으로 판정할 수 있다. 다른 값은 거부."""
    key, answer = item("ev-0001"), "인"
    judgments = tmp_path / "judgments.jsonl"
    judgments.write_text(json.dumps({"key": metrics.judgment_key(key, answer), "label": "빈 답"}, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    row = metrics.score_record(key, record(answer, trace(done="length")), metrics.load_judgments(judgments))
    assert (row["label"], row["truncated"]) == ("빈 답", True)
    judgments.write_text(json.dumps({"key": "x", "label": "애매"}, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        metrics.load_judgments(judgments)
