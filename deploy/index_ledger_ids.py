"""색인(Chroma documents 컬렉션)에 든 문서의 대장 ID를 한 줄에 하나씩 출력한다. 읽기만 한다.

데이터셋용 색인과 서비스 색인이 나뉘었는지 확인할 때 쓴다(docs/development/local-gpu/데이터셋-색인-절차.md §3).
업로드 기록(uploads 표)이 아니라 색인에 실제로 든 문서를 본다 — 올린 뒤 지운 문서는 기록에만 남는다.
실행(맥북, 저장소 루트): ssh desktop-win "wsl -d Ubuntu -- docker exec -i <프로젝트>-ai-server-1 python -" < deploy/index_ledger_ids.py > ids.txt
"""
import os

import chromadb

client = chromadb.HttpClient(host=os.environ.get("CHROMA_HOST", "chromadb"),
                             port=int(os.environ.get("CHROMA_PORT", "8000")))
collection = client.get_collection("documents")
ledger_ids: set[str] = set()
offset = 0
while True:
    page = collection.get(include=["metadatas"], limit=2000, offset=offset)
    metadatas = page.get("metadatas") or []
    if not metadatas:
        break
    ledger_ids.update(str(meta["ledger_id"]) for meta in metadatas if meta and meta.get("ledger_id"))
    offset += len(metadatas)
print("\n".join(sorted(ledger_ids)))
