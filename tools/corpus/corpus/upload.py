"""대장 행을 서비스 백엔드 API로 올린다(`python -m corpus upload`, 이슈 #126 결정 3).

- 올릴 행: `service`(서비스 색인, index_status='색인') / `dataset`(데이터셋용 색인, 학습 몫·개인정보 통과)
- 로그인: 관리자 비밀번호는 실행할 때 입력한다(저장하지 않음). 환경변수 DOCUMIND_ADMIN_PASSWORD가 있으면 그 값
- 한 문서씩 올리고 진행률로 처리가 끝날 때까지 기다린 뒤 다음 문서로 간다. 백엔드 문서 처리 실행기가
  스레드 1개·대기열 20칸이라, 기다리지 않고 보내면 거절된다
- 결과는 대장의 `uploads` 표(대상·대장 ID·문서 번호·상태·이유, 스키마는 ledger.py)에 적어 다시 실행하면 이어 올린다
- 409(같은 파일)는 'exists', 실패는 'failed'(이유 포함)로 적는다. 실패가 연속 5번이면 멈춘다
- 파일 이름은 대장 제목에 내용 형식의 확장자를 붙인 것, 주제는 같은 이름의 카테고리(없으면 만든다)
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

USER_AGENT = "DocuMind-corpus-uploader/0.1"
UPLOAD_FORMATS = ("html", "pdf", "hwp", "hwpx", "docx", "xlsx", "pptx")
EXTENSION_BY_FORMAT = {fmt: fmt for fmt in UPLOAD_FORMATS}
MIME_BY_FORMAT = {
    "html": "text/html",
    "pdf": "application/pdf",
    "hwp": "application/x-hwp",
    "hwpx": "application/hwp+zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
KNOWN_EXTENSIONS = re.compile(r"\.(html?|pdf|hwpx?|docx|xlsx|pptx)$", re.IGNORECASE)
MAX_CONSECUTIVE_FAILURES = 5
POLL_SECONDS = 2.0
DOCUMENT_TIMEOUT_SECONDS = 30 * 60

# 대상별로 올릴 행. 글을 꺼낼 수 있는 형식만, 원본 파일이 있는 행만
SELECTIONS = {
    "service": "index_status = '색인'",
    "dataset": "split = '학습' AND pii_status = '통과'",
}

class UploadStop(Exception):
    """더 올리면 안 되는 상황(로그인 실패·권한·연속 실패)."""


@dataclass(frozen=True)
class Result:
    status: str  # ready | exists | failed
    document_id: int | None = None
    reason: str | None = None


def upload_filename(title: str, fmt: str) -> str:
    """대장 제목에서 문서 확장자를 떼고 내용 형식의 확장자를 붙인다(예: '.hwp'로 올린 HWPX → '.hwpx').

    백엔드는 확장자와 파일 서명이 맞아야 받는다. 경로 구분자·제어 문자는 바꾸고 200자로 줄인다.
    """
    base = KNOWN_EXTENSIONS.sub("", title.strip()) or "문서"
    base = re.sub(r"[\x00-\x1f/\\]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()[:200]
    return f"{base}.{EXTENSION_BY_FORMAT[fmt]}"


def select_rows(con: sqlite3.Connection, target: str, formats: list[str] | None = None) -> list[dict]:
    """대상의 올릴 행을 대장 ID 순서로 고른다."""
    allowed = [fmt for fmt in (formats or UPLOAD_FORMATS) if fmt in UPLOAD_FORMATS]
    placeholders = ",".join("?" * len(allowed))
    query = (
        f"SELECT * FROM ledger WHERE {SELECTIONS[target]} AND file_path IS NOT NULL "
        f"AND format IN ({placeholders}) ORDER BY doc_id"
    )
    con.row_factory = sqlite3.Row
    return [dict(row) for row in con.execute(query, allowed)]


def source_fields(row: dict) -> dict:
    """업로드 API의 출처 칸(대장 ID·원래 주소·게시일·학년도). http(s)가 아닌 주소(local: 등)는 보내지 않는다."""
    fields = {"ledgerId": row["doc_id"]}
    url = row.get("url") or ""
    if url.startswith(("http://", "https://")):
        fields["sourceUrl"] = url
    if row.get("posted_at"):
        fields["sourcePostedAt"] = row["posted_at"]
    if row.get("academic_year"):
        fields["academicYear"] = str(row["academic_year"])
    return fields


class BackendClient:
    """백엔드 API(화면의 `/api` 경로)를 부른다. 요청 하나가 실패하면 예외 대신 응답을 그대로 돌려준다."""

    def __init__(self, base_url: str, session):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.session.headers.update({"User-Agent": USER_AGENT})

    def login(self, username: str, password: str) -> None:
        response = self.session.post(f"{self.base_url}/api/auth/login",
                                     json={"username": username, "password": password}, timeout=30)
        if response.status_code != 200:
            raise UploadStop(f"로그인 실패({response.status_code}). 아이디·비밀번호와 주소를 확인하세요.")
        token = response.json()["data"]["accessToken"]
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def category_ids(self, names: set[str]) -> dict[str, int]:
        """이름 → 카테고리 번호. 없는 이름은 만든다."""
        response = self.session.get(f"{self.base_url}/api/categories", timeout=30)
        self._raise_for_auth(response)
        ids = {item["name"]: item["id"] for item in response.json()["data"]}
        for name in sorted(names - set(ids)):
            created = self.session.post(f"{self.base_url}/api/categories", json={"name": name}, timeout=30)
            self._raise_for_auth(created)
            # 백엔드는 새로 만들면 201 Created를 돌려준다(CategoryController)
            if not 200 <= created.status_code < 300:
                raise UploadStop(f"카테고리 '{name}'를 만들지 못했습니다({created.status_code}).")
            ids[name] = created.json()["data"]["id"]
        return ids

    def upload(self, path: Path, filename: str, mime: str, fields: dict):
        with open(path, "rb") as file:
            return self.session.post(
                f"{self.base_url}/api/documents",
                files={"file": (filename, file, mime)},
                data=fields,
                timeout=(10, 900),
            )

    def progress(self, document_id: int):
        return self.session.get(f"{self.base_url}/api/documents/{document_id}/progress", timeout=30)

    def chunks(self, document_id: int):
        """문서의 색인 청크(관리자 문서 점검 화면과 같은 API). 평가셋 색인 글 내보내기에 쓴다."""
        return self.session.get(f"{self.base_url}/api/documents/{document_id}/chunks", timeout=60)

    @staticmethod
    def _raise_for_auth(response) -> None:
        if response.status_code in (401, 403):
            raise UploadStop(f"권한 오류({response.status_code}). 다시 로그인해 이어서 실행하세요.")


def _message(response) -> str:
    try:
        return response.json().get("message") or f"HTTP {response.status_code}"
    except ValueError:
        return f"HTTP {response.status_code}"


class Uploader:
    def __init__(self, con: sqlite3.Connection, corpus_root: Path, client: BackendClient, target: str,
                 log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.con = con
        self.root = corpus_root
        self.client = client
        self.target = target
        self.log = log
        self.sleep = sleep
        self.clock = clock

    def done_ids(self, retry_failed: bool) -> set[str]:
        statuses = ("ready", "exists") if retry_failed else ("ready", "exists", "failed")
        rows = self.con.execute(
            f"SELECT doc_id FROM uploads WHERE target = ? AND status IN ({','.join('?' * len(statuses))})",
            (self.target, *statuses),
        )
        return {row[0] for row in rows}

    def record(self, row: dict, result: Result) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO uploads (target, doc_id, sha256, document_id, status, reason, base_url, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (self.target, row["doc_id"], row.get("sha256"), result.document_id, result.status, result.reason,
             self.client.base_url),
        )
        if self.target == "service" and result.document_id is not None and result.status in ("ready", "exists"):
            self.con.execute("UPDATE ledger SET uploaded_document_id = ? WHERE doc_id = ?",
                             (result.document_id, row["doc_id"]))
        self.con.commit()

    def wait(self, document_id: int) -> Result:
        """처리가 끝날 때까지 진행률을 본다."""
        deadline = self.clock() + DOCUMENT_TIMEOUT_SECONDS
        while self.clock() < deadline:
            response = self.client.progress(document_id)
            BackendClient._raise_for_auth(response)
            if response.status_code == 200:
                data = response.json()["data"]
                if data.get("status") == "completed":
                    return Result("ready", document_id)
                if data.get("status") == "failed":
                    return Result("failed", document_id, data.get("message"))
            self.sleep(POLL_SECONDS)
        return Result("failed", document_id, "처리 시간 초과(30분)")

    def upload_one(self, row: dict, category_id: int | None) -> Result:
        fields = source_fields(row)
        if category_id is not None:
            fields["categoryId"] = str(category_id)
        filename = upload_filename(row["title"], row["format"])
        try:
            response = self.client.upload(self.root / row["file_path"], filename, MIME_BY_FORMAT[row["format"]], fields)
        except OSError as error:
            return Result("failed", reason=f"보내지 못함: {error.__class__.__name__}")
        BackendClient._raise_for_auth(response)
        if response.status_code == 409:
            existing = (response.json().get("data") or {}).get("documentId")
            return Result("exists", existing, _message(response))
        if response.status_code != 200:
            return Result("failed", reason=_message(response))
        data = response.json()["data"]
        document_id = data["documentId"]
        if data.get("processingStatus") == "PROCESSING":
            return self.wait(document_id)
        if data.get("processingStatus") == "FAILED":
            return Result("failed", document_id, "처리 실패")
        return Result("ready", document_id)

    def run(self, rows: list[dict], retry_failed: bool = False, limit: int | None = None) -> dict:
        done = self.done_ids(retry_failed)
        pending = [row for row in rows if row["doc_id"] not in done]
        if limit is not None:
            pending = pending[:limit]
        counts = {"ready": 0, "exists": 0, "failed": 0, "skipped_done": sum(1 for row in rows if row["doc_id"] in done)}
        categories = self.client.category_ids({row["topic"] for row in pending if row.get("topic")})
        uploaded_by_sha: dict[str, int] = {}
        consecutive_failures = 0
        for number, row in enumerate(pending, start=1):
            started = self.clock()
            sha = row.get("sha256")
            if sha and sha in uploaded_by_sha:
                # 같은 파일을 여러 대장 행이 가리킨다(데이터셋 몫). 한 번만 올리고 나머지는 같은 문서로 적는다
                result = Result("exists", uploaded_by_sha[sha], "같은 파일을 이번 실행에서 이미 올림")
            else:
                result = self.upload_one(row, categories.get(row.get("topic")))
            if sha and result.document_id is not None and result.status in ("ready", "exists"):
                uploaded_by_sha[sha] = result.document_id
            self.record(row, result)
            counts[result.status] += 1
            label = f"#{result.document_id}" if result.document_id is not None else "-"
            reason = f" · {result.reason}" if result.status == "failed" and result.reason else ""
            self.log(f"[{number}/{len(pending)}] {result.status} {label} {row['doc_id']}"
                     f" ({self.clock() - started:.1f}s){reason}")
            consecutive_failures = consecutive_failures + 1 if result.status == "failed" else 0
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise UploadStop(f"연속 {MAX_CONSECUTIVE_FAILURES}번 실패해 멈춥니다. 서버 상태를 확인한 뒤 다시 실행하세요"
                                 " (끝난 문서는 건너뛰고, 실패한 문서는 --retry-failed로 다시 올림).")
        return counts
