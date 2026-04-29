from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from pydantic import BaseModel
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
# 환경변수로 LLM 모델명 분기. Docker: OLLAMA_LLM_MODEL=exaone3.5:7.8b
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "exaone3.5:7.8b")

embeddings = OllamaEmbeddings(
    model="qwen3-embedding:4b",
    base_url=OLLAMA_BASE_URL
)

# 질의응답에 사용할 LLM. 임베딩 모델과 분리해 별도 관리
llm = OllamaLLM(
    model=OLLAMA_LLM_MODEL,
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

# Two-Pass 청킹 설정
# 1단계: 마크다운 헤더(#, ##, ###) 경계에서 분할, 헤더 경로를 메타데이터로 자동 부여
_MD_HEADERS = [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
_md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_MD_HEADERS)

# 2단계: 500자 초과 청크만 재분할. 내장 overlap은 서로 다른 헤더 구간 간 미적용 버그가
# 있으므로 0으로 두고 수동 후처리(_apply_overlap)로 대체한다.
_char_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=0,
    length_function=len
)

# 허용 파일 확장자. Spring Boot DocumentService와 동기화 필요
ALLOWED_EXTENSIONS = {"pdf", "docx", "pptx", "xlsx"}

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


def _load_documents(tmp_path: str, filename: str) -> list[Document]:
    """
    확장자에 따라 파서를 분기하고 LangChain Document 리스트를 반환한다.
    두 파서 모두 Markdown 형태의 Document를 출력하므로 이후 청킹 코드는 동일하게 유지된다.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        # opendataloader: 한글 PDF에 최적화, format="markdown"으로 구조 보존
        loader = OpenDataLoaderPDFLoader(file_path=tmp_path, format="markdown")
    else:
        # docx/pptx/xlsx: MarkItDown으로 Markdown 변환
        # Word 헤딩 스타일을 ATX(#, ##, ###)로 정확히 변환해 MarkdownHeaderTextSplitter와 연동
        from markitdown import MarkItDown
        markdown = MarkItDown().convert(tmp_path).text_content
        return [Document(page_content=markdown)]
    return loader.load()


def _normalize_text(text: str) -> str:
    """
    opendataloader 아티팩트 제거: 한글 문장 중간에 삽입되는 과도한 개행을 정규화한다.
    Docling 출력에도 동일하게 적용해도 무해하다.
    """
    # 한글 사이 3개 이상 개행 제거 (파서 버그로 삽입되는 아티팩트)
    text = re.sub(r'([가-힣])\n{3,}([가-힣])', r'\1\2', text)
    # 페이지 경계의 과도한 개행 정규화 (삼중 이상 → 이중)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _two_pass_split(full_text: str) -> list[Document]:
    """
    Two-Pass 청킹: MarkdownHeaderTextSplitter → RecursiveCharacterTextSplitter.

    1단계: 헤더 경계에서 분할해 헤더 경로 메타데이터를 부여한다.
    2단계: 500자 초과 청크만 char_splitter로 재분할한다.
           split_documents()는 부모 Document의 metadata를 자식에게 복사하므로
           1단계 헤더 메타데이터가 유지된다.
    """
    header_chunks = _md_splitter.split_text(full_text)

    result: list[Document] = []
    for doc in header_chunks:
        if len(doc.page_content) > 500:
            sub_docs = _char_splitter.split_documents([doc])
            result.extend(sub_docs)
        else:
            result.append(doc)

    return result


def _apply_overlap(docs: list[Document]) -> list[Document]:
    """
    이전 청크 마지막 50글자를 다음 청크 앞에 prepend하는 수동 overlap 후처리.
    RecursiveCharacterTextSplitter의 내장 overlap은 서로 다른 헤더 구간 간에
    작동하지 않으므로 전체 청크 리스트에 수동으로 적용한다.
    """
    overlapped: list[Document] = []
    for i, doc in enumerate(docs):
        if i == 0:
            overlapped.append(doc)
        else:
            overlap_text = docs[i - 1].page_content[-50:]
            overlapped.append(Document(
                page_content=overlap_text + "\n" + doc.page_content,
                metadata=doc.metadata
            ))
    return overlapped


async def _run_upload_pipeline(tmp_path: str, filename: str, document_id: int) -> int:
    """문서 전처리 파이프라인: 로딩 → 정규화 → Two-Pass 청킹 → overlap → 임베딩 → ChromaDB 저장"""

    async def _execute() -> int:
        # 파서 분기: 확장자에 따라 PDF 또는 Docling 로더 사용
        raw_docs = _load_documents(tmp_path, filename)

        # 전체 텍스트 병합 후 정규화
        full_text = "\n".join([doc.page_content for doc in raw_docs])
        full_text = _normalize_text(full_text)

        # Two-Pass 청킹 + 수동 overlap 후처리
        split_docs = _two_pass_split(full_text)
        final_docs = _apply_overlap(split_docs)

        # 임베딩 + ChromaDB 저장
        for i, doc in enumerate(final_docs):
            vector = embeddings.embed_query(doc.page_content)

            # 헤더 메타데이터(Header 1, Header 2 등) + 문서 식별 메타데이터 병합
            # ChromaDB는 str/int/float/bool 타입만 허용하므로 필터링한다
            metadata: dict = {
                "document_id": str(document_id),
                "source": filename,
            }
            for k, v in doc.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    metadata[k] = v

            collection.add(
                ids=[f"{document_id}_{i}"],
                embeddings=[vector],
                documents=[doc.page_content],
                metadatas=[metadata]
            )

        return len(final_docs)

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

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 파일 형식입니다. 허용: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 확장자를 임시 파일 suffix로 사용해야 파서가 형식을 올바르게 인식한다
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
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


# 질의응답 요청 스키마. Pydantic BaseModel로 JSON body를 자동 파싱·검증
class QueryRequest(BaseModel):
    question: str
    top_k: int = 5  # 검색할 유사 청크 수. 기본값 5


@app.post("/query")
async def query_document(request: QueryRequest):
    """
    RAG 질의응답 파이프라인:
    1. 질문 임베딩 → ChromaDB Top-K 유사도 검색
    2. 검색된 청크를 컨텍스트로 프롬프트 조합
    3. EXAONE (Ollama) 답변 생성
    4. 답변 + 출처 반환
    """
    # 1. 질문 임베딩 후 ChromaDB에서 유사 청크 검색
    question_vector = embeddings.embed_query(request.question)
    results = collection.query(
        query_embeddings=[question_vector],
        n_results=request.top_k,
        include=["documents", "metadatas", "distances"]
    )

    # ChromaDB 컬렉션이 비어있거나 결과가 없으면 빈 리스트 반환
    docs = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []

    if not docs:
        return {"answer": "관련 내용을 문서에서 찾을 수 없습니다.", "sources": []}

    # 2. 검색된 청크를 하나의 컨텍스트 문자열로 합침
    context = "\n\n".join(docs)

    # 3. 프롬프트 조합: 문서 외 내용 답변 방지를 위해 명시적 제약 포함
    prompt = f"""주어진 문서를 참고하여 질문에 답변하세요. 문서에 없는 내용은 "관련 내용을 문서에서 찾을 수 없습니다."라고 답하세요.

[문서]
{context}

[질문]
{request.question}

[답변]
"""

    # 4. EXAONE LLM 비동기 호출. async 핸들러에서 ainvoke()로 이벤트 루프 블로킹 방지
    answer = await llm.ainvoke(prompt)

    # 5. 출처 목록 구성: document_id, source(파일명), 청크 미리보기, 헤더 메타데이터 포함
    sources = []
    for doc, meta in zip(docs, metadatas):
        source: dict = {
            "document_id": meta.get("document_id", ""),
            "source": meta.get("source", ""),
            # 청크 전체를 반환하면 응답이 너무 커지므로 200자 미리보기만 포함
            "content": doc[:200]
        }
        # MarkdownHeaderTextSplitter가 부여한 헤더 메타데이터(Header 1, Header 2 등)를 함께 반환
        for k, v in meta.items():
            if k.startswith("Header"):
                source[k] = v
        sources.append(source)

    return {
        "answer": answer,
        "sources": sources
    }
