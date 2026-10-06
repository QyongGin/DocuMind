"""명령줄 한 바퀴: check → split → (교차 확인 결과를 넣고) need → report → freeze, 그리고 PR 2 명령."""

import json
import subprocess

from evalset_data import build_corpus, item, ledger_row, refusal_item

from corpus.cli import main
from corpus.evalset import cli, cross, schema


def test_evalset_commands_end_to_end(ledger, tmp_path, capsys):
    build_corpus(ledger, tmp_path)
    ledger.close()
    path = tmp_path / "evalset.jsonl"
    schema.save(path, [
        item("ev-0001"),
        item("ev-0002", question="가나대 실기 추가 비용은?", tags=["표 근거"], forbidden=[],
             evidence=[{"doc": "gana/page/fee", "quote": "실기 추가 15,000원"}],
             facts=[{"name": "실기 추가", "values": ["15,000원"]}]),
        refusal_item("ev-0003"),
        item("ev-0004", question="틀린 인용", evidence=[{"doc": "gana/page/fee", "quote": "전형료 99,000원"}]),
    ])
    root = ["--root", str(tmp_path), "evalset", "--today", "2026-10-05"]

    assert main([*root, "check", str(path), "--write"]) == 1  # 돌려보낸 문항이 있으면 1
    out = capsys.readouterr().out
    assert "돌려보냄 ev-0004" in out and "통과 3 · 돌려보냄 1" in out
    saved = {entry["id"]: entry for entry in schema.load(path)}
    assert saved["ev-0001"]["machine"]["quote_ok"] is True and saved["ev-0001"]["topic"] == "입시"

    schema.save(path, [entry for entry in saved.values() if entry["id"] != "ev-0004"])  # 돌려보낸 문항은 초안으로
    assert main([*root, "split", str(path), "--seed", "11", "--write"]) == 0
    assert all(entry["part"] in ("연습", "실전") for entry in schema.load(path))

    assert main([*root, "need", str(path), "--seed", "11"]) == 1  # 교차 확인 전에는 고르지 않는다
    entries = schema.load(path)
    for entry in entries:
        entry["cross"] = {"verdict": "일치", "answer": entry["answer"]}
    schema.save(path, entries)
    assert main([*root, "need", str(path), "--seed", "11", "--write"]) == 0
    capsys.readouterr()

    assert main([*root, "report", str(path), "--cap", "gana/page/fee=1"]) == 0
    report = capsys.readouterr().out
    assert "본 문항 3/250" in report and "gana/page/fee 2/1" in report

    entries = schema.load(path)
    for entry in entries:
        if entry.get("need"):
            entry["review"] = {"status": "승인", "reason": "", "at": "2026-10-05T10:00:00", "sec": 40}
    schema.save(path, entries)
    assert main([*root, "freeze", str(path), "--version", "v1", "--index-backup", "20261004-201713", "--seed", "11"]) == 0
    frozen = (tmp_path / "frozen_v1.txt").read_text(encoding="utf-8")
    assert f"evalset_sha256: {schema.fingerprint(entries)}" in frozen

    assert main([*root, "judge", str(path), "--id", "ev-0001", "--answer", "3만 원"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["label"] == "맞음"


def test_cross_review_merge_and_freeze_commands(ledger, tmp_path, capsys, monkeypatch):
    """교차 확인(가짜 세션) → need → 검수 화면 → 검수 기록 합치기 → 고친 문항 다시 검사 → 고정."""
    build_corpus(ledger, tmp_path)
    ledger.close()
    path = tmp_path / "evalset.jsonl"
    schema.save(path, [item("ev-0001"), item("ev-0002", question="가나대 수시 원서비는?"), refusal_item("ev-0003")])
    root = ["--root", str(tmp_path), "evalset", "--today", "2026-10-06"]
    answers = {"ev-0001": "30,000원입니다.", "ev-0002": "25,000원입니다.", "ev-0003": "문서에서 확인할 수 없습니다."}

    def session(command, cwd):
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, "2.1.205 (Claude Code)", "")
        questions = json.loads((cwd / "questions.json").read_text(encoding="utf-8"))["questions"]
        reply = {"answers": [{"id": q["id"], "answer": answers[q["id"]]} for q in questions]}
        return subprocess.CompletedProcess(command, 0, json.dumps({"result": json.dumps(reply, ensure_ascii=False)}), "")

    monkeypatch.setattr(cross, "run_claude", session)
    assert main([*root, "check", str(path), "--write"]) == 0
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("지침", encoding="utf-8")
    assert main([*root, "cross", str(path), "--work", str(repo / "work")]) == 2  # 저장소 안 꾸러미 거부
    assert main([*root, "cross", str(path), "--work", str(tmp_path / "work"), "--dry-run"]) == 0
    assert (tmp_path / "work" / "p001" / "questions.json").exists()
    capsys.readouterr()
    record = tmp_path / "record"
    assert main([*root, "cross", str(path), "--work", str(tmp_path / "work2"), "--record-dir", str(record),
                 "--write"]) == 0
    assert "일치 2 · 불일치 1 · 애매 0" in capsys.readouterr().out and not (tmp_path / "work2").exists()
    assert {entry["id"]: entry["cross"]["verdict"] for entry in schema.load(path)} == {
        "ev-0001": "일치", "ev-0002": "불일치", "ev-0003": "일치"}

    entries = schema.load(path)
    for entry in entries:
        entry["part"] = "실전"
    schema.save(path, entries)
    assert main([*root, "need", str(path), "--seed", "3", "--write"]) == 0
    screen = tmp_path / "screen.html"
    assert main([*root, "review-html", str(path), "--out", str(screen)]) == 0
    html = screen.read_text(encoding="utf-8")
    assert '"id": "ev-0002"' in html and '"need": "불일치"' in html

    records = tmp_path / "검수기록.jsonl"
    records.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in (
        {"id": "ev-0001", "status": "승인", "reason": "", "changed": [], "sec": 30, "at": "2026-10-06T10:00:00"},
        {"id": "ev-0002", "status": "고침", "reason": "정답지가 맞고 질문만 다듬음", "changed": ["question"], "sec": 80,
         "at": "2026-10-06T10:02:00", "edits": {"question": "가나대 수시 1차 원서비는?"}},
        {"id": "ev-0003", "status": "승인", "reason": "", "changed": [], "sec": 20, "at": "2026-10-06T10:03:00"},
    )) + "\n", encoding="utf-8")
    assert main([*root, "merge", str(path), "--records", str(records), "--write"]) == 0
    assert "다시 해야 한다" in capsys.readouterr().out
    freeze = [*root, "freeze", str(path), "--version", "v1", "--index-backup", "b", "--seed", "3"]
    assert main(freeze) == 1  # 고친 문항은 기계 검사 전이라 고정하지 않는다
    assert capsys.readouterr().err.endswith("검사 전이거나 오류): ev-0002\n")
    assert main([*root, "check", str(path), "--write"]) == 0
    assert main(freeze) == 0


def test_fence_and_export_index_commands(ledger, tmp_path, capsys, monkeypatch):
    def leaky(command, cwd):
        key = (cwd.parent / "answer_key.json").read_text(encoding="utf-8")
        notice = (cwd / "docs" / "notice.txt").read_text(encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, json.dumps({"result": notice + key}), "")

    monkeypatch.setattr(cross, "run_claude", leaky)
    assert main(["--root", str(tmp_path), "evalset", "fence", "--work", str(tmp_path / "fence")]) == 1
    assert "새어 나옴: 예" in capsys.readouterr().out and not (tmp_path / "fence").exists()

    ledger.upsert(ledger_row("gana/page/fee"))
    ledger.con.execute("UPDATE ledger SET uploaded_document_id = 7 WHERE doc_id = 'gana/page/fee'")
    ledger.con.commit()
    ledger.close()

    class Backend:
        def __init__(self, base_url, session):
            self.base_url = base_url

        def login(self, username, password):
            assert (username, password) == ("admin", "pw")

        def chunks(self, document_id):
            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {"data": [{"chunkIndex": 0, "content": "전형료 30,000원"}]}
            return Response()

    monkeypatch.setattr(cli, "BackendClient", Backend)
    monkeypatch.setenv("DOCUMIND_ADMIN_PASSWORD", "pw")
    out = tmp_path / "index"
    assert main(["--root", str(tmp_path), "evalset", "export-index", "--base-url", "http://gana.test",
                 "--index-backup", "20261004-201713", "--out", str(out)]) == 0
    assert (out / "gana__page__fee.txt").read_text(encoding="utf-8") == "전형료 30,000원"
    assert main(["--root", str(tmp_path), "evalset", "export-index", "--base-url", "gana.test",
                 "--index-backup", "b"]) == 2
