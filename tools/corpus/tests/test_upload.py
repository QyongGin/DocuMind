"""`upload` 명령: 행 고르기, 파일 이름, 출처 칸, 이어 올리기, 409·실패·연속 실패 멈춤. 네트워크 없이 가짜 백엔드로."""

import pytest

from corpus import upload


def row(doc_id, **extra):
    base = {"doc_id": doc_id, "site": "www", "kind": "attach", "url": f"https://www.example.ac.kr/{doc_id}",
            "title": "수강신청 안내.hwp", "collected_at": "2026-10-02", "format": "hwp", "topic": "학사",
            "file_path": f"raw/{doc_id}.hwp", "sha256": f"sha-{doc_id}", "index_status": "색인", "split": "학습",
            "posted_at": "2026-08-01", "academic_year": 2026}
    base.update(extra)
    return base


def add_rows(ledger, tmp_path, *rows):
    for item in rows:
        ledger.upsert(item)
        path = tmp_path / item["file_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xd0\xcf\x11\xe0 synthetic")


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class FakeBackend:
    """백엔드 API 흉내. documents 응답은 파일 이름마다 정해 둘 수 있다."""

    def __init__(self, upload_results=None, progress_steps=None):
        self.headers = {}
        self.categories = {"학사": 1}
        self.uploads = []
        self.upload_results = upload_results or {}
        self.progress_steps = progress_steps or {}
        self.next_id = 100

    def post(self, url, json=None, files=None, data=None, timeout=None):
        if url.endswith("/api/auth/login"):
            if json["password"] != "pw":
                return FakeResponse(401, {"success": False, "message": "아이디 또는 비밀번호가 올바르지 않습니다."})
            return FakeResponse(200, {"success": True, "data": {"accessToken": "token"}})
        if url.endswith("/api/categories"):
            new_id = max(self.categories.values()) + 1
            self.categories[json["name"]] = new_id
            # 실제 백엔드(CategoryController)처럼 새로 만들면 201
            return FakeResponse(201, {"success": True, "data": {"id": new_id, "name": json["name"]}})
        if url.endswith("/api/documents"):
            filename = files["file"][0]
            self.uploads.append({"filename": filename, "fields": dict(data), "auth": self.headers.get("Authorization")})
            result = self.upload_results.get(filename)
            if result is not None:
                return result
            self.next_id += 1
            return FakeResponse(200, {"success": True, "data": {"documentId": self.next_id, "processingStatus": "PROCESSING"}})
        raise AssertionError(url)

    def get(self, url, timeout=None):
        if url.endswith("/api/categories"):
            return FakeResponse(200, {"success": True, "data": [{"id": i, "name": n} for n, i in self.categories.items()]})
        if "/progress" in url:
            document_id = int(url.split("/")[-2])
            steps = self.progress_steps.setdefault(document_id, ["processing", "completed"])
            status = steps.pop(0) if len(steps) > 1 else steps[0]
            message = "암호가 걸린 HWP는 읽을 수 없습니다." if status == "failed" else "처리 중"
            return FakeResponse(200, {"success": True, "data": {"status": status, "message": message}})
        raise AssertionError(url)


def make_uploader(ledger, tmp_path, backend, target="service"):
    client = upload.BackendClient("http://desktop.example/", backend)
    client.login("admin", "pw")
    logs = []
    return upload.Uploader(ledger.con, tmp_path, client, target, log=logs.append, sleep=lambda _: None), logs


def test_filename_follows_content_format_and_is_safe():
    assert upload.upload_filename("공고.hwp", "hwpx") == "공고.hwpx"
    assert upload.upload_filename("학과소개(항공)", "html") == "학과소개(항공).html"
    assert upload.upload_filename("a/b\\c.PDF", "pdf") == "a b c.pdf"
    assert len(upload.upload_filename("가" * 300, "pdf")) == 204


def test_source_fields_skip_non_http_urls():
    fields = upload.source_fields(row("www/bbs/1/a1", url="local:2026 모집요강.pdf", academic_year=None, posted_at=None))
    assert fields == {"ledgerId": "www/bbs/1/a1"}
    assert upload.source_fields(row("www/bbs/1/a2"))["academicYear"] == "2026"


def test_select_rows_by_target(ledger, tmp_path):
    add_rows(ledger, tmp_path,
             row("a/1"),
             row("a/2", index_status="보관"),
             row("a/3", format="image", file_path="raw/a/3.png"),
             row("a/4", index_status="보관", split="평가"))
    assert [r["doc_id"] for r in upload.select_rows(ledger.con, "service")] == ["a/1"]
    assert [r["doc_id"] for r in upload.select_rows(ledger.con, "dataset")] == ["a/1", "a/2"]
    assert upload.select_rows(ledger.con, "service", ["html"]) == []


def test_upload_waits_records_and_resumes(ledger, tmp_path):
    add_rows(ledger, tmp_path, row("a/1", topic="입시"), row("a/2", title="일정표.hwp"))
    backend = FakeBackend()
    uploader, logs = make_uploader(ledger, tmp_path, backend)

    counts = uploader.run(upload.select_rows(ledger.con, "service"))

    assert counts == {"ready": 2, "exists": 0, "failed": 0, "skipped_done": 0}
    first = backend.uploads[0]
    assert first["auth"] == "Bearer token"
    assert first["fields"] == {"ledgerId": "a/1", "sourceUrl": "https://www.example.ac.kr/a/1",
                               "sourcePostedAt": "2026-08-01", "academicYear": "2026", "categoryId": "2"}
    assert backend.categories["입시"] == 2  # 없던 주제는 카테고리로 만들었다
    assert ledger.get("a/1")["uploaded_document_id"] == 101  # 서비스 대상은 대장 칸도 채운다

    again = make_uploader(ledger, tmp_path, backend)[0].run(upload.select_rows(ledger.con, "service"))
    assert again["skipped_done"] == 2 and len(backend.uploads) == 2


def test_duplicate_and_failures_are_recorded(ledger, tmp_path):
    add_rows(ledger, tmp_path,
             row("a/1", title="같은 파일.hwp"),
             row("a/2", title="형식 오류.hwp"),
             row("a/3", title="암호.hwp"))
    backend = FakeBackend(
        upload_results={
            "같은 파일.hwp": upload_conflict(77),
            "형식 오류.hwp": FakeResponse(400, {"success": False, "message": "지원하지 않는 파일 형식입니다."}),
        },
        progress_steps={101: ["processing", "failed"]},
    )
    uploader, _ = make_uploader(ledger, tmp_path, backend)

    counts = uploader.run(upload.select_rows(ledger.con, "service"))

    assert counts["exists"] == 1 and counts["failed"] == 2
    statuses = dict(ledger.con.execute("SELECT doc_id, status FROM uploads").fetchall())
    reasons = dict(ledger.con.execute("SELECT doc_id, reason FROM uploads").fetchall())
    assert statuses == {"a/1": "exists", "a/2": "failed", "a/3": "failed"}
    assert ledger.get("a/1")["uploaded_document_id"] == 77
    assert "지원하지 않는" in reasons["a/2"] and "암호" in reasons["a/3"]

    # 실패한 행은 기본으로 건너뛰고, --retry-failed면 다시 올린다
    retry = make_uploader(ledger, tmp_path, FakeBackend())[0]
    assert retry.run(upload.select_rows(ledger.con, "service"))["skipped_done"] == 3
    assert retry.run(upload.select_rows(ledger.con, "service"), retry_failed=True)["ready"] == 2


def upload_conflict(existing_id):
    return FakeResponse(409, {"success": False, "message": "이미 올린 문서입니다: x",
                              "data": {"documentId": existing_id, "originalName": "x"}})


def test_same_file_rows_upload_once_for_dataset(ledger, tmp_path):
    add_rows(ledger, tmp_path, row("a/1", sha256="same"), row("a/2", sha256="same", file_path="raw/a/2.hwp"))
    backend = FakeBackend()
    uploader, _ = make_uploader(ledger, tmp_path, backend, target="dataset")

    counts = uploader.run(upload.select_rows(ledger.con, "dataset"))

    assert len(backend.uploads) == 1 and counts == {"ready": 1, "exists": 1, "failed": 0, "skipped_done": 0}
    ids = dict(ledger.con.execute("SELECT doc_id, document_id FROM uploads WHERE target='dataset'").fetchall())
    assert ids == {"a/1": 101, "a/2": 101}
    assert ledger.get("a/1")["uploaded_document_id"] is None  # 데이터셋 대상은 대장의 서비스 칸을 건드리지 않는다


def test_stops_after_five_consecutive_failures(ledger, tmp_path):
    rows = [row(f"a/{i}", title=f"문서{i}.hwp") for i in range(7)]
    add_rows(ledger, tmp_path, *rows)
    failing = {f"문서{i}.hwp": FakeResponse(500, {"success": False, "message": "AI 서버 문서 처리 중 오류가 발생했습니다."})
               for i in range(7)}
    uploader, _ = make_uploader(ledger, tmp_path, FakeBackend(upload_results=failing))

    with pytest.raises(upload.UploadStop, match="연속 5번"):
        uploader.run(upload.select_rows(ledger.con, "service"))
    assert ledger.con.execute("SELECT count(*) FROM uploads").fetchone()[0] == 5


def test_wrong_password_and_expired_token_stop(ledger, tmp_path):
    with pytest.raises(upload.UploadStop, match="로그인 실패"):
        upload.BackendClient("http://desktop.example", FakeBackend()).login("admin", "틀림")

    add_rows(ledger, tmp_path, row("a/1"))
    expired = FakeBackend(upload_results={"수강신청 안내.hwp": FakeResponse(401, {"success": False})})
    uploader, _ = make_uploader(ledger, tmp_path, expired)
    with pytest.raises(upload.UploadStop, match="권한"):
        uploader.run(upload.select_rows(ledger.con, "service"))
