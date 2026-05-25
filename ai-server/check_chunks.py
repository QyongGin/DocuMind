import chromadb
import os

# 환경변수로 로컬/Docker 분기
# 로컬: python check_chunks.py
# Docker 확인: CHROMA_HOST=localhost CHROMA_PORT=8001 python check_chunks.py
CHROMA_HOST = os.getenv("CHROMA_HOST")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))

if CHROMA_HOST:
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
else:
    client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_collection("documents")

import sys
if len(sys.argv) == 1:
    # 인자 없으면 목록만 출력
    all_results = collection.get(include=["metadatas"])
    doc_ids = sorted(set(m["document_id"] for m in all_results["metadatas"]))
    print(f"저장된 document_id 목록: {doc_ids}")
    print(f"전체 청크 수: {len(all_results['metadatas'])}개\n")
    for doc_id in doc_ids:
        count = sum(1 for m in all_results["metadatas"] if m["document_id"] == doc_id)
        source = next(m["source"] for m in all_results["metadatas"] if m["document_id"] == doc_id)
        print(f"  document_id={doc_id} | {source} | {count}청크")
else:
    # 인자로 document_id 지정하면 청크 내용 출력
    doc_id = sys.argv[1]
    results = collection.get(
        where={"document_id": doc_id},
        include=["documents"]
    )
    print(f"document_id={doc_id} 총 청크 수: {len(results['documents'])}개\n")
    for i, doc in enumerate(results["documents"]):
        print(f"=== 청크 {i+1} === ({len(doc)}글자)")
        print(doc)
        print()
