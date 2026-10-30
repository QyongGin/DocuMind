"""답없음(거절 + 확인처) 예시를 근거 구성으로 만든다(ADR-0048 결정 2). 가나대학 합성 데이터로.

답이 있는 질문을 만든 뒤, 근거를 붙일 때 답이 든 청크를 빼고 다시 붙여 근거 8개에 답이 없게 한다.
정답은 거절 문장이고, 확인처는 재료 문서의 다른 청크·같은 게시글·같은 묶음 블록의 연락처·사이트에서만 고른다.
"""

import json

from corpus.trainset import checks, pipeline, prompts

from test_trainset import FakeSession

MATERIAL = "gana/bbs/77"  # 질문 재료: 학위복 대여 공지(본문)
HINT = "대여료는 10,000원이다"


def evidence(*blocks):
    body = "\n\n".join(f"[출처 {number}]\n문서: {title}\n전체 내용:\n{text}" for number, (title, text) in enumerate(blocks, 1))
    return f"너는 가나대학 안내 챗봇이다.\n\n[검색 근거]\n{body}\n\n[사용자 질문]\n학위복 빌리면 돈 내?\n"


WITH_ANSWER = evidence(("학위복 대여 안내.html", "학위복 대여료는 10,000원이다. 대여는 학생지원팀에서 한다."),
                       ("가나대학 축제 안내.html", "축제는 5월에 열린다. 문의 02-111-2222"))
WITHOUT_ANSWER = evidence(("학위복 대여 안내.html", "학위복은 졸업식 전주에 빌린다. 문의는 학생지원팀 02-333-4444"),
                          ("가나대학 축제 안내.html", "축제는 5월에 열린다. 문의 02-111-2222"))
FIRST = {"answer_path": "llm", "prompt": WITH_ANSWER, "stages": {"final": [
    {"chunk_id": "77_0", "document_id": "77", "ledger_id": MATERIAL, "chunk_index": 0},
    {"chunk_id": "90_0", "document_id": "90", "ledger_id": "gana/bbs/90", "chunk_index": 0}]}}
SECOND = {"answer_path": "llm", "prompt": WITHOUT_ANSWER, "stages": {"final": [
    {"chunk_id": "77_1", "document_id": "77", "ledger_id": MATERIAL, "chunk_index": 1},  # 재료 문서의 다른 청크
    {"chunk_id": "90_0", "document_id": "90", "ledger_id": "gana/bbs/90", "chunk_index": 0}]}}


def batch_with_refusal_question(tmp_path, hint=HINT):
    batch = tmp_path / "r2"
    pipeline.write(batch, "plan", [{"id": "r2-0001", "kind": "refuse_guide", "ledger_id": MATERIAL, "group_id": "공지:학위복",
                                    "chunks": []}], mode="w")
    pipeline.write(batch, "questions", [{"id": "r2-0001", "question": "학위복 빌리면 돈 내?", "hint": hint, "possible": True}])
    return batch


def test_refusal_question_is_made_like_a_fact_question_with_hint():
    item = {"kind": "refuse_guide", "user": "재학생", "style": "짧은 구어", "title": "학위복 대여 안내",
            "chunks": [{"content": "학위복 대여료는 10,000원이다."}]}
    text = prompts.question_prompt(item)
    assert prompts.KIND_RULES["refuse_guide"] == prompts.KIND_RULES["fact"]
    assert "'답 근거'에는 질문의 답이 되는 부분을 글에서 그대로 옮긴다." in text


def test_attach_removes_answer_chunks_and_records_contact_blocks(tmp_path):
    batch = batch_with_refusal_question(tmp_path)
    session = FakeSession(lambda body: {"answer": "답", "eval_trace": SECOND if body.get("exclude_chunk_ids") else FIRST})
    assert pipeline.run_attach(batch, session, "http://ai", log=lambda line: None) == {"attached": 1}
    assert session.sent[1][1]["exclude_chunk_ids"] == ["77_0"]  # 답이 든 1번 블록의 청크를 빼고 다시 붙임
    attached = pipeline.read(batch, "attached")["r2-0001"]
    assert attached["prompt"] == WITHOUT_ANSWER
    assert attached["refusal"] == {"removed_chunks": ["77_0"], "contact_blocks": [1]}  # 재료 문서의 다른 청크만


def test_attach_fails_when_answer_cannot_be_removed(tmp_path):
    batch = batch_with_refusal_question(tmp_path)
    session = FakeSession({"answer": "답", "eval_trace": FIRST})  # 빼도 같은 답이 계속 올라옴
    assert pipeline.run_attach(batch, session, "http://ai", log=lambda line: None) == {"error": 1}
    assert "빼도 근거에 답이 남음" in pipeline.read(batch, "attached")["r2-0001"]["error"]


def test_attach_fails_without_hint(tmp_path):
    batch = batch_with_refusal_question(tmp_path, hint="")
    session = FakeSession({"answer": "답", "eval_trace": FIRST})
    assert pipeline.run_attach(batch, session, "http://ai", log=lambda line: None) == {"error": 1}


def test_contact_blocks_follow_post_and_group():
    family = {MATERIAL: (MATERIAL, "공지:학위복"), "gana/bbs/77/a1": (MATERIAL, "공지:학위복"),
              "gana/bbs/55": ("gana/bbs/55", "공지:학위복"), "gana/bbs/90": ("gana/bbs/90", "공지:축제")}
    retrieved = [{"ledger_id": "gana/bbs/77/a1"}, {"ledger_id": "gana/bbs/90"}, {"ledger_id": "gana/bbs/55"}, {}]
    assert pipeline.refusal_contact_blocks({"ledger_id": MATERIAL}, retrieved, family) == [1, 3]  # 같은 게시글 첨부, 같은 묶음
    assert pipeline.refusal_contact_blocks({"ledger_id": MATERIAL}, retrieved, None) == []  # 관계를 모르면 재료 문서만


def test_target_prompt_offers_only_contacts_from_allowed_blocks():
    task = prompts.target_prompt({}, WITHOUT_ANSWER, "", "ga", guidance_blocks=[1])
    assert "[출처 1] 학위복은 졸업식 전주에 빌린다. 문의는 학생지원팀 02-333-4444" in task
    assert "02-111-2222" not in task.split("[챗봇이 받는 입력]")[0]  # 축제 문의처는 후보에 없다
    assert "[답없음 예시]" in task
    none = prompts.target_prompt({}, WITHOUT_ANSWER, "", "ga", guidance_blocks=[])
    assert "\n[근거에 있는 안내 후보]\n" not in none and "후보가 없으면 거절 문장 하나만 쓴다" in none  # 후보 목록이 없다


def refusal_record(**extra):
    base = {"id": "r2-0001", "kind": "refuse_guide", "question": "학위복 빌리면 돈 내?", "hint": HINT, "prompt": WITHOUT_ANSWER,
            "refusal": {"removed_chunks": ["77_0"], "contact_blocks": [1]},
            "target_ga": f"{prompts.REFUSAL} 학위복 대여는 학생지원팀(02-333-4444)에 문의하세요.\n[출처 1]"}
    base.update(extra)
    return base


def failed(result):
    return sorted(name for name, value in result["checks"].items() if not value["ok"])


def test_constructed_refusal_checks():
    assert failed(checks.check(refusal_record())) == []
    assert "답 근거 없음" in failed(checks.check(refusal_record(prompt=WITH_ANSWER)))  # 근거에 답이 남음
    other = refusal_record(target_ga=f"{prompts.REFUSAL} 축제 문의는 02-111-2222입니다.\n[출처 2]")
    assert "확인처 출처" in failed(checks.check(other))  # 고른 블록 밖의 연락처
    answered = refusal_record(target_ga="학위복 대여료는 없습니다.\n[출처 1]")
    assert "거절함" in failed(checks.check(answered))


def test_old_refusal_records_without_construction_are_checked_as_before():
    old = refusal_record()
    del old["refusal"]
    assert not {"답 근거 없음", "거절함", "확인처 출처"} & set(checks.check(old)["checks"])
    json.dumps(old)  # 옛 묶음 기록 그대로
