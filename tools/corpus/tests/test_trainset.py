"""학습 예시 만들기(`trainset`): 묶음 고르기·지시문·호출·자동 검사·이어서 돌리기·학습 파일. 가나대학 합성 데이터로."""

import ast
import json
import random
from pathlib import Path

import pytest

from corpus.trainset import checks, clients, pipeline, prompts
from corpus.trainset.plan import (KINDS, ROUND1, boilerplate_lines, dataset_documents, draft_text, is_table_chunk,
                                  pick_chunks, plan, scale)

TABLE = "\n".join([
    "|구분|등록 기간|금액|",
    "|---|---|---|",
    "|신입생|2월 3일~2월 7일|1,200,000원|",
    "|재학생|2월 10일~2월 14일|1,150,000원|",
]) + "\n가나대학 등록금 납부 안내 표이며 문의는 재무팀이다." * 6
TEXT = ("가나대학 휴학 신청 기간은 8월 18일부터 8월 29일까지이다. 신청은 가나포털 학적 메뉴에서 하고, "
        "문의는 학사지원팀 02-000-0000으로 한다. 휴학 기간은 한 번에 1년까지 신청할 수 있다. ") * 2


def chunk(index, content=TEXT):
    return {"id": f"doc_{index}", "chunk_index": index, "content": content}


def documents():
    docs = []
    for number in range(12):
        topic = ("학사", "입시", "장학·등록금")[number % 3]
        docs.append({"doc_id": f"www/bbs/1/{number}", "document_id": 100 + number, "group_id": f"공지:{number // 2}",
                     "topic": topic, "format": ("html", "pdf")[number % 2], "title": f"가나대학 안내 {number}"})
    return docs


def fetch_chunks(document_id):
    # 짝수 문서 번호는 표가 있는 청크를, 모든 문서는 이웃한 글 청크 둘을 갖는다
    chunks = [chunk(0), chunk(1)]
    if document_id % 2 == 0:
        chunks.append(chunk(2, TABLE))
    return chunks


def test_scale_keeps_round1_ratio():
    assert scale(ROUND1, 200) == ROUND1
    assert scale(ROUND1, 40) == {"fact": 8, "procedure": 7, "table": 8, "multi": 5, "partial": 4,
                                 "refuse_guide": 6, "refuse_offtopic": 2}
    assert (ROUND1["refuse_guide"] + ROUND1["refuse_offtopic"]) / sum(ROUND1.values()) == 0.2  # 거절 20%(ADR-0043)
    assert sum(scale(ROUND1, 60).values()) == 60


def test_pick_chunks_by_kind():
    rng = random.Random(1)
    assert is_table_chunk(TABLE) and not is_table_chunk(TEXT)
    assert pick_chunks(KINDS["table"], [chunk(0), chunk(2, TABLE)], rng)[0]["chunk_index"] == 2
    assert pick_chunks(KINDS["table"], [chunk(0)], rng) is None
    pair = pick_chunks(KINDS["multi"], [chunk(0), chunk(3), chunk(4)], rng)
    assert [c["chunk_index"] for c in pair] == [3, 4]  # 이웃한 청크 둘
    assert pick_chunks(KINDS["multi"], [chunk(0), chunk(2)], rng) is None
    assert pick_chunks(KINDS["fact"], [chunk(0, "짧은 글")], rng) is None


def test_plan_one_example_per_group_and_kind_fits():
    quotas = {"fact": 2, "table": 2, "multi": 1, "refuse_offtopic": 1}
    items = plan(documents(), quotas, fetch_chunks, "r1", seed=7)
    assert sorted(item["kind"] for item in items) == ["fact", "fact", "multi", "refuse_offtopic", "table", "table"]
    groups = [item["group_id"] for item in items if item["group_id"]]
    assert len(groups) == len(set(groups)) == 5
    for item in items:
        if item["kind"] == "table":
            assert item["document_id"] % 2 == 0 and is_table_chunk(item["chunks"][0]["content"])
        if item["kind"] == "refuse_offtopic":
            assert item["chunks"] == [] and item["group_id"] is None
        if item["kind"] == "multi":
            assert len(item["chunks"]) == 2
    assert [item["user"] for item in items][:5] == ["재학생", "예비 입학생·지원자", "교직원", "외국인", "업체"]
    assert plan(documents(), quotas, fetch_chunks, "r1", seed=7) == items  # 씨앗이 같으면 같은 계획


def test_plan_skips_groups_of_other_batches():
    items = plan(documents(), {"fact": 6}, fetch_chunks, "r2", seed=1, skip_groups={f"공지:{n}" for n in range(5)})
    assert {item["group_id"] for item in items} == {"공지:5"}  # 남은 묶음 하나뿐이라 하나만


def test_dataset_documents_reads_dataset_uploads(ledger):
    ledger.upsert({"doc_id": "a/1", "site": "www", "kind": "attach", "url": "https://x/1", "title": "가나 안내",
                   "collected_at": "2026-10-02", "format": "pdf", "split": "학습", "group_id": "공지:가나", "topic": "학사"})
    ledger.con.execute("INSERT INTO uploads VALUES ('dataset','a/1','s',7,'ready',NULL,'http://x','2026-10-21')")
    ledger.con.execute("INSERT INTO uploads VALUES ('service','a/1','s',3,'ready',NULL,'http://x','2026-10-21')")
    assert [(d["doc_id"], d["document_id"]) for d in dataset_documents(ledger.con)] == [("a/1", 7)]


def test_question_prompt_has_kind_user_style_and_text():
    item = {"kind": "table", "user": "외국인", "style": "쉬운 한국어", "title": "가나대학 등록 안내", "chunks": [chunk(2, TABLE)]}
    text = prompts.question_prompt(item)
    assert prompts.KIND_RULES["table"] in text and "외국인" in text and prompts.STYLE_RULES["쉬운 한국어"] in text
    assert "1,200,000원" in text and '"가능"' in text
    offtopic = prompts.question_prompt({"kind": "refuse_offtopic", "user": "업체", "style": "정중체", "chunks": []})
    assert "(글 없음)" in offtopic and "빈 글" in offtopic


def test_target_prompt_shapes_and_hint():
    ga = prompts.target_prompt({}, "[검색 근거]\n[출처 1]\n휴학 신청", "8월 29일까지", "ga")
    assert "[출처 N]" in ga and prompts.REFUSAL in ga and "8월 29일까지" in ga and "[검색 근거]" in ga
    na = prompts.target_prompt({}, "프롬프트", "", "na")
    assert "'근거:'" in na and "답이 되는 부분" not in na


class FakeSession:
    def __init__(self, payload):
        self.payload, self.sent = payload, []

    def post(self, url, json=None, timeout=None):
        self.sent.append((url, json))
        payload = self.payload(json) if callable(self.payload) else self.payload
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: payload})()


def test_generate_turns_off_thinking_and_asks_json():
    session = FakeSession({"response": '{"질문": "가나대학 휴학 언제까지야?"}', "done_reason": "stop", "eval_count": 9})
    out = clients.generate(session, "http://o/", "gemma", "지시", temperature=0.7, num_ctx=4096, num_predict=400,
                           json_mode=True)
    url, body = session.sent[0]
    assert url == "http://o/api/generate" and body["think"] is False and body["format"] == "json"
    assert out["generation"]["done_reason"] == "stop"
    assert clients.parse_json('앞말 {"가능": false} 뒷말') == {"가능": False}


def test_attach_takes_prompt_and_final_candidates():
    trace = {"answer_path": "llm", "prompt": "P", "context": "C",
             "stages": {"final": [{"chunk_id": "x", "document_id": "7", "ledger_id": "a/1", "chunk_index": 2,
                                   "chunk_role": "raw", "text": "긴 글"}]}}
    session = FakeSession({"answer": "학습 전 답", "eval_trace": trace})
    out = clients.attach(session, "http://ai", "질문")
    assert session.sent[0][1]["include_eval_trace"] is True and session.sent[0][1]["top_k"] == 8
    assert out["prompt"] == "P" and out["ax_answer"] == "학습 전 답"
    assert out["retrieved"] == [{"chunk_id": "x", "document_id": "7", "ledger_id": "a/1", "chunk_index": 2, "chunk_role": "raw"}]
    with pytest.raises(ValueError):
        clients.attach(FakeSession({"answer": "표 답", "eval_trace": {"answer_path": "table_fact", "prompt": ""}}),
                       "http://ai", "질문")


PROMPT = """너는 가나대학 문서를 근거로 답변하는 안내 챗봇이다.

[검색 근거]
[출처 1]
문서: 가나대학 휴학 안내.html
전체 내용:
휴학 신청 기간은 8월 18일부터 8월 29일까지이다. 문의는 학사지원팀 02-000-0000.

[출처 2]
문서: 가나대학 등록 안내.pdf
표 검색 정보:
1. 등록금: 신입생 행 정보는 등록 기간=2월 3일~2월 7일; 금액=1,200,000원이다.
2. 등록금: 신입생 행 정보는 금액=1,250,000원이다.
3. 장학금: 성적 행 정보는 금액=500,000원이다.

[사용자 질문]
휴학 언제까지 신청해?

[답변 작성]
"""


def record(**extra):
    base = {"id": "r1-0001", "kind": "fact", "question": "휴학 언제까지 신청해?", "hint": "8월 18일부터 8월 29일까지",
            "prompt": PROMPT, "document_id": 7, "chunks": [{"chunk_index": 2}],
            "retrieved": [{"document_id": "7", "chunk_index": 2}, {"document_id": "9", "chunk_index": 0}],
            "target_ga": "8월 29일까지 신청하면 됩니다(기간 8월 18일~8월 29일). 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"}
    base.update(extra)
    return base


def failed(result):
    return sorted(name for name, value in result["checks"].items() if not value["ok"])


def test_good_answer_passes_all_checks():
    result = checks.check(record())
    assert failed(result) == [] and not result["drop"]


@pytest.mark.parametrize("extra, name", [
    ({"target_ga": "8월 29일까지 신청하면 됩니다."}, "모양"),  # 끝 줄에 출처 번호 없음
    ({"target_ga": "8월 29일까지입니다. 그 밖은 제공된 문서에서는 확인할 수 없습니다.\n[출처 1]"}, "모양"),
    ({"target_ga": "8월 29일까지입니다.\n[출처 5]"}, "출처 번호 범위"),
    ({"target_ga": "8월 31일까지입니다.\n[출처 1]"}, "근거 대조"),  # 근거에 없는 날짜
    ({"target_ga": "8월 29일까지입니다.\n[출처 2]"}, "출처 번호 대조"),  # 값이 쓴 번호의 근거에 없음
    ({"hint": "9월 1일부터 9월 5일까지"}, "지워진 정답"),  # 답 근거가 프롬프트에 없음(발췌 규칙이 지움)
    # 질문을 만든 청크도 없고 답 근거가 든 블록도 없을 때만 왕복 검사가 떨어진다(ADR-0048 결정 3)
    ({"retrieved": [{"document_id": "9", "chunk_index": 0}], "hint": "9월 1일부터 9월 5일까지"}, "왕복 검색"),
    ({"question": "휴학 언제까지? 내 번호 010-1234-5678"}, "개인정보"),
    ({"question": "..."}, "질문"),
])
def test_each_check_catches_its_error(extra, name):
    result = checks.check(record(**extra))
    assert name in failed(result) and result["drop"]


def test_ambiguous_table_value_is_dropped():
    target = "신입생 등록금은 1,200,000원입니다.\n[출처 2]"
    result = checks.check(record(question="신입생 등록금 얼마야?", hint="금액=1,200,000원", target_ga=target,
                                 retrieved=[{"document_id": "7", "chunk_index": 2}]))
    assert failed(result) == ["모호한 표 근거"]
    clear = checks.check(record(question="성적 장학금 얼마야?", hint="금액=500,000원",
                                target_ga="성적 장학금은 500,000원입니다.\n[출처 2]"))
    assert "모호한 표 근거" not in failed(clear)


def test_table_facts_parse_row_path():
    facts = checks.table_facts("1. 장학금 요약표: 생활비 행 정보는 (행 경로=마바 장학;) 장학 금액=1.5이다.")
    assert facts == [("장학금 요약표", "생활비 마바 장학", "장학 금액", "1.5")]


def test_refusal_shapes():
    good = checks.check(record(kind="refuse_guide", question="휴학하면 등록금 몇 퍼센트 돌려줘?",
                               target_ga=f"{prompts.REFUSAL} 휴학 문의는 학사지원팀(02-000-0000)입니다. [출처 1]"))
    assert failed(good) == []
    plain = checks.check(record(kind="refuse_offtopic", question="내일 날씨 어때?", target_ga=prompts.REFUSAL))
    assert failed(plain) == []
    wrong = checks.check(record(kind="refuse_guide", target_ga="확인이 어렵습니다. 학사지원팀에 물어보세요."))
    assert "모양" in failed(wrong)
    no_number = checks.check(record(kind="refuse_guide", target_ga=f"{prompts.REFUSAL} 학사지원팀에 문의하세요."))
    assert "모양" in failed(no_number)
    # 운영 거절 문장이 아닌 거절(번호를 붙였거나 짧아도) — 채점기가 거절로 못 알아볼 수 있는 말투를 가르치지 않는다
    other_words = checks.check(record(kind="refuse_guide", target_ga="확인이 어렵습니다. 학사지원팀(02-000-0000)에 문의하세요. [출처 1]"))
    assert failed(other_words) == ["모양"]
    dont_know = checks.check(record(kind="refuse_offtopic", target_ga="모르겠습니다."))
    assert "모양" in failed(dont_know) and dont_know["drop"]  # 거절 말투라 답 예시로 바뀌지 않고 모양에서 떨어진다


def test_partial_needs_answer_and_refusal():
    target = f"휴학 신청은 8월 29일까지입니다. 휴학 비용은 {prompts.REFUSAL}\n[출처 1]"
    assert failed(checks.check(record(kind="partial", target_ga=target))) == []
    # 일부만 있음 계획인데 받은 근거로 다 답했으면 답 예시로 바뀐다(ADR-0041)
    whole = checks.check(record(kind="partial"))
    assert whole["kind"] == "fact" and failed(whole) == [] and whole["judge_notes"]


def test_kind_follows_received_evidence_not_plan():
    # 거절 계획인데 받은 근거에 답이 있어 답했다 — 근거 번호가 둘이면 여러 근거 합치기
    answered = checks.check(record(kind="refuse_guide", hint="", target_ga="8월 29일까지 신청하면 됩니다.\n[출처 1][출처 2]"))
    assert answered["kind"] == "multi" and not answered["drop"] and "계획 refuse_guide" in answered["judge_notes"][0]
    # 값이 없는 말글 답은 글자 겹침으로 가르지 않고 Claude 판정에 확인 메모를 넘긴다
    words = checks.check(record(kind="refuse_guide", hint="", target_ga="학사지원팀에서 휴학을 신청받습니다.\n[출처 1]"))
    assert words["kind"] == "fact" and "출처 번호 대조" not in words["checks"]
    assert any("값이 없는 답" in note for note in words["judge_notes"])
    # 답 계획인데 질문 재료 청크가 검색됐고 답 근거도 남았는데 거절했다 — 목표 답이 틀린 것이라 바꾸지 않고 떨어뜨린다
    wrong_refusal = checks.check(record(kind="fact", target_ga=f"{prompts.REFUSAL}\n[출처 1]"))
    assert wrong_refusal["kind"] == "fact" and "모양" in failed(wrong_refusal)
    # 질문 재료 청크가 검색되지 않아 받은 근거에 답이 없으면 거절 예시로 바뀐다
    missed = checks.check(record(kind="fact", target_ga=f"{prompts.REFUSAL}\n[출처 1]",
                                 retrieved=[{"document_id": "9", "chunk_index": 0}]))
    assert missed["kind"] == "refuse_guide" and not missed["drop"]


def test_run_checks_keeps_planned_kind_and_gives_same_result_twice(tmp_path):
    batch = tmp_path / "r1"
    base = record(id="r1-0001", kind="refuse_guide", hint="", target_ga="8월 29일까지 신청하면 됩니다.\n[출처 1]")
    pipeline.write(batch, "plan", [{key: base[key] for key in ("id", "kind", "document_id", "chunks")}], mode="w")
    pipeline.write(batch, "questions", [{"id": "r1-0001", "question": base["question"], "hint": "", "possible": True}])
    pipeline.write(batch, "attached", [{"id": "r1-0001", "prompt": base["prompt"], "retrieved": base["retrieved"]}])
    pipeline.write(batch, "targets", [{"id": "r1-0001", "target_ga": base["target_ga"]}])
    for _ in range(2):
        counts = pipeline.run_checks(batch)
        merged = pipeline.merged(batch)[0]
        assert (merged["kind"], merged["kind_planned"], counts["종류 바꿈"]) == ("fact", "refuse_guide", 1)
    assert pipeline.status(batch)["fact"]["종류 바꿈"] == 1


def test_refusal_example_flags_ax_answer_with_evidence_values():
    result = checks.check(record(kind="refuse_guide", target_ga=prompts.REFUSAL, ax_answer="8월 29일까지 신청하세요."))
    assert not result["drop"] and result["judge_notes"]


def test_quote_shape():
    na = '근거: [출처 1] "휴학 신청 기간은 8월 18일부터 8월 29일까지이다."\n답: 8월 29일까지 신청하면 됩니다.\n[출처 1]'
    assert failed(checks.check(record(target_na=na), "na")) == []
    assert "모양" in failed(checks.check(record(target_na="답: 8월 29일까지입니다.\n[출처 1]"), "na"))


def test_duplicates_keep_first():
    records = [{"id": "a", "question": "휴학 신청 기간이 언제인가요?"}, {"id": "b", "question": "휴학 신청 기간이 언제인가요?!"},
               {"id": "c", "question": "등록금은 얼마야?"}]
    assert checks.duplicates(records) == {"b": "a"}


def test_pipeline_resumes_and_exports(tmp_path):
    batch = tmp_path / "r1"
    pipeline.write(batch, "plan", [
        {"id": "r1-0001", "kind": "fact", "user": "재학생", "style": "정중체", "title": "가나대학 휴학 안내",
         "document_id": 7, "chunks": [{"chunk_index": 2, "content": TEXT}]},
        {"id": "r1-0002", "kind": "refuse_offtopic", "user": "업체", "style": "정중체", "chunks": []}], mode="w")

    def ollama(body):
        if body.get("format") == "json":
            offtopic = "(글 없음)" in body["prompt"]
            return {"response": json.dumps({"질문": "내일 가나시 날씨 어때?" if offtopic else "휴학 언제까지 신청해?",
                                            "답 근거": "" if offtopic else "8월 18일부터 8월 29일까지",
                                            "묻는 사람": "외국인 유학생" if offtopic else "재학생", "가능": True})}
        # 답 근거를 함께 받은 목표 답 지시문(답 종류)이면 답을, 아니면(거절 종류) 거절 문장을 돌려준다
        answerable = "[질문을 만든 글에서 답이 되는 부분]" in body["prompt"]
        return {"response": record()["target_ga"] if answerable else prompts.REFUSAL}

    calls = []

    def flaky_ai(body):
        calls.append(body["question"])
        if len(calls) == 1:
            raise OSError("터널 끊김")
        return {"answer": "학습 전 답", "eval_trace": {"answer_path": "llm", "prompt": PROMPT, "stages": {"final": [
            {"document_id": "7", "chunk_index": 2}]}}}

    class Session(FakeSession):
        def post(self, url, json=None, timeout=None):
            if "/query" in url:
                payload = flaky_ai(json)
                return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: payload})()
            return super().post(url, json, timeout)

    session = Session(ollama)
    log = []
    assert pipeline.run_questions(batch, session, "http://o", "gemma", log=log.append)["made"] == 2
    first = pipeline.run_attach(batch, session, "http://ai", log=log.append)
    assert first == {"error": 1, "attached": 1}
    assert pipeline.run_attach(batch, session, "http://ai", log=log.append) == {"attached": 1}  # 실패한 것만 다시
    assert pipeline.run_questions(batch, session, "http://o", "gemma", log=log.append) == {}  # 끝난 것은 건너뜀
    assert pipeline.run_targets(batch, session, "http://o", "gemma", log=log.append)["made"] == 2
    counts = pipeline.run_checks(batch)
    assert counts["keep"] == 2
    out = tmp_path / "train.jsonl"
    assert pipeline.export(batch, out) == 2
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["messages"][0] == {"role": "user", "content": PROMPT}
    assert lines[0]["messages"][1]["role"] == "assistant" and lines[0]["meta"]["drafter"] == "gemma"
    assert pipeline.export(batch, out, verdicts={"r1-0001": "통과", "r1-0002": "탈락"}) == 1
    assert pipeline.status(batch)["fact"]["keep"] == 1
    assert {record["id"]: record["user_actual"] for record in pipeline.merged(batch)} == {"r1-0001": "재학생", "r1-0002": "외국인"}


CONSENT = "수집한 개인정보는 행사 종료 후 1년간 보관하며 이후 파기합니다."


def test_boilerplate_lines_found_across_documents_and_removed():
    chunks = {number: [chunk(0, f"가나대학 {number}번 행사 안내 본문이다.\n{CONSENT}")] for number in range(5)}
    chunks[9] = [chunk(0, "가나대학 기숙사 안내 본문이다.")]
    found = boilerplate_lines(chunks, min_docs=5)
    assert found == {CONSENT}
    assert draft_text(f"본문 줄\n  {CONSENT}  ", found) == "본문 줄"
    assert boilerplate_lines(chunks, min_docs=6) == set()
    header = "| 구분 | 신청 기간 | 장학 금액 | 비고 |"  # 20자 넘는 표 머리줄
    heading = "##### 장학금 신청 구비서류 안내 및 유의사항"  # 20자 넘는 제목 줄
    assert min(len(header), len(heading)) >= 20
    with_tables = {n: [chunk(0, f"{header}\n{heading}\n짧은 줄 02-000-0000")] for n in range(6)}
    assert boilerplate_lines(with_tables, min_docs=5) == set()  # 표 줄·제목 줄·짧은 줄은 남긴다


def test_pick_chunks_measures_length_without_boilerplate():
    rng = random.Random(1)
    mostly_consent = chunk(0, "가나대학 짧은 안내.\n" + "\n".join([CONSENT] * 8))
    assert pick_chunks(KINDS["fact"], [mostly_consent], rng) is not None  # 상투문을 모르면 길어 보인다
    assert pick_chunks(KINDS["fact"], [mostly_consent], rng, {CONSENT}) is None


def test_plan_gives_drafter_text_without_boilerplate():
    def with_consent(document_id):
        return [chunk(0, TEXT + "\n" + CONSENT), chunk(1, TEXT + "\n" + CONSENT)]
    items = plan(documents(), {"fact": 1}, with_consent, "r1", seed=3, boilerplate={CONSENT})
    assert CONSENT in items[0]["chunks"][0]["content"] and CONSENT not in items[0]["chunks"][0]["draft_text"]
    assert CONSENT not in prompts.question_prompt(items[0])


def test_question_prompt_asks_for_named_subject_and_keeps_user():
    text = prompts.question_prompt({"kind": "fact", "user": "교직원", "style": "정중체", "title": "가나대학 안내",
                                    "chunks": [chunk(0)]})
    assert "대상(행사·전형·장학금·프로그램·학과 등)" in text and "전혀 없을 때만" in text and "반드시 지킨다" in text
    assert "공식 명칭 전체" in text  # 문서 용어를 베끼지 않고 평소 부르는 이름으로(ADR-0044)


def test_styles_rotate_independently_of_users():
    from corpus.trainset.plan import STYLES, USERS, plan
    items = plan([], {"refuse_offtopic": 25}, lambda document_id: [], "r1", seed=1)  # 글 없는 종류라 문서가 필요 없다
    assert len({(item["user"], item["style"]) for item in items}) == len(USERS) * len(STYLES)  # 25개면 짝이 모두 한 번씩
    assert {"짧은 구어", "검색어형"} <= set(STYLES) and all(style in prompts.STYLE_RULES for style in STYLES)


def test_target_prompt_lists_guidance_candidates_from_evidence():
    text = prompts.target_prompt({"kind": "fact"}, PROMPT, "8월 18일부터 8월 29일까지")
    assert "[근거에 있는 안내 후보]" in text and "- [출처 1]" in text and "02-000-0000" in text.split("\n[챗봇이 받는 입력]\n")[0]  # 후보는 입력 앞(지시문 안)에


def test_offtopic_prompt_does_not_invite_impossible():
    offtopic = prompts.question_prompt({"kind": "refuse_offtopic", "user": "업체", "style": "정중체", "chunks": []})
    assert "'가능'은 true로 둔다." in offtopic and "false로 한다" not in offtopic
    fact = prompts.question_prompt({"kind": "fact", "user": "업체", "style": "정중체", "title": "가나", "chunks": [chunk(0)]})
    assert "양식 문구뿐이어도 false" in fact and "질문 재료로 쓰지 않는다" in fact


@pytest.mark.parametrize("text, expected", [
    ("지원자", "예비 입학생·지원자"), ("예비 입학생", "예비 입학생·지원자"), ("재학생", "재학생"),
    ("외국인 유학생", "외국인"), ("협력 기업 담당자", "업체"), ("교수", "교직원"), ("", "교직원"), ("누군가", "교직원"),
])
def test_user_category(text, expected):
    assert pipeline.user_category(text, "교직원") == expected


def test_probe_score_counts_ax_answers_against_target():
    good = "8월 29일까지 신청하면 됩니다."
    scored = checks.probe_score(record(ax_answer=good, ax_samples=[good, "9월 5일까지입니다.", prompts.REFUSAL]), "fact")
    assert (scored["n"], scored["decided"], scored["correct"]) == (4, 4, 2)
    assert scored["wrong"] == ["9월 5일까지입니다.", prompts.REFUSAL]  # 틀린 답은 선호 학습의 '나쁜 답' 후보
    refusal = checks.probe_score(record(kind="refuse_guide", target_ga=prompts.REFUSAL, ax_answer=good,
                                        ax_samples=[prompts.REFUSAL, "확인이 어렵습니다."]), "refuse_guide")
    assert (refusal["decided"], refusal["correct"]) == (3, 2)
    no_values = checks.probe_score(record(target_ga="학사지원팀에서 받습니다.\n[출처 1]", ax_answer="학사지원팀"), "fact")
    assert (no_values["n"], no_values["decided"]) == (1, 0)  # 값이 없으면 규칙으로 가르지 않는다


def test_check_notes_missing_contact_from_cited_evidence():
    missing = checks.check(record(target_ga="8월 29일까지 신청하면 됩니다.\n[출처 1]"))
    assert not missing["drop"] and any("02-000-0000" in note for note in missing["judge_notes"])
    given = checks.check(record())  # 기본 목표 답은 학사지원팀 번호를 말한다
    assert not any("연락처" in note for note in given["judge_notes"])


def test_run_probe_samples_ax_with_production_settings(tmp_path):
    batch = tmp_path / "r1"
    pipeline.write(batch, "plan", [{"id": "r1-0001", "kind": "fact"}], mode="w")
    pipeline.write(batch, "questions", [{"id": "r1-0001", "question": "휴학 언제까지?", "possible": True}])
    pipeline.write(batch, "attached", [{"id": "r1-0001", "prompt": PROMPT,
                                        "runtime": {"llm_model": "ax40light:q4km", "num_ctx": 12288, "num_predict": 512}}])
    session = FakeSession({"response": "8월 29일까지입니다."})
    assert pipeline.run_probe(batch, session, "http://o", samples=3, log=lambda line: None) == {"probed": 1}
    bodies = [body for _, body in session.sent]
    assert len(bodies) == 3 and {body["model"] for body in bodies} == {"ax40light:q4km"}
    assert {(body["options"]["num_ctx"], body["options"]["temperature"]) for body in bodies} == {(12288, 0.7)}
    assert bodies[0]["prompt"] == PROMPT  # 운영 프롬프트 그대로
    assert pipeline.merged(batch)[0]["ax_samples"] == ["8월 29일까지입니다."] * 3
    assert pipeline.run_probe(batch, session, "http://o", samples=3, log=lambda line: None) == {}  # 끝난 것은 건너뜀


def test_missing_guidance_compares_cited_lines_regardless_of_date_format():
    from corpus.trainset import evidence
    complete = "2026. 8. 18. ~ 8. 29.까지 신청합니다. 문의 02-000-0000\n[출처 1]"
    assert evidence.missing_guidance(complete, PROMPT) == []
    lost = evidence.missing_guidance("8월 29일까지 신청하면 됩니다.\n[출처 1]", PROMPT)
    assert [(number, values) for number, _, values in lost] == [(1, ["02-000-0000", "8월 18일"])]
    # 거절 답은 확인처(연락처·사이트)만 본다
    refusal = evidence.missing_guidance(prompts.REFUSAL + "\n[출처 1]", PROMPT, refusal=True)
    assert [values for _, _, values in refusal] == [["02-000-0000"]]


def test_missing_guidance_skips_uncited_evidence_and_revision_dates():
    from corpus.trainset import evidence
    prompt = ("[검색 근거]\n[출처 1]\n문서: 가나대학 학칙.pdf\n전체 내용:\n"
              "학생은 사유 발생일로부터 7일 이내에 출석인정원을 낸다. <개정 2019.11.25.>\n\n"
              "[출처 2]\n문서: 가나대학 학사 안내.html\n전체 내용:\n문의: 가나대학 학사팀 02-111-1111\n\n[사용자 질문]\n출석 인정?")
    assert evidence.missing_guidance("7일 이내에 출석인정원을 내야 합니다.\n[출처 1]", prompt) == []  # 개정일·출처 2는 안 봄
    assert [values for _, _, values in evidence.missing_guidance("출석인정원을 내야 합니다.\n[출처 1]", prompt)] == [["7일"]]


def test_run_targets_rewrites_once_when_cited_guidance_is_missing(tmp_path):
    batch = tmp_path / "r1"
    prompts_by_id = {"r1-0001": PROMPT, "r1-0002": PROMPT.replace("휴학 언제까지 신청해?", "휴학 문의처랑 기간?"),
                     "r1-0003": PROMPT.replace("휴학 언제까지 신청해?", "가나시 내일 날씨?")}
    kinds = {"r1-0001": "fact", "r1-0002": "fact", "r1-0003": "refuse_offtopic"}
    pipeline.write(batch, "plan", [{"id": item_id, "kind": kind, "chunks": []} for item_id, kind in kinds.items()], mode="w")
    pipeline.write(batch, "questions", [{"id": item_id, "question": "q", "hint": "8월 29일까지", "possible": True}
                                        for item_id in kinds])
    pipeline.write(batch, "attached", [{"id": item_id, "prompt": prompt} for item_id, prompt in prompts_by_id.items()])
    full, partial = record()["target_ga"], "8월 29일까지 신청하면 됩니다.\n[출처 1]"

    def ollama(body):
        if "[검사 결과]" in body["prompt"]:
            return {"response": full}
        if "가나시 내일 날씨?" in body["prompt"]:
            return {"response": prompts.REFUSAL}
        return {"response": full if "휴학 문의처랑 기간?" in body["prompt"] else partial}

    session = FakeSession(ollama)
    counts = pipeline.run_targets(batch, session, "http://o", "gemma", log=lambda line: None)
    assert counts["made"] == 3 and counts["guidance_fix"] == 1 and len(session.sent) == 4
    targets = pipeline.read(batch, "targets")
    fixed = targets["r1-0001"]
    assert fixed["target_ga"] == full
    assert fixed["target_generation"]["ga"]["guidance_fix"]["draft"] == partial
    assert fixed["target_generation"]["ga"]["guidance_fix"]["missing"] == ["[출처 1] 02-000-0000, 8월 18일"]
    fix_prompt = session.sent[1][1]["prompt"]
    assert "[먼저 쓴 답]\n" + partial in fix_prompt and "02-000-0000, 8월 18일" in fix_prompt
    assert "근거 줄을 목록으로 붙여 넣지 않는다" in fix_prompt and fix_prompt.endswith(prompts.TARGET_END)
    assert fix_prompt.count(PROMPT) == 1  # 챗봇 입력은 한 번만
    assert "guidance_fix" not in targets["r1-0002"]["target_generation"]["ga"]  # 이미 다 쓴 답은 다시 쓰지 않음
    assert "guidance_fix" not in targets["r1-0003"]["target_generation"]["ga"]  # 엉뚱한 근거 종류는 확인처를 붙이지 않음


def test_ambiguous_rule_shared_by_target_prompt_and_judge_guide():
    from corpus.trainset import judge
    for shape in ("ga", "na"):
        assert prompts.AMBIGUOUS_RULE in prompts.target_prompt({}, PROMPT, "", shape)
    assert prompts.AMBIGUOUS_RULE in judge.PROMPT and judge.GUIDE_VERSION == "2026-11-01"
    # ADR-0047 결정 5: '가장 최근 근거로'가 아니라 '오늘 기준으로 유효한 근거로', 지난 학기뿐이면 밝히고 확인처
    assert "오늘" in prompts.AMBIGUOUS_RULE and "지난 학기" in prompts.AMBIGUOUS_RULE and "가장 최근 것" not in prompts.AMBIGUOUS_RULE
    # ADR-0049: 기준은 근거에 적힌 것만 필요할 때만 — 오늘 날짜로 만들지 않고, 베낄 예시 문구를 넣지 않는다
    assert "오늘 날짜로 학년도·학기를 만들지 않는다" in prompts.AMBIGUOUS_RULE
    assert "기준을 붙이지 않는다" in prompts.AMBIGUOUS_RULE and "학기 기준'" not in prompts.AMBIGUOUS_RULE
    assert "근거 문서에 없는 학년도·학기를 기준으로 썼으면 탈락" in judge.PROMPT
    assert "기준이 없는 것은 탈락 사유가 아니다" in judge.PROMPT


def test_check_notes_missing_period_from_cited_evidence():
    result = checks.check(record(target_ga="휴학은 8월 29일까지이며 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"))
    assert not result["drop"] and any("8월 18일" in note for note in result["judge_notes"])


def test_fill_quotas_assigns_only_missing_kinds_weighted_by_yield():
    from corpus.trainset.plan import fill_quotas
    target = {"fact": 4, "table": 4, "refuse_guide": 2}
    planned = {"fact": 4, "table": 4, "refuse_guide": 2}
    # 표는 3개 모자라고 수율 1/4, 거절은 2개 모자라고 수율 0(바닥값 0.2) → 무게 12 대 10
    quotas = fill_quotas(target, {"fact": 4, "table": 1}, planned, {"fact": 3, "table": 1}, 10)
    assert quotas == {"table": 5, "refuse_guide": 5}
    assert fill_quotas(target, target, planned, target, 10) == {}  # 다 채웠으면 새 묶음이 필요 없다


def test_pick_round_balances_kinds_prefers_what_ax_misses_and_shares_ids_across_shapes(tmp_path):
    def batch(name, rows):
        folder = tmp_path / name
        pipeline.write(folder, "plan", [{"id": row["id"], "kind": row["kind"]} for row in rows], mode="w")
        pipeline.write(folder, "questions", [{"id": row["id"], "question": row["q"], "possible": True} for row in rows])
        pipeline.write(folder, "attached", [{"id": row["id"], "prompt": PROMPT} for row in rows])
        pipeline.write(folder, "targets", [{"id": row["id"], "target_ga": f"{row['id']} 가", "target_na": f"{row['id']} 나"}
                                           for row in rows])
        pipeline.write(folder, "checked", [{"id": row["id"], "kind": row["kind"], "keep": {"ga": True, "na": row.get("na", True)},
                                            "probe": row.get("probe", {})} for row in rows])
        pipeline.write(folder, "judged", [{"id": row["id"], "verdict": row["verdict"]} for row in rows])
        pipeline.write(folder, "human", [{"id": row["id"], "human": row["human"]} for row in rows if "human" in row])
        return folder

    def probe(correct, decided):
        return {"correct": correct, "decided": decided}

    first = batch("a", [
        {"id": "a1", "kind": "fact", "q": "가나대학 휴학 신청 기간이 언제인가요?", "verdict": "통과", "probe": probe(5, 5)},
        {"id": "a2", "kind": "fact", "q": "가나대학 등록금 얼마야?", "verdict": "통과", "probe": probe(0, 5)},
        {"id": "a3", "kind": "table", "q": "신입생 등록 기간 표", "verdict": "통과", "probe": probe(2, 4)},
        {"id": "a4", "kind": "fact", "q": "가나대학 기숙사비?", "verdict": "탈락", "probe": probe(0, 5)},
        {"id": "a5", "kind": "fact", "q": "가나대학 장학금 문의처", "verdict": "통과", "na": False, "probe": probe(0, 5)}])
    second = batch("b", [
        {"id": "b1", "kind": "fact", "q": "가나대학 휴학 신청 기간이 언제인가요?", "verdict": "통과", "probe": probe(0, 5)},
        {"id": "b2", "kind": "refuse_guide", "q": "가나대학 셔틀버스 요금?", "verdict": "탈락", "human": "통과"},
        {"id": "b3", "kind": "fact", "q": "가나대학 졸업 학점?", "verdict": "통과", "human": "탈락", "probe": probe(0, 5)}])
    # 3개면 1회차 비율로 사실·표·절차 하나씩. 절차는 없어 남은 예시 중 아는 정도가 낮은 b2(모름 0.5)가 a1(다 맞힘)보다 먼저
    # b1은 a1과 질문이 겹쳐 빠지고, a4는 탈락, a5는 모양 '나'가 자동 검사를 못 넘어, b3은 사람이 탈락으로 바꿔 빠진다
    assert [record["id"] for record in pipeline.pick_round([first, second], 3, ("ga", "na"))] == ["a2", "a3", "b2"]
    manifest = pipeline.export_round([first, second], tmp_path / "round1", 3, ("ga", "na"))
    assert manifest["kinds"] == {"fact": 1, "table": 1, "refuse_guide": 1}
    assert manifest["known"] == {"못 맞힘": 1, "가끔": 1, "모름": 1}
    for shape in ("ga", "na"):
        lines = [json.loads(line) for line in (tmp_path / "round1" / f"round-{shape}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [line["id"] for line in lines] == ["a2", "a3", "b2"]  # 두 모양에 같은 예시
        assert lines[0]["messages"][1]["content"] == f"a2 {'가' if shape == 'ga' else '나'}"
    passed, planned, planned_passed = pipeline.yields([first, second])
    assert passed == {"fact": 4, "table": 1, "refuse_guide": 1} and planned["fact"] == 6


# ADR-0050 결정 4·7: 1회차는 결론 먼저 모양 한 벌, 거절 문장 뒤에 출처 번호만 있으면 학습 파일에서 지운다
def test_training_line_drops_citations_only_after_a_bare_refusal():
    def content(target):
        return pipeline.training_line(record(target_ga=target), "ga")["messages"][1]["content"]

    assert content(f"{prompts.REFUSAL}\n\n[출처 1][출처 2]") == prompts.REFUSAL
    guide = f"{prompts.REFUSAL} 휴학 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"
    assert content(guide) == guide  # 확인처가 나온 근거 번호는 남긴다
    partial = f"8월 29일까지 신청하면 됩니다. 수수료는 {prompts.REFUSAL}\n[출처 1]"
    assert content(partial) == partial  # 일부만 없는 답도 그대로
    assert content(record()["target_ga"]) == record()["target_ga"]


def test_export_round_defaults_to_one_shape_and_counts_removed_citations(tmp_path):
    folder = tmp_path / "c"
    rows = [("c1", "fact", "8월 29일까지 신청하면 됩니다.\n[출처 1]"), ("c2", "refuse_guide", f"{prompts.REFUSAL}\n\n[출처 1][출처 2]")]
    pipeline.write(folder, "plan", [{"id": i, "kind": kind} for i, kind, _ in rows], mode="w")
    pipeline.write(folder, "questions", [{"id": i, "question": f"가나대학 질문 {i}", "possible": True} for i, _, _ in rows])
    pipeline.write(folder, "attached", [{"id": i, "prompt": PROMPT} for i, _, _ in rows])
    pipeline.write(folder, "targets", [{"id": i, "target_ga": target} for i, _, target in rows])  # 인용형(na)은 만들지 않았다
    pipeline.write(folder, "checked", [{"id": i, "kind": kind, "keep": {"ga": True}} for i, kind, _ in rows])
    pipeline.write(folder, "judged", [{"id": i, "verdict": "통과"} for i, _, _ in rows])
    manifest = pipeline.export_round([folder], tmp_path / "round1", 2)
    assert manifest["shapes"] == ["ga"] and sorted(manifest["ids"]) == ["c1", "c2"]
    assert manifest["removed_refusal_citations"] == {"ga": 1}
    assert not (tmp_path / "round1" / "round-na.jsonl").exists()
    lines = {json.loads(line)["id"]: json.loads(line)
             for line in (tmp_path / "round1" / "round-ga.jsonl").read_text(encoding="utf-8").splitlines()}
    assert lines["c2"]["messages"][1]["content"] == prompts.REFUSAL
    assert lines["c1"]["messages"][1]["content"] == rows[0][2]


# ADR-0050 2026-11-02 변경: 거절 문장은 모델이 학습으로 바로 쓴다. 옛 문장으로 만든 묶음은 내보낼 때 목표 답과 입력 규칙을
# 함께 바꾼다 — 둘이 어긋나면 규칙과 다르게 답하는 버릇을 배운다
MAIN_PY = Path(__file__).resolve().parents[3] / "ai-server" / "main.py"


def operating_rules() -> str:
    """운영 프롬프트의 필수 답변 규칙(ai-server main.py의 MANDATORY_RAG_PROMPT). 서버 코드를 부르지 않고 글자만 읽는다."""
    for node in ast.parse(MAIN_PY.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "MANDATORY_RAG_PROMPT" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("MANDATORY_RAG_PROMPT를 찾지 못함")


def with_rules(rules: str) -> str:
    return PROMPT.replace("\n\n[검색 근거]", f"\n\n{rules}\n\n[검색 근거]")


def legacy_operating_rules(legacy: tuple[str, str]) -> str:
    """지금 운영 규칙에서 거절 규칙 9·11만 지난 규칙으로 되돌린 글(지난 묶음의 학습 입력 모양)."""
    rules = operating_rules()
    for old, new in zip(legacy, prompts.REFUSAL_RULES):
        rules = rules.replace(new, old)
    return rules


def test_refusal_rules_are_the_operating_rules():
    rules = operating_rules().splitlines()
    assert all(rule in rules for rule in prompts.REFUSAL_RULES)  # 학습 입력에 넣는 규칙이 운영 규칙과 글자까지 같다
    assert not any(legacy in rule for rule in rules for legacy in prompts.LEGACY_REFUSALS)
    assert all(prompts.REFUSAL in rule for rule in prompts.REFUSAL_RULES)


@pytest.mark.parametrize("legacy", range(len(prompts.LEGACY_REFUSAL_RULES)))
def test_training_line_rewords_legacy_refusal_in_answer_and_rules(legacy):
    """옛 운영 문장으로 만든 묶음과 2026-11-02 한때 문장으로 만든 묶음 모두 목표 답과 입력 규칙을 지금 문장으로 바꾼다."""
    old = prompts.LEGACY_REFUSALS[legacy]

    def line(target):
        out = pipeline.training_line(record(prompt=with_rules(legacy_operating_rules(prompts.LEGACY_REFUSAL_RULES[legacy])),
                                            target_ga=target), "ga")
        return out["messages"][0]["content"], out["messages"][1]["content"]

    prompt, bare = line(f"{old}\n\n[출처 1][출처 2]")
    assert prompt == with_rules(operating_rules()) and bare == prompts.REFUSAL
    guide = f"{old} 휴학 문의는 학사지원팀(02-000-0000)입니다.\n[출처 1]"
    assert line(guide)[1] == guide.replace(old, prompts.REFUSAL)
    partial = f"8월 29일까지 신청하면 됩니다. 수수료는 {old}\n[출처 1]"
    assert line(partial)[1] == partial.replace(old, prompts.REFUSAL)  # 일부만 없음도 같은 문장
    new = partial.replace(old, prompts.REFUSAL)
    assert line(new)[1] == new  # 지금 문장으로 만든 답은 그대로


def test_checks_take_current_and_legacy_refusal():
    for refusal in prompts.REFUSALS:
        assert checks.shape_check("refuse_offtopic", refusal, "ga") == (True, "")
        assert checks.shape_check("refuse_guide", f"{refusal} 학사지원팀에 문의하세요.", "ga")[0] is False  # 번호 없는 확인처
    partial = f"8월 29일까지입니다. 수수료는 {prompts.REFUSAL}\n[출처 1]"
    assert checks.shape_check("partial", partial, "ga") == (True, "")  # 지금 문장도 '없는 것을 밝힘'
    assert checks.shape_check("fact", partial, "ga")[0] is False  # 답 예시에 섞인 거절


def test_export_round_rewords_old_batches_and_counts_left_overs(tmp_path):
    folder = tmp_path / "old"
    old = prompts.LEGACY_REFUSALS[0]
    rows = [("o1", "partial", f"8월 29일까지 신청하면 됩니다. 수수료는 {old}\n[출처 1]"),
            ("o2", "refuse_guide", f"{old}\n\n[출처 1]")]
    pipeline.write(folder, "plan", [{"id": i, "kind": kind} for i, kind, _ in rows], mode="w")
    pipeline.write(folder, "questions", [{"id": i, "question": f"가나대학 질문 {i}", "possible": True} for i, _, _ in rows])
    pipeline.write(folder, "attached", [{"id": i, "prompt": with_rules(legacy_operating_rules(prompts.LEGACY_REFUSAL_RULES[0]))}
                                        for i, _, _ in rows])
    pipeline.write(folder, "targets", [{"id": i, "target_ga": target} for i, _, target in rows])
    pipeline.write(folder, "checked", [{"id": i, "kind": kind, "keep": {"ga": True}} for i, kind, _ in rows])
    pipeline.write(folder, "judged", [{"id": i, "verdict": "통과"} for i, _, _ in rows])
    manifest = pipeline.export_round([folder], tmp_path / "round1", 2)
    assert manifest["reworded_refusals"] == {"targets": {"ga": 2}, "prompts": 2}
    assert manifest["removed_refusal_citations"] == {"ga": 1} and manifest["old_refusal_left"] == 0
    # 규칙 글자가 다른 지난 프롬프트는 바꾸지 못한다 — 남은 줄을 세어 내보내기를 멈추게 한다
    pipeline.write(folder, "attached", [{"id": "o1", "prompt": with_rules(f"9. '{old}'라고 답한다.")}])
    assert pipeline.export_round([folder], tmp_path / "round2", 2)["old_refusal_left"] == 1
    # 목표 답에 규칙의 '(없는 것)' 자리표시를 그대로 베낀 줄도 센다
    pipeline.write(folder, "attached", [{"id": "o1", "prompt": PROMPT}])
    pipeline.write(folder, "targets", [{"id": "o1", "target_ga": f"8월 29일까지입니다. (없는 것)은 {prompts.REFUSAL}\n[출처 1]"}])
    assert pipeline.export_round([folder], tmp_path / "round3", 2)["old_refusal_left"] == 1


# ADR-0048 결정 3·4: 답 근거가 든 블록은 코드가 짚고, 왕복 검사는 그 블록 기준, 표 질문은 사용자 말로
PROMPT_TWIN = PROMPT.replace("[사용자 질문]", """[출처 3]
문서: 가나대학 휴학 안내(학사지원팀 게시판).html
전체 내용:
휴학 신청 마감은 8월 29일이다.

[사용자 질문]""")


def test_hint_blocks_finds_every_block_with_the_answer():
    assert checks.hint_blocks("8월 18일부터 8월 29일까지", PROMPT_TWIN) == [1]  # 3번에는 8월 18일이 없다
    assert checks.hint_blocks("휴학 신청 마감", PROMPT_TWIN) == [3]  # 값 없는 답 근거는 글자 겹침으로
    assert checks.hint_blocks("", PROMPT_TWIN) == []


def test_round_trip_passes_when_answer_comes_from_another_document():
    # 질문을 만든 청크(7번 문서)가 근거 8개 밖이어도 답 근거가 1번 블록에 있으면 통과 — 학과마다 같은 페이지 같은 경우
    result = checks.check(record(retrieved=[{"document_id": "9", "chunk_index": 0}]))
    assert "왕복 검색" not in failed(result)


def test_citing_another_block_with_the_same_value_is_fine():
    # 답 근거가 든 블록은 1번이지만, 3번(같은 안내의 다른 글)에도 답의 값이 있으면 그 번호를 써도 된다.
    # 코드가 짚은 번호를 꼭 쓰게 하자 공고·재공고를 인용한 정상 답이 떨어졌다(ADR-0048 결과)
    target = "8월 29일까지 신청하면 됩니다.\n[출처 3]"
    assert "출처 번호 대조" not in failed(checks.check(record(prompt=PROMPT_TWIN, target_ga=target)))


def test_target_prompt_gives_code_found_source_number():
    task = prompts.target_prompt({}, PROMPT_TWIN, "8월 18일부터 8월 29일까지", "ga", hint_sources=[1])
    assert "이 부분은 [검색 근거]의 [출처 1]에 있다" in task and "몇 번에 있는지 찾아" not in task
    assert "몇 번에 있는지 찾아" in prompts.target_prompt({}, PROMPT_TWIN, "8월 18일부터 8월 29일까지", "ga")


def test_table_question_rule_asks_for_user_words_not_header_labels():
    rule = prompts.KIND_RULES["table"]
    assert "평소 쓰는 말" in rule and "칸 이름" in rule and "행 이름과 열 이름을 담는다" not in rule
