"""명령줄 한 바퀴: check → split → (교차 확인 결과를 넣고) need → report → freeze."""

import json

from evalset_data import build_corpus, item, refusal_item

from corpus.cli import main
from corpus.evalset import schema


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
