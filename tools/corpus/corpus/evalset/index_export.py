"""색인 글 내보내기(결정 ④-6): 서비스 색인의 청크 글을 문서별 파일로 받는다.

맥북에서 백엔드 API(`/api/documents/{id}/chunks`, 관리자)를 부른다. 데스크탑이 켜져 있고 챗봇이 떠 있어야 한다.
받은 글은 기계 검사의 인용 대조(`check --index-dir`), 검수 화면의 근거 원문, 거절 문항의 부재 확인에 쓴다.
학교 글이므로 저장소 밖(`Assets/eval/index_text/<색인 백업 이름>/`)에 둔다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..ledger import Ledger
from ..upload import BackendClient, UploadStop
from .checks import index_text_name


def rows(ledger: Ledger) -> list[tuple[str, int]]:
    """서비스 색인에 올라간 문서: (대장 ID, 문서 번호)."""
    return [(row[0], int(row[1])) for row in ledger.con.execute(
        "SELECT doc_id, uploaded_document_id FROM ledger WHERE index_status = '색인' "
        "AND uploaded_document_id IS NOT NULL ORDER BY doc_id")]


def chunk_text(chunks: list[dict]) -> str:
    """청크를 순서대로 이은 글. 청크 사이에는 빈 줄 하나."""
    ordered = sorted(chunks, key=lambda chunk: int(chunk.get("chunkIndex") or 0))
    return "\n\n".join(str(chunk.get("content") or "").strip("\n") for chunk in ordered)


def export(client: BackendClient, ledger: Ledger, out_dir: Path, base_url: str, index_backup: str, now: datetime,
           limit: int | None = None) -> dict:
    """문서마다 `<대장 ID 파일 이름>.txt`와 `manifest.json`(문서 번호·청크 수·글자 수·SHA-256)을 쓴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = rows(ledger)[:limit] if limit else rows(ledger)
    manifest: dict[str, dict] = {}
    failed: list[tuple[str, str]] = []
    for doc_id, document_id in targets:
        response = client.chunks(document_id)
        if response.status_code in (401, 403):
            raise UploadStop(f"권한 오류({response.status_code}). 다시 로그인해 실행하세요.")
        if response.status_code != 200:
            failed.append((doc_id, f"HTTP {response.status_code}"))
            continue
        chunks = response.json().get("data") or []
        if not chunks:
            failed.append((doc_id, "청크 0개"))
            continue
        text = chunk_text(chunks)
        (out_dir / index_text_name(doc_id)).write_text(text, encoding="utf-8")
        manifest[doc_id] = {"document_id": document_id, "chunks": len(chunks), "chars": len(text),
                            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps({
        "exported_at": now.isoformat(timespec="seconds"), "base_url": base_url, "index_backup": index_backup,
        "documents": manifest, "failed": dict(failed),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"targets": len(targets), "written": len(manifest), "failed": failed}
