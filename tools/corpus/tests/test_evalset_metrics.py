"""실행 채점과 지표(M1 11번): 실패 위치, 출처 정확도, 답 잘림, 사람 판정 재사용, 신뢰구간, 테스트셋 봉인."""

import hashlib
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


def test_judgment_key_keeps_bold_marks():
    """판정 열쇠는 채점 정규화가 굵게 기호를 지우게 된 뒤에도 그 전과 같다(옛 판정이 그대로 붙는다)."""
    key = item("ev-0001")
    assert metrics.judgment_key(key, "**30,000원**") == "ev-0001@1#" + hashlib.sha256("**30000원**".encode()).hexdigest()[:16]
    assert metrics.judgment_key(key, "**30,000원**") != metrics.judgment_key(key, "30,000원")


def test_rule_correct_answer_from_priority_path_goes_to_judgment():
    """모델을 거치지 않은 우선 경로 답은 규칙이 맞음이어도 판정으로 보낸다(ADR-0028). 판정이 있으면 그 판정을 쓴다."""
    listed = "표 근거 기준 답변입니다.\n- 면접고사료: 20,000원\n- 전형료: 30,000원"
    eval_trace = trace(FOUND, FOUND, "전형료 30,000원 면접고사료 20,000원", path="priority_table_fact")
    row = metrics.score_record(item("ev-0001"), record(listed, eval_trace), {})
    assert (row["rule_label"], row["label"], row["doubt"]) == ("맞음", "애매", "우선 경로")
    assert metrics.aggregate([row])["doubted"] == 1
    key = metrics.judgment_key(item("ev-0001"), listed)
    judged = metrics.score_record(item("ev-0001"), record(listed, eval_trace), {key: {"key": key, "label": "일부"}})
    assert (judged["label"], judged["judged"], judged["doubt"]) == ("일부", True, "우선 경로")


@pytest.mark.parametrize("answer, shape, expected", [
    # 값 문항에 정답 값과 단위가 같은 다른 값이 함께 있으면 판정으로(다른 값을 결론으로 내세웠을 수 있다)
    ("면접학과는 50,000원이지만 질문은 원서비라 30,000원입니다.", "값", ("애매", "다른 값")),
    # 단위가 다른 숫자(연도)는 보지 않는다
    ("2027학년도 전형료는 30,000원입니다.", "값", ("맞음", None)),
    # 값 문항만 본다
    ("전형료는 30,000원이고 면접학과는 50,000원입니다.", "설명", ("맞음", None)),
])
def test_value_item_with_another_value_of_same_unit_goes_to_judgment(answer, shape, expected):
    context = "전형료 30,000원 면접학과 50,000원 2027학년도"
    row = metrics.score_record(item("ev-0001", shape=shape), record(answer, trace(FOUND, FOUND, context)), {})
    assert (row["label"], row["doubt"]) == expected


def test_wrong_answers_are_split_by_kind(tmp_path):
    """'틀림'의 종류: 판정 태그가 있으면 그것, 규칙이 정한 틀림은 답의 숫자가 근거 글에 있으면 다른문서사실, 없으면 지어냄."""
    key = item("ev-0001")
    last_year = metrics.score_record(key, record("전형료는 25,000원입니다.", trace(context="2026학년도 전형료 25,000원")), {})
    invented = metrics.score_record(key, record("전형료는 25,000원입니다.", trace(context="전형료 30,000원")), {})
    assert (last_year["label"], last_year["wrong_kind"]) == ("틀림", "다른문서사실")  # 근거 글의 지난해 값을 댐
    assert (invented["label"], invented["wrong_kind"]) == ("틀림", "지어냄")
    guessed = metrics.score_record(unanswerable_item("ev-0002"), record("40명입니다.", trace(context="정원 표 없음")), {})
    assert (guessed["label"], guessed["wrong_kind"]) == ("틀림", "지어냄")
    answer = "휴학은 포털에서 신청합니다."  # 규칙이 못 정해 판정으로 간 답에 판정 태그가 붙은 경우
    judged = {metrics.judgment_key(key, answer): {"key": "", "label": "틀림", "tags": ["v3 재채점", "엉뚱한근거"]}}
    tagged = metrics.score_record(key, record(answer, trace(context="휴학 안내")), judged)
    assert (tagged["label"], tagged["wrong_kind"]) == ("틀림", "엉뚱한근거")
    right = metrics.score_record(key, record("전형료는 30,000원입니다.", trace(FOUND, FOUND, "전형료 30,000원")), {})
    assert right["wrong_kind"] is None
    result = metrics.aggregate([last_year, invented, guessed, tagged, right])
    assert result["wrong_kinds"] == {"엉뚱한근거": 1, "다른문서사실": 1, "지어냄": 2}
    assert "  틀림 종류 엉뚱한근거 1 · 다른문서사실 1 · 지어냄 2" in metrics.summary_lines({"groups": {"본/dev": {
        **result, "locations": {}}}})


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


def test_rescore_with_new_version_matches_by_id_and_skips_changed_questions(tmp_path):
    """평가셋 판을 올린 뒤 옛 실행을 새 판으로 다시 채점: 고친 정답으로 채점하고, 질문이 바뀐 문항은 빼고,
    결과는 따로 둔 폴더에 쓰고, 어느 판으로 채점했는지 남긴다."""
    old_items = [item("ev-0001", part="dev"), item("ev-0002", question="가나대 원서 접수비 얼마예요?", part="dev")]
    answers = [{**record("전형료는 삼만 원입니다.", trace(FOUND, FOUND, "전형료 30,000원")), "id": entry["id"],
                "question": entry["question"]} for entry in old_items]
    write_run(tmp_path / "run", old_items, answers)
    new_items = [item("ev-0001", rev=2, part="dev", facts=[{"name": "전형료", "values": ["30,000원", "3만 원", "삼만 원"]}]),
                 item("ev-0002", question="가나대 원서 낼 때 내는 돈 얼마예요?", part="dev")]
    path = tmp_path / "evalset.jsonl"
    schema.save(path, new_items)
    (tmp_path / "frozen_v3.txt").write_text(f"version: v3\nevalset_sha256: {schema.fingerprint(new_items)}\n",
                                            encoding="utf-8")
    with pytest.raises(ValueError, match="지문"):
        metrics.score_run(path, tmp_path / "run")
    with pytest.raises(ValueError, match="--out"):
        metrics.score_run(path, tmp_path / "run", rescore=True)

    result = metrics.score_run(path, tmp_path / "run", out_dir=tmp_path / "v3", rescore=True)
    rows = {row["id"]: row for row in map(json.loads, (tmp_path / "v3" / metrics.DEV_RESULTS).read_text().splitlines())}
    assert (rows["ev-0001"]["label"], rows["ev-0001"]["rev"]) == ("맞음", 2)  # 고친 정답(허용 표기 '삼만 원')으로 채점
    assert rows["ev-0002"]["status"] == "질문 바뀜" and "label" not in rows["ev-0002"]
    group = result["groups"]["본/dev"]
    assert (group["scored"], group["question_changed"], group["accuracy"]["n"]) == (1, 1, 1)
    assert result["scored_with"] == {"evalset_version": "v3", "evalset_sha256": schema.fingerprint(new_items),
                                     "same_as_run": False, "run_dir": str(tmp_path / "run")}
    assert result["manifest"]["evalset_version"] == "v2"  # 실행 때 판은 그대로 남긴다
    assert not (tmp_path / "run" / metrics.METRICS).exists()  # 실행 폴더는 건드리지 않는다
    assert "질문 바뀜 1" in "\n".join(metrics.summary_lines(result))


def test_frozen_version_is_none_for_unfrozen_file(tmp_path):
    path = tmp_path / "evalset.jsonl"
    schema.save(path, [item("ev-0001")])
    (tmp_path / "frozen_v2.txt").write_text("version: v2\nevalset_sha256: 다른지문\n", encoding="utf-8")
    assert metrics.frozen_version(path, schema.fingerprint([item("ev-0001")])) is None


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
