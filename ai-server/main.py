from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
import chromadb
import tempfile
import os
import re
from langfuse_callback import get_langfuse_handler

app = FastAPI(title="DocuMind AI Server", version="1.0.0")

# 환경변수로 로컬/Docker 환경 분기
# 로컬: OLLAMA_BASE_URL 미설정 시 localhost 사용
# Docker: OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

embeddings = OllamaEmbeddings(
    model="qwen3-embedding:4b",
    base_url=OLLAMA_BASE_URL
)

# 환경변수로 ChromaDB 모드 분기
# 로컬: CHROMA_HOST 미설정 시 in-process PersistentClient 사용
# Docker: CHROMA_HOST=chromadb 설정 시 서버 모드 HttpClient 사용
CHROMA_HOST = os.getenv("CHROMA_HOST")
if CHROMA_HOST:
    client = chromadb.HttpClient(host=CHROMA_HOST, port=8000)
else:
    client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection("documents")

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=0,  # 후처리에서 정확한 문자 단위 overlap을 적용하므로 0으로 설정
    length_function=len
)

# LANGFUSE_SECRET_KEY 설정 시 Langfuse 클라이언트를 초기화한다.
# 미설정 시 None으로 유지해 트레이싱 없이 파이프라인이 실행된다.
_langfuse = None
if os.getenv("LANGFUSE_SECRET_KEY"):
    from langfuse import Langfuse
    _langfuse = Langfuse()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import logging
    logging.error(f"[422 DETAIL] {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.get("/health")
def health():
    return {"status": "ok"}


async def _run_upload_pipeline(tmp_path: str, filename: str, document_id: int) -> int:
    """PDF 전처리 파이프라인: 로딩 → 청킹 → overlap 후처리 → 임베딩 → ChromaDB 저장"""

    async def _execute() -> int:
        loader = OpenDataLoaderPDFLoader(
            file_path=tmp_path,
            format="markdown"
        )
        docs = loader.load()

        # 전체 텍스트 합치기 (페이지 경계 무관하게 청킹하기 위함)
        full_text = "\n".join([doc.page_content for doc in docs])

        # PDF 파서 아티팩트: 문장 중간 삼중 개행 제거 (예: "같\n\n\n다" → "같다")
        full_text = re.sub(r'([가-힣])\n{3,}([가-힣])', r'\1\2', full_text)
        # 페이지 경계의 과도한 개행 정규화 (삼중 이상 → 이중)
        # "\n".join()으로 붙인 페이지 경계에서 \n\n\n이 생겨 overlap 버퍼가 리셋되는 문제 방지
        full_text = re.sub(r'\n{3,}', '\n\n', full_text)

        # 합친 텍스트로 청킹 (chunk_overlap=0으로 clean하게 분리)
        raw_texts = splitter.split_text(full_text)

        # 문자 단위 50글자 overlap 후처리 적용
        # create_documents()에 리스트를 넘기면 각 항목에 splitter를 재적용하므로
        # 텍스트를 직접 조작한 뒤 embedding/저장 루프에서 바로 사용
        overlapped_texts = []
        for i, text in enumerate(raw_texts):
            if i == 0:
                overlapped_texts.append(text)
            else:
                overlap = raw_texts[i - 1][-50:]
                overlapped_texts.append(overlap + "\n" + text)

        for i, text in enumerate(overlapped_texts):
            vector = embeddings.embed_query(text)
            collection.add(
                ids=[f"{document_id}_{i}"],
                embeddings=[vector],
                documents=[text],
                metadatas=[{
                    "document_id": str(document_id),
                    "source": filename,
                    "page": ""
                }]
            )

        return len(overlapped_texts)

    # Langfuse 4.x: start_as_current_observation()은 async context manager로 동작한다
    # _langfuse가 None이면 트레이싱 없이 파이프라인을 그대로 실행한다
    if _langfuse:
        with _langfuse.start_as_current_observation(
            name="document-upload-pipeline",
            as_type="chain",
            metadata={"document_id": document_id, "filename": filename}
        ):
            chunk_count = await _execute()
            _langfuse.set_current_trace_io(output={"chunks": chunk_count})
            _langfuse.flush()
            return chunk_count
    else:
        return await _execute()


@app.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    document_id: int = Form(None)
):
    import logging
    logging.warning(f"[DEBUG] filename={file.filename}, content_type={file.content_type}, document_id={document_id}")
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 허용됩니다.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunk_count = await _run_upload_pipeline(tmp_path, file.filename, document_id)
        return {
            "status": "success",
            "filename": file.filename,
            "chunks": chunk_count
        }
    finally:
        os.unlink(tmp_path)