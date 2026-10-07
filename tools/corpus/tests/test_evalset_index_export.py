"""색인 글 내보내기(결정 ④-6): 백엔드 청크 API를 가짜로 바꿔 문서별 파일·기록을 확인한다."""

import hashlib
import json
from datetime import datetime

import pytest
from evalset_data import ledger_row

from corpus.evalset import index_export
from corpus.upload import UploadStop


class Response:
    def __init__(self, status_code: int, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        return {"success": True, "data": self._data}


class FakeBackend:
    def __init__(self, responses: dict[int, Response]):
        self.responses = responses
        self.asked = []

    def chunks(self, document_id: int):
        self.asked.append(document_id)
        return self.responses[document_id]


def indexed(ledger):
    """서비스에 올린 문서 4개, 보관 1개, 아직 안 올린 색인 문서 1개. 문서 번호는 업로드처럼 따로 적는다."""
    uploaded = {"gana/page/fee": 11, "gana/page/leave": 12, "gana/page/empty": 13, "gana/page/broken": 14,
                "gana/page/archived": 15}
    for doc_id in (*uploaded, "gana/page/notyet"):
        ledger.upsert(ledger_row(doc_id, index_status="보관" if doc_id.endswith("archived") else "색인"))
    for doc_id, document_id in uploaded.items():
        ledger.con.execute("UPDATE ledger SET uploaded_document_id = ? WHERE doc_id = ?", (document_id, doc_id))
    ledger.con.commit()


def test_export_writes_chunks_in_order_with_manifest(ledger, tmp_path):
    indexed(ledger)
    backend = FakeBackend({
        11: Response(200, [{"chunkIndex": 1, "content": "| 전형료 | 30,000원 |\n"},
                           {"chunkIndex": 0, "content": "## 전형료 안내"}]),
        12: Response(200, [{"chunkIndex": 0, "content": "휴학원서 1부"}]),
        13: Response(200, []),
        14: Response(500),
    })
    result = index_export.export(backend, ledger, tmp_path / "out", "http://gana.test", "20261004-201713",
                                 datetime(2026, 10, 6, 9, 0))
    assert backend.asked == [14, 13, 11, 12]  # 대장 ID 순, 색인 문서만
    assert result["targets"] == 4 and result["written"] == 2
    assert result["failed"] == [("gana/page/broken", "HTTP 500"), ("gana/page/empty", "청크 0개")]
    text = (tmp_path / "out" / "gana__page__fee.txt").read_text(encoding="utf-8")
    assert text == "## 전형료 안내\n\n| 전형료 | 30,000원 |"
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["index_backup"] == "20261004-201713" and manifest["base_url"] == "http://gana.test"
    assert manifest["documents"]["gana/page/fee"] == {"document_id": 11, "chunks": 2, "chars": len(text),
                                                      "sha256": hashlib.sha256(text.encode()).hexdigest()}
    assert manifest["failed"] == {"gana/page/broken": "HTTP 500", "gana/page/empty": "청크 0개"}


def test_export_stops_on_auth_error(ledger, tmp_path):
    indexed(ledger)
    with pytest.raises(UploadStop, match="권한 오류"):
        index_export.export(FakeBackend({14: Response(401)}), ledger, tmp_path / "out", "http://gana.test",
                            "b", datetime(2026, 10, 6))
