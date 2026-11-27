"""서버 프롬프트를 그대로 쓰는 학습 데이터(#275): 정답 청크 지정과 순위 기록, 근거에 못 든 이유, 거절로 두기, 프롬프트 대조,
표 블록 프롬프트에서의 값 검사, 표본 화면의 기준 날짜. 가나대학 합성 데이터로.
"""

import json

import pytest

from corpus.cli import main
from corpus.trainset import checks, gold, pipeline, prompts, review, verify
from corpus.trainset.plan import KINDS

from test_trainset import PROMPT, FakeSession

RUNTIME = {"prompt_template_version": 1, "default_top_k": 8, "llm_model": "ax40light:q4km", "num_ctx": 12288,
           "num_predict": 512}
QUESTION = "가나대학 휴학 언제까지 신청해?"
HINT = "8월 18일부터 8월 29일까지"
# 답 근거가 없는 근거(정답 청크가 근거에 못 든 실제 검색)
NO_ANSWER = PROMPT.replace("휴학 신청 기간은 8월 18일부터 8월 29일까지이다. 문의는 학사지원팀 02-000-0000.",
                           "휴학은 학기마다 신청한다. 문의는 학사지원팀 02-000-0000.")


def retrieval(*entries):
    """후보별 단계 순위(서버 eval_trace.retrieval 모양). entries는 (청크 id, 순위 융합 순위, 재순위 순위, 블록)."""
    return [{"chunk_id": chunk_id, "retrieval_methods": ["vector"] if fused else [], "vector_rank": fused,
             "fused_rank": fused, "rerank_rank": rerank, "final_rank": fused, "block": block}
            for chunk_id, fused, rerank, block in entries]


def trace(prompt=PROMPT, ranks=(), final=(), table_block=None, pinned=None):
    stages = {"final": [{"chunk_id": chunk_id, "document_id": chunk_id.split("_")[0], "ledger_id": f"gana/{chunk_id}",
                         "chunk_index": int(chunk_id.split("_")[1])} for chunk_id in final]}
    if table_block:
        stages["table_block"] = table_block
    return {"answer_path": "llm", "prompt": prompt, "stages": stages, "runtime": RUNTIME,
            "retrieval": list(ranks), "pinned": pinned}


def batch(tmp_path, kind="fact", chunks=None, hint=HINT):
    folder = tmp_path / "b"
    chunks = [{"id": "7_2", "chunk_index": 2, "content": "휴학 안내", "table_numbers": []}] if chunks is None else chunks
    pipeline.write(folder, "plan", [{"id": "b-0001", "kind": kind, "ledger_id": "gana/7_2", "document_id": 7,
                                     "chunks": chunks}], mode="w")
    pipeline.write(folder, "questions", [{"id": "b-0001", "question": QUESTION, "hint": hint, "possible": True}])
    return folder


class Server(FakeSession):
    """/debug/rag-trace는 실행 설정만, /query는 answer(body)가 만든 평가 기록을 돌려준다."""

    def __init__(self, answer):
        super().__init__(lambda body: {"answer": "학습 전 답", "eval_trace": answer(body)})

    def post(self, url, json=None, timeout=None):
        if url.endswith("/debug/rag-trace"):
            self.sent.append((url, json))
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"runtime": RUNTIME}})()
        return super().post(url, json, timeout)


# 정답 청크 지정과 자리
def test_pick_mode_and_ranks_are_deterministic_and_in_range():
    records = [{"id": f"b-{n:04d}", "chunks": [{"id": f"{n}_1"}, {"id": f"{n}_2"}]} for n in range(400)]
    modes = [gold.pick_mode(record, 0.3, 7, answerable=True) for record in records]
    assert 0.22 < modes.count(gold.PINNED) / len(modes) < 0.38
    assert modes == [gold.pick_mode(record, 0.3, 7, answerable=True) for record in records]  # 다시 돌려도 같다
    assert gold.pick_mode(records[0], 1.0, 7, answerable=False) == gold.REAL  # 거절 종류는 지정하지 않는다
    assert gold.pick_mode({"id": "x", "chunks": []}, 1.0, 7, answerable=True) == gold.REAL  # 정답 청크가 없으면 실제 검색
    assert all(gold.pick_mode(record, 0.0, 7, answerable=True) == gold.REAL for record in records)  # 기본 0이면 모두 실제 검색
    ranks = [pin["rank"] for record in records for pin in gold.pinned_chunks(record, 8, 7)]
    assert set(ranks) == set(range(1, 9))  # 첫째에 몰리지 않고 1~8 모두 나온다
    assert all(len({pin["rank"] for pin in gold.pinned_chunks(record, 8, 7)}) == 2 for record in records)  # 겹치지 않음


def test_run_attach_pins_gold_chunk_with_server_top_k_and_records_it(tmp_path):
    folder = batch(tmp_path)
    session = Server(lambda body: trace(ranks=retrieval(("9_0", 1, None, 1), ("7_2", None, None, 5)), final=["9_0", "7_2"],
                                        pinned=[{"chunk_id": "7_2", "rank": 5, "block": 5}]))
    assert pipeline.run_attach(folder, session, "http://ai", pinned_share=1.0, seed=1, today="2026-10-31",
                               log=lambda line: None) == {"attached": 1}
    urls = [url for url, _ in session.sent]
    assert urls == ["http://ai/debug/rag-trace", "http://ai/query"]  # 근거 수를 서버에서 한 번 읽는다
    body = session.sent[1][1]
    assert body["pinned_chunks"] == gold.pinned_chunks(pipeline.merged(folder)[0], 8, 1)
    assert body["as_of"] == "2026-10-31" and "top_k" not in body
    attached = pipeline.read(folder, "attached")["b-0001"]
    assert attached["gold"]["mode"] == gold.PINNED and attached["gold"]["in_evidence"] is True
    assert attached["gold"]["chunks"][0]["block"] == 5
    assert attached["request"] == {k: v for k, v in body.items() if k != "include_eval_trace"}
    assert attached["runtime"]["prompt_template_version"] == 1


def test_real_retrieval_records_gold_block(tmp_path):
    folder = batch(tmp_path)
    session = Server(lambda body: trace(ranks=retrieval(("7_2", 2, None, 2)), final=["9_0", "7_2"]))
    pipeline.run_attach(folder, session, "http://ai", log=lambda line: None)
    found = pipeline.read(folder, "attached")["b-0001"]["gold"]
    assert found["mode"] == gold.REAL and found["in_evidence"] and found["chunks"][0]["block"] == 2
    assert [url for url, _ in session.sent] == ["http://ai/query"]  # 지정하지 않으면 실행 설정을 따로 묻지 않는다


# 근거에 못 든 이유
ATTACHED = {"considered": 8, "dropped_chunk_ids": ["5_4", "5_6"],
            "limit_dropped_chunk_ids": ["6_0"], "limit_dropped_merged_chunk_ids": ["5_6"],
            "table_blocks": [{"block": 1, "chunk_id": "5_3", "document_id": "5", "table_numbers": [1], "table_block": True}],
            "retrieval": retrieval(("1_0", 12, None, None), ("2_0", 5, 11, None), ("3_0", 15, 9, None), ("5_3", 1, None, 1),
                                   ("5_4", 3, None, None), ("6_0", 4, None, None), ("5_6", 6, None, None))}


@pytest.mark.parametrize("chunk, document_id, expected", [
    ({"id": "9_9"}, 9, {"in_evidence": False, "reason": gold.NOT_CANDIDATE, "same_table": None}),  # 어느 검색기도 못 찾음
    ({"id": "1_0"}, 1, {"in_evidence": False, "reason": gold.FUSION, "fused_rank": 12}),  # 순위 융합에서 8위 밖
    ({"id": "2_0"}, 2, {"in_evidence": False, "reason": gold.RERANK, "fused_rank": 5, "rerank_rank": 11}),  # 재순위가 밀어냄
    ({"id": "3_0"}, 3, {"in_evidence": False, "reason": gold.FUSION, "rerank_rank": 9}),  # 융합에서 이미 밖
    ({"id": "5_9", "table_numbers": [1]}, 5, {"in_evidence": False, "reason": gold.NOT_CANDIDATE, "same_table": True}),
    ({"id": "5_9", "table_numbers": [2]}, 5, {"in_evidence": False, "same_table": False}),  # 다른 표
    ({"id": "5_4", "table_numbers": [1]}, 5, {"in_evidence": True, "merged": True, "block": 1}),  # 같은 표 블록에 합쳐짐
    ({"id": "5_3", "table_numbers": [1]}, 5, {"in_evidence": True, "block": 1}),
    # 근거 수 안에 들었지만 프롬프트 길이 상한 때문에 서버가 그 블록을 뺐다(재순위나 융합 탓이 아니다)
    ({"id": "6_0"}, 6, {"in_evidence": False, "reason": gold.LIMIT, "fused_rank": 4}),
    # 합쳐진 블록이 상한 때문에 빠졌다: 합쳐진 경우보다 먼저 본다
    ({"id": "5_6", "table_numbers": [2]}, 5, {"in_evidence": False, "reason": gold.LIMIT, "merged": None}),
])
def test_chunk_status_reasons(chunk, document_id, expected):
    status = gold.chunk_status(chunk, document_id, ATTACHED)
    assert {key: status.get(key) for key in expected} == expected


def gold_batch(tmp_path):
    """이유별 수를 세는 가나대학 묶음: 실제 검색 답 예시 여섯(근거에 듦 하나, 못 듦 다섯), 거절 + 확인처 하나, 지정 예시 둘."""
    folder = tmp_path / "g"
    rows = [("g1", "fact", "7_2", []), ("g2", "table", "5_9", [1]), ("g3", "procedure", "2_0", []),
            ("g4", "fact", "1_0", []), ("g5", "multi", "5_3", [1]), ("g6", "refuse_guide", "8_0", []),
            ("g7", "fact", "7_2", []), ("g8", "table", "5_3", [1]), ("g9", "fact", "6_0", [])]
    pipeline.write(folder, "plan", [{"id": i, "kind": kind, "document_id": int(chunk.split("_")[0]),
                                     "chunks": [{"id": chunk, "table_numbers": numbers}]
                                     + ([{"id": "9_9", "table_numbers": []}] if i == "g5" else [])}
                                    for i, kind, chunk, numbers in rows], mode="w")
    attached = {**ATTACHED, "retrieval": ATTACHED["retrieval"] + retrieval(("7_2", 2, None, 2))}
    records = []
    for i, kind, _, _ in rows:
        record = next(r for r in pipeline.merged(folder) if r["id"] == i)
        mode = gold.PINNED if i in ("g7", "g8") else gold.REAL
        # g7은 블록 하나만 남아도 상한을 넘어 서버가 끝 줄을 자른 지정 예시
        found = gold.gold_record(record, {**attached, "truncated_lines": 40} if i == "g7" else attached, mode)
        if i == "g4":
            found["refusal_target"] = True
        records.append({"id": i, "gold": found})
    pipeline.write(folder, "attached", records)
    return folder


def test_count_reasons_counts_only_real_retrieval_answer_examples(tmp_path):
    counts = gold.count_reasons(pipeline.merged(gold_batch(tmp_path)), lambda kind: KINDS[kind].answerable)
    assert counts["실제 검색 예시"] == 6 and counts["정답 청크가 근거에 듦"] == 1 and counts["정답 청크가 근거에 못 듦"] == 5
    # 못 든 청크: g2 5_9(후보 없음, 같은 표 듦), g3 2_0(재순위), g4 1_0(융합), g5의 9_9(후보 없음), g9 6_0(길이 상한).
    # g5의 5_3은 듦
    assert counts["못 든 청크의 이유"] == {gold.NOT_CANDIDATE: 2, gold.FUSION: 1, gold.RERANK: 1, gold.LIMIT: 1}
    assert counts["못 든 청크 중 같은 표의 다른 조각이 근거에 듦"] == {"예": 1, "아니오": 0, "표 번호 모름": 4}
    assert counts["거절로 둔 예시"] == 1 and counts["지정 예시"] == 2 and counts["끝 줄을 자른 예시"] == 1
    assert counts["지정 예시의 정답 블록"] == {1: 1, 2: 1}


def test_gold_report_command_prints_counts(tmp_path, capsys):
    folder = gold_batch(tmp_path / "train")
    assert main(["--root", str(tmp_path / "corpus"), "trainset", "gold-report", "--batches", folder.name]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["못 든 청크의 이유"][gold.NOT_CANDIDATE] == 2 and out["못 든 청크의 이유"][gold.LIMIT] == 1
    assert out["끝 줄을 자른 예시"] == 1


# 정답 청크가 근거에 못 든 실제 검색 예시는 거절로 둔다
def test_missing_gold_without_hint_in_prompt_becomes_refusal_target(tmp_path):
    folder = batch(tmp_path)
    session = Server(lambda body: trace(prompt=NO_ANSWER, ranks=retrieval(("9_0", 1, None, 1)), final=["9_0"]))
    pipeline.run_attach(folder, session, "http://ai", log=lambda line: None)
    record = pipeline.merged(folder)[0]
    assert record["gold"]["refusal_target"] is True and record["gold"]["chunks"][0]["reason"] == gold.NOT_CANDIDATE
    assert record["refusal"]["contact_blocks"] == []  # 재료 문서 블록이 근거에 없다
    # 목표 답 지시문: 답 근거를 주지 않고 답없음 예시로 쓰게 한다
    asked = []
    drafter = FakeSession(lambda body: asked.append(body["prompt"]) or {"response": prompts.REFUSAL})
    result = pipeline.draft_target(record, drafter, "http://o", "gemma")
    assert "[질문을 만든 글에서 답이 되는 부분]" not in asked[0] and "[답없음 예시]" in asked[0]
    checked = checks.check({**record, **result})
    assert checked["kind"] == "refuse_guide" and checked["checks"]["거절함"]["ok"] and not checked["drop"]
    # 거절하지 않은 목표 답은 떨어진다
    wrong = checks.check({**record, **result, "target_ga": "8월 29일까지입니다.\n[출처 1]"})
    assert wrong["drop"]


def test_gold_dropped_by_prompt_limit_is_recorded_from_server_and_becomes_refusal_target(tmp_path):
    # 정답 청크 7_2는 재순위 뒤 2위였지만 프롬프트가 길이 상한을 넘어 서버가 블록 2를 뺐다. 블록 1은 끝 줄이 잘렸다
    folder = batch(tmp_path)
    table_block = {"blocks": [{"block": 1, "chunk_id": "9_0", "table_numbers": [], "table_block": False}],
                   "dropped_chunk_ids": [], "limit_dropped_chunk_ids": ["7_2"], "limit_dropped_merged_chunk_ids": ["7_3"],
                   "truncated_lines": 31}
    session = Server(lambda body: trace(prompt=NO_ANSWER, ranks=retrieval(("9_0", 1, None, 1), ("7_2", 2, None, None)),
                                        final=["9_0", "7_2"], table_block=table_block))
    pipeline.run_attach(folder, session, "http://ai", log=lambda line: None)
    attached = pipeline.read(folder, "attached")["b-0001"]
    assert attached["limit_dropped_chunk_ids"] == ["7_2"] and attached["limit_dropped_merged_chunk_ids"] == ["7_3"]
    assert attached["truncated_lines"] == 31
    record = pipeline.merged(folder)[0]
    assert record["gold"]["chunks"][0]["reason"] == gold.LIMIT and record["gold"]["truncated_lines"] == 31
    assert record["gold"]["refusal_target"] is True
    # 표 블록 기록이 없으면(표 블록이 꺼진 서버) 빈 값이다
    plain = Server(lambda body: trace(ranks=retrieval(("7_2", 1, None, 1)), final=["7_2"]))
    pipeline.run_attach(batch(tmp_path / "plain"), plain, "http://ai", log=lambda line: None)
    attached = pipeline.read(tmp_path / "plain" / "b", "attached")["b-0001"]
    assert attached["limit_dropped_chunk_ids"] == [] and attached["limit_dropped_merged_chunk_ids"] == []
    assert attached["truncated_lines"] is None


def test_missing_gold_with_hint_in_another_block_stays_an_answer(tmp_path):
    folder = batch(tmp_path)
    session = Server(lambda body: trace(ranks=retrieval(("9_0", 1, None, 1)), final=["9_0"]))  # 답 근거가 [출처 1]에 있음
    pipeline.run_attach(folder, session, "http://ai", log=lambda line: None)
    record = pipeline.merged(folder)[0]
    assert record["gold"]["in_evidence"] is False and "refusal_target" not in record["gold"] and "refusal" not in record


# 답 있는 예시의 값 검사(표 블록 프롬프트)
TABLE_PROMPT = PROMPT.replace("[사용자 질문]", """[출처 3]
문서: 2027학년도 가나대학 신입생 모집요강.pdf
학년도: 2027
내용:
# Ⅰ. 2027학년도 모집인원
표:
|계열|모집단위|모집 정원|수시1차|
|---|---|---|---|
|공학|항공기계공학과|110|50|
표 아래 주석:
※ 동일 모집시기 내 1개 전형에만 지원 가능함

[사용자 질문]""")


def test_answer_values_must_be_in_the_table_block_prompt():
    base = {"id": "t1", "kind": "table", "question": "가나대 항공기계 수시1차 몇 명 뽑아?", "hint": "|항공기계공학과|110|50|",
            "prompt": TABLE_PROMPT, "document_id": 31, "chunks": [{"chunk_index": 3}],
            "retrieved": [{"document_id": "31", "chunk_index": 3}]}
    good = checks.check({**base, "target_ga": "항공기계공학과 수시 1차 모집 인원은 50명입니다.\n[출처 3]"})
    assert good["checks"]["근거 대조"]["ok"]
    made_up = checks.check({**base, "target_ga": "항공기계공학과 수시 1차 모집 인원은 55명입니다.\n[출처 3]"})
    assert not made_up["checks"]["근거 대조"]["ok"] and "55명" in made_up["checks"]["근거 대조"]["why"]


# 학습 파일의 프롬프트 대조
def training_file(tmp_path, prompt=PROMPT):
    line = {"id": "b-0001", "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": "답"}],
            "meta": {"prompt_template_version": 1,
                     "request": {"question": QUESTION, "system_prompt": None, "as_of": "2026-10-31",
                                 "pinned_chunks": [{"chunk_id": "7_2", "rank": 3}]}}}
    path = tmp_path / "round-ga.jsonl"
    path.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_verify_prompts_passes_when_server_gives_the_same_prompt(tmp_path):
    session = Server(lambda body: trace())
    result = verify.verify_file(training_file(tmp_path), session, "http://ai", log=lambda line: None)
    assert verify.ok(result) and result["same"] == 1
    body = session.sent[0][1]  # 근거를 붙일 때와 같은 요청
    assert body["as_of"] == "2026-10-31" and body["pinned_chunks"] == [{"chunk_id": "7_2", "rank": 3}]


def test_verify_prompts_catches_a_one_letter_change(tmp_path):
    changed = PROMPT.replace("8월 29일까지", "8월 28일까지", 1)
    assert sum(a != b for a, b in zip(changed, PROMPT)) == 1
    result = verify.verify_file(training_file(tmp_path, changed), Server(lambda body: trace()), "http://ai",
                                log=lambda line: None)
    assert not verify.ok(result) and result["same"] == 0
    difference = result["different"][0]
    assert difference["at"] == PROMPT.index("8월 29일까지") + len("8월 2") and difference["same_template_version"] is True


def test_verify_prompts_command_fails_without_request_record(tmp_path, capsys):
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps({"id": "o1", "messages": [{"role": "user", "content": PROMPT}], "meta": {}}) + "\n",
                    encoding="utf-8")
    assert main(["--root", str(tmp_path), "trainset", "verify-prompts", str(path), "--ai-url", "http://127.0.0.1:9"]) == 1
    assert json.loads(capsys.readouterr().out)["no_request"] == ["o1"]


# 문맥 길이와 답 상한은 서버 실행 설정에서만
def test_probe_fails_without_server_runtime(tmp_path):
    folder = tmp_path / "p"
    pipeline.write(folder, "plan", [{"id": "p1", "kind": "fact"}], mode="w")
    pipeline.write(folder, "attached", [{"id": "p1", "prompt": PROMPT,
                                         "runtime": {"prompt_template_version": 1, "llm_model": "ax40light:q4km"}}])
    session = FakeSession({"response": "답"})
    assert pipeline.run_probe(folder, session, "http://o", samples=1, log=lambda line: None) == {"error": 1}
    assert session.sent == []  # 도구 쪽 기본값(12288, 512)으로 부르지 않는다


# 표본 화면의 기준 날짜(#273 뒤 날짜 줄)
def test_review_page_reads_only_the_date_from_the_first_line():
    dated = "오늘: 2026-10-31 (2026학년도 2학기)\n지금 모집 중인 입시: 2027학년도\n" + PROMPT
    record = {"id": "r1", "kind": "fact", "user": "재학생", "prompt": dated, "question": QUESTION,
              "target_ga": "8월 29일까지입니다.\n[출처 1]"}
    html = review.page([record], "b")
    assert '"today": "2026-10-31"' in html  # 괄호의 학년도·학기까지 날짜로 읽지 않는다
    assert '"today": ""' in review.page([{**record, "prompt": PROMPT}], "b")  # 날짜 줄이 없으면 비움
