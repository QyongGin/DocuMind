"""평가 실행기(M1 11번): AI 서버 /query(평가용 옵션)에 묻고 실행 폴더에 쌓기, 이어서 돌리기, 조건이 다르면 거부."""

import json

import pytest
import requests
from evalset_data import item

from corpus.evalset import runner, schema

RUNTIME = {"llm_model": "gana-llm", "llm_temperature": 0.0, "num_predict": 512}


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeSession:
    """AI 서버 대신. down이면 연결 실패, no_trace면 평가용 기록이 없는 옛 서버처럼 답한다."""

    def __init__(self, down: set[str] = frozenset(), no_trace: bool = False):
        self.down, self.no_trace, self.requests = set(down), no_trace, []

    def post(self, url, timeout, json):
        self.requests.append((url, json))
        if json["question"] in self.down:
            raise requests.ConnectionError("데스크탑 꺼짐")
        body = {"answer": "전형료는 30,000원입니다.", "sources": [{"document_id": "11", "chunk_index": 0}]}
        if not self.no_trace:
            body["eval_trace"] = {"answer_path": "llm", "stages": {}, "context": "", "prompt": "", "runtime": RUNTIME,
                                  "generation": {"done_reason": "stop"}}
        return FakeResponse(body)


@pytest.fixture
def evalset(tmp_path):
    path = tmp_path / "evalset.jsonl"
    schema.save(path, [item("ev-0001", part="dev"), item("ev-0002", question="가나대 정시 원서비는요?", part="test"),
                       item("ev-0003", question="버린 문항", review={"status": "버림"})])
    return path


def run(evalset, out, session, **extra):
    return runner.run(evalset, out, "http://gana:8000/", "gana-index", session=session, log=None,
                      now=lambda: "2026-10-12T21:00:00", **extra)


def test_run_writes_manifest_and_answers(evalset, tmp_path):
    session = FakeSession()
    summary = run(evalset, tmp_path / "run", session, version="v2")
    assert summary == {"asked": 2, "skipped": 0, "errors": 0}  # 버린 문항은 묻지 않는다
    url, body = session.requests[0]
    assert url == "http://gana:8000/query" and body["include_eval_trace"] is True and body["top_k"] == 8
    answers = runner.read_answers(tmp_path / "run")
    assert sorted(answers) == ["ev-0001", "ev-0002"] and answers["ev-0001"]["eval_trace"]["answer_path"] == "llm"
    manifest = json.loads((tmp_path / "run" / runner.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["evalset_sha256"] == schema.fingerprint(schema.load(evalset))
    assert (manifest["evalset_version"], manifest["index"], manifest["runtime"]) == ("v2", "gana-index", RUNTIME)
    assert manifest["counts"] == {"answered": 2, "errors": 0} and manifest["system_prompt_sha256"] == runner.sha256("")


def test_run_resumes_and_retries_only_failures(evalset, tmp_path):
    first = run(evalset, tmp_path / "run", FakeSession(down={"가나대 정시 원서비는요?"}))
    assert first == {"asked": 2, "skipped": 0, "errors": 1}
    second_session = FakeSession()
    second = run(evalset, tmp_path / "run", second_session)
    assert second == {"asked": 1, "skipped": 1, "errors": 0}
    assert [body["question"] for _, body in second_session.requests] == ["가나대 정시 원서비는요?"]
    assert "error" not in runner.read_answers(tmp_path / "run")["ev-0002"]  # 다시 물은 결과가 앞의 실패를 덮는다


def test_run_refuses_to_mix_conditions_in_one_folder(evalset, tmp_path):
    run(evalset, tmp_path / "run", FakeSession())
    with pytest.raises(ValueError, match="top_k"):
        run(evalset, tmp_path / "run", FakeSession(), top_k=3)
    with pytest.raises(ValueError, match="system_prompt_sha256"):
        run(evalset, tmp_path / "run", FakeSession(), system_prompt="관리자가 바꾼 프롬프트")


def test_run_marks_server_without_eval_trace_as_failure(evalset, tmp_path):
    summary = run(evalset, tmp_path / "run", FakeSession(no_trace=True), ids=["ev-0001"])
    assert summary["errors"] == 1
    assert "eval_trace" in runner.read_answers(tmp_path / "run")["ev-0001"]["error"]


def test_run_always_sends_retrieval_mode(evalset, tmp_path):
    plain = FakeSession()
    run(evalset, tmp_path / "plain", plain, ids=["ev-0001"])
    assert plain.requests[0][1]["retrieval_mode"] == "rrf"  # 기본값(운영 기본값)도 적어 보낸다
    manifest = json.loads((tmp_path / "plain" / runner.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["retrieval_mode"] == "rrf"
    rules = FakeSession()
    run(evalset, tmp_path / "rules", rules, ids=["ev-0001"], retrieval_mode="rules")
    assert rules.requests[0][1]["retrieval_mode"] == "rules"  # 서버 기본값이 바뀌어도 규칙 경로로 돈다
    with pytest.raises(ValueError, match="retrieval_mode"):  # 한 실행 폴더에 다른 검색 방식을 섞지 않는다
        run(evalset, tmp_path / "rules", FakeSession(), ids=["ev-0001"])


def test_run_reads_old_manifest_without_retrieval_mode_as_rules(evalset, tmp_path):
    run(evalset, tmp_path / "old", FakeSession(), ids=["ev-0001"], retrieval_mode="rules")
    path = tmp_path / "old" / runner.MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["retrieval_mode"]  # 이 옵션이 생기기 전의 실행 기록
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert run(evalset, tmp_path / "old", FakeSession(), retrieval_mode="rules")["skipped"] == 1
    with pytest.raises(ValueError, match="retrieval_mode"):  # 옛 기록에 지금 기본값(rrf)으로 이어 붙이지 않는다
        run(evalset, tmp_path / "old", FakeSession())
