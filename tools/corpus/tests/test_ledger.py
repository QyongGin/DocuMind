"""문서 대장: 값 목록 제약, 확인 칸 보호, CSV 왕복, 제외 원본 삭제."""

import csv
import sqlite3

import pytest

from corpus.ledger import CSV_COLUMNS


def row(doc_id="www/page/1", **extra):
    base = {"doc_id": doc_id, "site": "www", "kind": "page", "url": "https://x/1", "title": "제목",
            "collected_at": "2026-10-02", "format": "html", "topic": "학사"}
    base.update(extra)
    return base


def test_defaults_and_check_constraints(ledger):
    ledger.upsert(row())
    saved = ledger.get("www/page/1")
    assert (saved["pii_status"], saved["split"], saved["visibility"], saved["reviewed"]) == ("통과", "미정", "공개", 0)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.upsert(row("www/page/2", format="gif"))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.upsert(row("www/page/3", topic="잡담"))


def test_reviewed_columns_survive_recollection(ledger):
    ledger.upsert(row(topic="학사", group_id="안내:가"))
    ledger.con.execute("UPDATE ledger SET topic = '입시', group_id = '안내:나', reviewed = 1")
    ledger.upsert(row(topic="학사", group_id="안내:가", title="바뀐 제목", size_bytes=10))
    saved = ledger.get("www/page/1")
    assert (saved["topic"], saved["group_id"]) == ("입시", "안내:나")  # 사람이 확인한 칸은 그대로
    assert (saved["title"], saved["size_bytes"]) == ("바뀐 제목", 10)  # 자동 칸은 갱신


def test_unreviewed_suggestions_are_refreshed(ledger):
    ledger.upsert(row(topic="학사"))
    ledger.upsert(row(topic="입시"))
    assert ledger.get("www/page/1")["topic"] == "입시"


def test_csv_round_trip(ledger, tmp_path):
    ledger.upsert(row("www/page/1"))
    ledger.upsert(row("www/page/2", pii_status="보류", pii_reason="1차 제목·파일명: 명단"))
    path = tmp_path / "review.csv"
    assert ledger.export_review(path) == 2
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # 엑셀이 한글을 바로 읽도록 BOM
    with open(path, encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    assert list(records[0]) == CSV_COLUMNS
    records[1].update(pii_status="제외", reviewed="1", academic_year="2026", notes="명단 확인")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    assert ledger.import_review(path) == 2
    saved = ledger.get("www/page/2")
    assert (saved["pii_status"], saved["reviewed"], saved["academic_year"], saved["notes"]) == ("제외", 1, 2026, "명단 확인")
    assert ledger.export_review(path, only_unreviewed=True) == 1


def test_import_rejects_unknown_rows_and_bad_values(ledger, tmp_path):
    ledger.upsert(row())
    path = tmp_path / "review.csv"
    ledger.export_review(path)
    text = path.read_text(encoding="utf-8-sig")
    path.write_text(text.replace("www/page/1", "www/page/999"), encoding="utf-8-sig")
    with pytest.raises(KeyError):
        ledger.import_review(path)
    path.write_text(text.replace(",통과,", ",괜찮음,"), encoding="utf-8-sig")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.import_review(path)


def test_purge_excluded_removes_original_and_twins(ledger, tmp_path):
    original = tmp_path / "raw" / "www" / "bbs" / "1" / "a1.hwp"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"list")
    shared = {"file_path": "raw/www/bbs/1/a1.hwp", "sha256": "abc", "kind": "attach", "format": "hwp"}
    ledger.upsert(row("www/bbs/1/a1", **shared, pii_status="제외", reviewed=1))
    ledger.upsert(row("www/bbs/2/a9", **shared))
    removed = ledger.purge_excluded(tmp_path)
    assert removed == ["raw/www/bbs/1/a1.hwp"] and not original.exists()
    for doc_id in ("www/bbs/1/a1", "www/bbs/2/a9"):
        saved = ledger.get(doc_id)
        assert saved["file_path"] is None and saved["pii_status"] == "제외" and saved["index_status"] == "제외"
        assert saved["url"]  # 주소는 남는다


def test_visits_and_reopen(ledger):
    assert not ledger.visited("www/bbs/11/1")
    ledger.mark_visited("www/bbs/11/1")
    assert ledger.visited("www/bbs/11/1")
    ledger.upsert(row(reviewed=1))
    ledger.reopen("www/page/1", "2차 본문: 휴대전화")
    saved = ledger.get("www/page/1")
    assert (saved["pii_status"], saved["reviewed"], saved["index_status"]) == ("보류", 0, "제외")
