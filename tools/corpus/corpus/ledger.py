"""문서 대장: SQLite 파일 하나가 원본이고, 사람이 확인할 칸만 CSV로 왕복한다.

한 행 = 파일 하나(안내 페이지 HTML, 글 본문, 첨부 각각). 형식 정의는 M1-1 결정을 따른다.
다시 수집해도 사람이 확인한 칸(`reviewed=1`)은 덮어쓰지 않는다.
"""

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
  doc_id TEXT PRIMARY KEY,
  parent_id TEXT,
  site TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('page','post','attach','viewer','file','faq')),
  board TEXT,
  post_no TEXT,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  posted_at TEXT,
  collected_at TEXT NOT NULL,
  file_path TEXT,
  format TEXT NOT NULL CHECK (format IN ('html','pdf','hwp','hwpx','docx','xlsx','pptx','image','etc')),
  sha256 TEXT,
  size_bytes INTEGER,
  text_chars INTEGER,
  table_count INTEGER,
  image_heavy INTEGER CHECK (image_heavy IN (0,1)),
  topic TEXT CHECK (topic IN ('입시','학사','장학·등록금','학과·캠퍼스 생활','기타')),
  academic_year INTEGER,
  revised_at TEXT,
  valid_until TEXT,
  aliases TEXT,
  group_id TEXT,
  pii_status TEXT NOT NULL CHECK (pii_status IN ('통과','보류','가림','제외')),
  pii_reason TEXT,
  third_party TEXT,
  visibility TEXT NOT NULL DEFAULT '공개' CHECK (visibility IN ('공개','내부')),
  index_status TEXT CHECK (index_status IN ('색인','보관','제외')),
  split TEXT NOT NULL DEFAULT '미정' CHECK (split IN ('학습','평가','미정')),
  uploaded_document_id INTEGER,
  reviewed INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0,1)),
  notes TEXT
);
CREATE INDEX IF NOT EXISTS ledger_sha256 ON ledger(sha256);
CREATE INDEX IF NOT EXISTS ledger_parent ON ledger(parent_id);
CREATE TABLE IF NOT EXISTS failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  url TEXT NOT NULL,
  doc_id TEXT,
  stage TEXT NOT NULL,
  error TEXT NOT NULL
);
-- 이어 받기: 끝까지 처리한 단위(페이지·글·FAQ 게시판 등). 실패가 있었던 단위는 넣지 않아 다음에 다시 시도한다
CREATE TABLE IF NOT EXISTS visits (
  unit TEXT PRIMARY KEY,
  at TEXT NOT NULL
);
-- 업로드 기록(`upload` 명령): 대상(service·dataset)마다 대장 행이 어느 문서 번호로 올라갔는지. 다시 실행하면 이어 올린다
CREATE TABLE IF NOT EXISTS uploads (
  target TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  sha256 TEXT,
  document_id INTEGER,
  status TEXT NOT NULL CHECK (status IN ('ready','exists','failed')),
  reason TEXT,
  base_url TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (target, doc_id)
);
"""

# 사람이 확인하는 칸. 확인 뒤(reviewed=1)에는 수집기가 바꾸지 않는다
REVIEW_COLUMNS = [
    "topic", "academic_year", "revised_at", "valid_until", "aliases", "group_id",
    "pii_status", "pii_reason", "third_party", "index_status", "split", "notes",
]
# 수집기가 매번 채우는 칸
MACHINE_COLUMNS = [
    "parent_id", "site", "kind", "board", "post_no", "url", "title", "posted_at",
    "collected_at", "file_path", "format", "sha256", "size_bytes", "text_chars",
    "table_count", "image_heavy", "visibility",
]
CSV_COLUMNS = ["doc_id", "title", "format", "url", *REVIEW_COLUMNS, "reviewed"]
INTEGER_COLUMNS = {"academic_year", "reviewed"}


def grouped_failures(con: sqlite3.Connection) -> dict:
    return {row[0]: row[1] for row in con.execute("SELECT stage, count(*) FROM failures GROUP BY stage")}


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def close(self) -> None:
        self.con.close()

    def get(self, doc_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM ledger WHERE doc_id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def has(self, doc_id: str) -> bool:
        return self.get(doc_id) is not None

    def find_by_sha256(self, sha256: str) -> dict | None:
        row = self.con.execute(
            "SELECT * FROM ledger WHERE sha256 = ? ORDER BY doc_id LIMIT 1", (sha256,)
        ).fetchone()
        return dict(row) if row else None

    def upsert(self, row: dict) -> None:
        """새 행은 그대로 넣고, 있는 행은 자동 칸만 갱신한다(확인 전이면 제안 칸도 갱신)."""
        existing = self.get(row["doc_id"])
        if existing is None:
            columns = ["doc_id", *MACHINE_COLUMNS, *REVIEW_COLUMNS]
            values = [row.get(column) for column in columns]
            values[columns.index("pii_status")] = row.get("pii_status") or "통과"
            values[columns.index("split")] = row.get("split") or "미정"
            values[columns.index("visibility")] = row.get("visibility") or "공개"
            placeholders = ",".join("?" * len(columns))
            self.con.execute(f"INSERT INTO ledger ({','.join(columns)}) VALUES ({placeholders})", values)
        else:
            update = [column for column in MACHINE_COLUMNS if column in row]
            if not existing["reviewed"]:
                update += [column for column in REVIEW_COLUMNS if column in row]
            if update:
                assignments = ", ".join(f"{column} = ?" for column in update)
                self.con.execute(
                    f"UPDATE ledger SET {assignments} WHERE doc_id = ?",
                    [row[column] for column in update] + [row["doc_id"]],
                )
        self.con.commit()

    def children(self, parent_id: str) -> list[dict]:
        rows = self.con.execute("SELECT * FROM ledger WHERE parent_id = ? ORDER BY doc_id", (parent_id,))
        return [dict(row) for row in rows]

    def approved_pending_under(self, prefix: str) -> bool:
        """ID가 prefix로 시작하는 행 중 사람이 1차 보류를 풀어 줬지만 아직 받지 않은 행이 있는가."""
        row = self.con.execute(
            "SELECT 1 FROM ledger WHERE doc_id LIKE ? AND reviewed = 1 AND pii_status = '통과' AND file_path IS NULL",
            (prefix.replace("%", "") + "%",),
        ).fetchone()
        return row is not None

    def visited(self, unit: str) -> bool:
        return self.con.execute("SELECT 1 FROM visits WHERE unit = ?", (unit,)).fetchone() is not None

    def mark_visited(self, unit: str) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO visits (unit, at) VALUES (?, ?)",
            (unit, datetime.now().isoformat(timespec="seconds")),
        )
        self.con.commit()

    def reopen(self, doc_id: str, reason: str) -> None:
        """사람이 확인한 뒤 새로 받은 내용에서 개인정보 패턴이 나오면 다시 확인 대기로 돌린다."""
        self.con.execute(
            "UPDATE ledger SET pii_status = '보류', pii_reason = ?, index_status = '제외', reviewed = 0 WHERE doc_id = ?",
            (reason, doc_id),
        )
        self.con.commit()

    def purge_excluded(self, corpus_root: str | Path) -> list[str]:
        """개인정보 `제외`로 확정한 파일의 원본을 지우고 주소만 남긴다(수집 규칙 ⑨).

        같은 파일을 가리키는 다른 행(내용 중복)도 같은 내용이므로 함께 제외한다.
        """
        root = Path(corpus_root)
        removed = []
        rows = self.con.execute(
            "SELECT doc_id, file_path FROM ledger WHERE pii_status = '제외' AND file_path IS NOT NULL"
        ).fetchall()
        for doc_id, file_path in rows:
            target = root / file_path
            if target.exists():
                target.unlink()
                removed.append(file_path)
            self.con.execute(
                "UPDATE ledger SET pii_status = '제외', pii_reason = coalesce(pii_reason, ?), index_status = '제외', "
                "file_path = NULL WHERE file_path = ? AND doc_id != ? AND pii_status != '제외'",
                (f"같은 파일이 제외됨: {doc_id}", file_path, doc_id),
            )
            self.con.execute(
                "UPDATE ledger SET file_path = NULL, index_status = '제외' WHERE file_path = ?", (file_path,)
            )
        self.con.commit()
        return removed

    def add_failure(self, url: str, stage: str, error: str, doc_id: str | None = None) -> None:
        self.con.execute(
            "INSERT INTO failures (at, url, doc_id, stage, error) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), url, doc_id, stage, error[:500]),
        )
        self.con.commit()

    def export_review(self, csv_path: str | Path, only_unreviewed: bool = False) -> int:
        """사람이 확인할 칸만 CSV로 내보낸다. 엑셀에서 바로 열리게 UTF-8 BOM으로 쓴다."""
        where = "WHERE reviewed = 0" if only_unreviewed else ""
        rows = self.con.execute(f"SELECT {','.join(CSV_COLUMNS)} FROM ledger {where} ORDER BY doc_id").fetchall()
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_COLUMNS)
            for row in rows:
                writer.writerow(["" if value is None else value for value in row])
        return len(rows)

    def import_review(self, csv_path: str | Path) -> int:
        """CSV의 확인 칸을 대장에 반영한다. 값 목록에 없는 값은 CHECK 제약으로 막힌다."""
        updated = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            for record in csv.DictReader(handle):
                if not self.has(record["doc_id"]):
                    raise KeyError(f"대장에 없는 doc_id: {record['doc_id']}")
                columns = [*REVIEW_COLUMNS, "reviewed"]
                values = []
                for column in columns:
                    value = (record.get(column) or "").strip()
                    if value == "":
                        value = None
                    elif column in INTEGER_COLUMNS:
                        value = int(value)
                    values.append(value)
                values[columns.index("pii_status")] = values[columns.index("pii_status")] or "통과"
                values[columns.index("split")] = values[columns.index("split")] or "미정"
                values[columns.index("reviewed")] = values[columns.index("reviewed")] or 0
                assignments = ", ".join(f"{column} = ?" for column in columns)
                self.con.execute(f"UPDATE ledger SET {assignments} WHERE doc_id = ?", values + [record["doc_id"]])
                updated += 1
        self.con.commit()
        return updated

    def stats(self) -> dict:
        def grouped(column: str) -> dict:
            return {
                (row[0] if row[0] is not None else "(없음)"): row[1]
                for row in self.con.execute(f"SELECT {column}, count(*) FROM ledger GROUP BY {column}")
            }

        attachments = {
            row[0]: {"files": row[1], "bytes": row[2], "avg_bytes": round(row[3] or 0), "avg_chars": round(row[4] or 0)}
            for row in self.con.execute(
                "SELECT format, count(*), sum(size_bytes), avg(size_bytes), avg(text_chars) FROM ledger "
                "WHERE kind = 'attach' AND file_path IS NOT NULL GROUP BY format"
            )
        }
        return {
            "rows": self.con.execute("SELECT count(*) FROM ledger").fetchone()[0],
            "failures": self.con.execute("SELECT count(*) FROM failures").fetchone()[0],
            "failure_stages": grouped_failures(self.con),
            "attachments": attachments,
            "format": grouped("format"),
            "kind": grouped("kind"),
            "topic": grouped("topic"),
            "pii_status": grouped("pii_status"),
            "index_status": grouped("index_status"),
            "split": grouped("split"),
            "bytes": self.con.execute("SELECT coalesce(sum(size_bytes), 0) FROM ledger").fetchone()[0],
            "text_chars": self.con.execute("SELECT coalesce(sum(text_chars), 0) FROM ledger").fetchone()[0],
        }
