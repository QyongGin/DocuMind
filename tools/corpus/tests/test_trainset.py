"""학습 예시 만들기(`trainset`): 묶음 고르기·지시문·호출·자동 검사·이어서 돌리기·학습 파일. 가나대학 합성 데이터로."""

import json
import random

import pytest

from corpus.trainset import checks, clients, pipeline, prompts
from corpus.trainset.plan import KINDS, ROUND1, dataset_documents, is_table_chunk, pick_chunks, plan, scale

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
    assert scale(ROUND1, 40) == {"fact": 7, "procedure": 6, "table": 7, "multi": 4, "partial": 4,
                                 "refuse_guide": 8, "refuse_offtopic": 4}
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
    ({"retrieved": [{"document_id": "9", "chunk_index": 0}]}, "왕복 검색"),
    ({"question": "휴학 언제까지? 내 번호 010-1234-5678"}, "개인정보"),
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


def test_partial_needs_answer_and_refusal():
    target = f"휴학 신청은 8월 29일까지입니다. 휴학 비용은 {prompts.REFUSAL}\n[출처 1]"
    assert failed(checks.check(record(kind="partial", target_ga=target))) == []
    assert "모양" in failed(checks.check(record(kind="partial")))


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
                                            "묻는 사람": "재학생", "가능": True})}
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
