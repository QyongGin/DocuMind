"""생성만 다시 돌리기(2단계 평가): 기준 실행의 프롬프트를 그대로, 우선 경로 답은 옮기고, 이어서 돌리고, 조건이 다르면 거부."""

import json

import pytest
import requests
from evalset_data import item

from corpus.evalset import metrics, regenerate, runner, schema

BASE_RUNTIME = {"llm_model": "gana-llm", "llm_temperature": 0.0, "num_ctx": 8192, "num_predict": 512,
                "embedding_model": "gana-embed"}
PROMPT = "규칙\n[검색 근거]\n전형료 30,000원\n질문: 가나대 원서비 얼마예요?"


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeOllama:
    """Ollama 생성 API 대신. down에 든 프롬프트는 연결 실패, prompt_tokens로 입력 토큰 수를 정한다."""

    def __init__(self, answer="전형료는 30,000원입니다.", down=frozenset(), prompt_tokens=100):
        self.answer, self.down, self.prompt_tokens, self.requests = answer, set(down), prompt_tokens, []

    def post(self, url, timeout, json):
        self.requests.append((url, json))
        if json["prompt"] in self.down:
            raise requests.ConnectionError("데스크탑 꺼짐")
        return FakeResponse({"response": self.answer, "done_reason": "stop", "eval_count": 12,
                             "prompt_eval_count": self.prompt_tokens, "eval_duration": 1, "prompt_eval_duration": 1})


@pytest.fixture
def base_run(tmp_path):
    """기준 실행: ev-0001은 모델 답(거절), ev-0002는 표 사실 우선 경로 답, ev-0003은 실패한 문항."""
    items = [item("ev-0001", part="dev"), item("ev-0002", question="가나대 정시 원서비는요?", part="dev"),
             item("ev-0003", question="가나대 수시 원서비는요?", part="dev")]
    schema.save(tmp_path / "evalset.jsonl", items)
    run_dir = tmp_path / "base"
    run_dir.mkdir()
    manifest = {"evalset_sha256": schema.fingerprint(items), "evalset_version": "v2", "index": "gana", "top_k": 5,
                "system_prompt_sha256": runner.sha256(""), "git_commit": "abc", "runtime": BASE_RUNTIME}
    (run_dir / runner.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    found = [{"ledger_id": "gana/page/fee", "text": "전형료 30,000원"}]
    trace = lambda path, prompt: {"answer_path": path, "stages": {"vector": found, "final": found},  # noqa: E731
                                  "context": "전형료 30,000원", "prompt": prompt, "runtime": BASE_RUNTIME,
                                  "generation": {"done_reason": "stop"} if path == "llm" else None}
    answers = [{"id": "ev-0001", "rev": 1, "question": items[0]["question"], "answer": "문서에서 확인할 수 없습니다.",
                "sources": [], "eval_trace": trace("llm", PROMPT), "elapsed": 2.0},
               {"id": "ev-0002", "rev": 1, "question": items[1]["question"], "answer": "표 근거 기준 답변입니다. 30,000원",
                "sources": [], "eval_trace": trace("priority_table_fact", "표 프롬프트"), "elapsed": 1.0},
               {"id": "ev-0003", "rev": 1, "question": items[2]["question"], "error": "시간 초과", "elapsed": 600.0}]
    (run_dir / runner.ANSWERS).write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in answers),
                                          encoding="utf-8")
    return run_dir


def again(base_run, out, session, model="gana-big", num_ctx=16384, **extra):
    return regenerate.regenerate(base_run, out, "http://gana:11435/", model, num_ctx, session=session, log=None,
                                 now=lambda: "2026-10-13T20:00:00", **extra)


def test_regenerates_model_answers_with_same_prompt_and_copies_priority_answers(base_run, tmp_path):
    session = FakeOllama()
    counts = again(base_run, tmp_path / "out", session)
    assert counts == {"generated": 1, "copied": 1, "skipped": 0, "errors": 0, "truncated": 0}  # 실패했던 문항은 없다
    url, body = session.requests[0]
    assert url == "http://gana:11435/api/generate" and len(session.requests) == 1
    assert body["prompt"] == PROMPT and body["model"] == "gana-big" and body["think"] is False
    assert body["options"] == {"temperature": 0.0, "num_ctx": 16384, "num_predict": 512}  # 온도·출력 상한은 기준과 같게
    rows = runner.read_answers(tmp_path / "out")
    assert rows["ev-0001"]["answer"] == "전형료는 30,000원입니다."
    assert rows["ev-0001"]["eval_trace"]["stages"]["final"][0]["ledger_id"] == "gana/page/fee"  # 검색 기록은 그대로
    assert rows["ev-0001"]["eval_trace"]["runtime"]["llm_model"] == "gana-big"
    assert rows["ev-0002"]["answer"] == "표 근거 기준 답변입니다. 30,000원"
    manifest = json.loads((tmp_path / "out" / runner.MANIFEST).read_text())
    assert (manifest["mode"], manifest["generated_from"], manifest["evalset_version"]) == ("생성만", "base", "v2")
    assert manifest["runtime"] == {**BASE_RUNTIME, "llm_model": "gana-big", "num_ctx": 16384}
    assert manifest["counts"] == {"answered": 2, "errors": 0}


def test_result_folder_scores_like_a_run(base_run, tmp_path):
    again(base_run, tmp_path / "out", FakeOllama())
    result = metrics.score_run(tmp_path / "evalset.jsonl", tmp_path / "out")
    group = result["groups"]["본/dev"]
    # 모델 답은 맞음, 옮긴 우선 경로 답은 판정 대기(ADR-0028), 기준 실행에서 실패한 문항은 미실행
    assert (group["accuracy"]["k"], group["ambiguous_open"], group["not_run"]) == (1, 1, 1)


def test_resume_skips_done_and_retries_failures(base_run, tmp_path):
    first = again(base_run, tmp_path / "out", FakeOllama(down={PROMPT}))
    assert (first["generated"], first["copied"], first["errors"]) == (0, 1, 1)
    second = again(base_run, tmp_path / "out", FakeOllama())
    assert (second["generated"], second["skipped"], second["errors"]) == (1, 1, 0)
    assert runner.read_answers(tmp_path / "out")["ev-0001"]["answer"] == "전형료는 30,000원입니다."


def test_refuses_other_conditions_in_same_folder_and_writing_into_base(base_run, tmp_path):
    again(base_run, tmp_path / "out", FakeOllama())
    with pytest.raises(ValueError, match="llm_model"):
        again(base_run, tmp_path / "out", FakeOllama(), model="gana-other")
    with pytest.raises(ValueError, match="num_ctx"):
        again(base_run, tmp_path / "out", FakeOllama(), num_ctx=8192)
    with pytest.raises(ValueError, match="밖"):
        again(base_run, base_run, FakeOllama())


def test_prompt_filling_context_is_counted_as_truncated(base_run, tmp_path):
    counts = again(base_run, tmp_path / "out", FakeOllama(prompt_tokens=8191), num_ctx=8192)
    assert counts["truncated"] == 1
    assert runner.read_answers(tmp_path / "out")["ev-0001"]["eval_trace"]["generation"]["prompt_truncated"] is True
