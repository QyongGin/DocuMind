from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from pydantic import BaseModel
import chromadb
import tempfile
import os
import re
import json
import asyncio
import logging
from langfuse_callback import get_langfuse_handler

logger = logging.getLogger(__name__)

app = FastAPI(title="DocuMind AI Server", version="1.0.0")

# 환경변수로 로컬/Docker 환경 분기
# 로컬: OLLAMA_BASE_URL 미설정 시 localhost 사용
# Docker: OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# 환경변수로 LLM 모델명 분기. Docker: OLLAMA_LLM_MODEL=exaone3.5:7.8b
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "exaone3.5:7.8b")
# 환경변수로 임베딩 모델명 분기. 배포 서버에서는 qwen3-embedding:8b 사용 가능
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b")

embeddings = OllamaEmbeddings(
    model=OLLAMA_EMBEDDING_MODEL,
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
    logger.error(f"[422 DETAIL] {exc.errors()}")
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


def _compact_for_page_match(text: str) -> str:
    """
    페이지 추정을 위해 공백을 제거한 비교용 문자열을 만든다.
    청킹 과정에서 개행과 공백이 정규화되어도 원본 페이지와 매칭할 수 있게 한다.
    """
    return re.sub(r'\s+', '', text)


def _build_page_lookup(raw_docs: list[Document]) -> list[dict]:
    """
    원본 로더가 제공한 페이지 metadata를 검색 가능한 형태로 보존한다.
    PDF는 OpenDataLoader가 page metadata를 제공하고, DOCX/PPTX/XLSX는 페이지 개념이 없으므로 제외된다.
    """
    page_lookup: list[dict] = []
    for doc in raw_docs:
        page = doc.metadata.get("page")
        if page is None:
            continue

        try:
            page_number = int(page)
        except (TypeError, ValueError):
            continue

        normalized_content = _compact_for_page_match(_normalize_text(doc.page_content))
        if normalized_content:
            page_lookup.append({
                "page": page_number,
                "content": normalized_content,
            })

    return page_lookup


def _sample_page_match_snippets(text: str) -> list[str]:
    """
    청크의 앞/중간/뒤 일부를 뽑아 원본 페이지와 비교한다.
    수동 overlap 때문에 앞부분이 이전 페이지에 걸칠 수 있어 여러 구간을 함께 사용한다.
    """
    compacted = _compact_for_page_match(text)
    if not compacted:
        return []

    snippet_size = min(120, len(compacted))
    starts = {0, max(0, (len(compacted) - snippet_size) // 2), max(0, len(compacted) - snippet_size)}

    snippets: list[str] = []
    for start in sorted(starts):
        snippet = compacted[start:start + snippet_size]
        if len(snippet) >= 8:
            snippets.append(snippet)

    return snippets


def _resolve_page_range(content: str, page_lookup: list[dict]) -> tuple[int | None, int | None]:
    """
    청크 내용이 어느 원본 페이지에 포함되는지 추정한다.
    여러 페이지에 걸친 overlap 청크는 page_start/page_end 범위로 반환한다.
    """
    if not page_lookup:
        return None, None

    snippets = _sample_page_match_snippets(content)
    if not snippets:
        return None, None

    matched_pages = set()
    for page in page_lookup:
        page_content = page["content"]
        if any(snippet in page_content for snippet in snippets):
            matched_pages.add(page["page"])

    if not matched_pages:
        return None, None

    return min(matched_pages), max(matched_pages)


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
        page_lookup = _build_page_lookup(raw_docs)

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
                "chunk_index": i,
            }
            page_start, page_end = _resolve_page_range(doc.page_content, page_lookup)
            if page_start is not None:
                metadata["page"] = page_start
                metadata["page_start"] = page_start
                metadata["page_end"] = page_end if page_end is not None else page_start
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


def _prepare_query(question: str, top_k: int) -> tuple[str | None, list]:
    """
    질문 임베딩 → ChromaDB 검색 → 프롬프트 + 출처 조합.
    문서가 없으면 (None, []) 반환. 호출자가 빈 응답 처리를 담당한다.
    """
    question_vector = embeddings.embed_query(question)
    results = collection.query(
        query_embeddings=[question_vector],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    docs = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    ids = results["ids"][0] if results["ids"] else []

    if not docs:
        return None, []

    context = "\n\n".join(docs)
    # 프롬프트 조합: 문서 외 내용 답변 방지를 위해 명시적 제약 포함
    prompt = f"""주어진 문서를 참고하여 질문에 답변하세요. 문서에 없는 내용은 "관련 내용을 문서에서 찾을 수 없습니다."라고 답하세요.

[문서]
{context}

[질문]
{question}

[답변]
"""

    # 출처 목록 구성: document_id, source(파일명), 페이지, 청크 미리보기, 헤더 메타데이터 포함
    sources = []
    for doc, meta, chunk_id in zip(docs, metadatas, ids):
        source: dict = {
            "document_id": meta.get("document_id", ""),
            "source": meta.get("source", ""),
            "page": meta.get("page"),
            "page_start": meta.get("page_start"),
            "page_end": meta.get("page_end"),
            "chunk_index": meta.get("chunk_index", _parse_chunk_index(chunk_id)),
            # 청크 전체를 반환하면 응답이 너무 커지므로 200자 미리보기만 포함
            "content": doc[:200]
        }
        # MarkdownHeaderTextSplitter가 부여한 헤더 메타데이터(Header 1, Header 2 등)를 함께 반환
        for k, v in meta.items():
            if k.startswith("Header"):
                source[k] = v
        sources.append(source)

    return prompt, sources


def _parse_chunk_index(chunk_id: str) -> int | None:
    """
    ChromaDB id({document_id}_{chunk_index})에서 청크 순번을 복원한다.
    기존 업로드 문서처럼 chunk_index metadata가 없는 경우 출처 UI에 최소 위치 정보를 제공한다.
    """
    suffix = str(chunk_id).rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else None


@app.delete("/documents/{document_id}")
async def delete_document(document_id: int):
    """
    ChromaDB에서 document_id에 해당하는 청크를 모두 삭제한다.
    Spring Boot 논리 삭제와 쌍으로 호출되어, RAG 검색에서 해당 문서가 제외되도록 한다.
    """
    def _delete_from_chroma() -> int:
        results = collection.get(
            where={"document_id": str(document_id)},
            include=[]  # IDs만 필요하므로 documents/embeddings/metadatas 제외
        )
        ids_to_delete = results["ids"]
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)

    # collection.get()/delete()는 동기 블로킹 호출이다.
    # async 핸들러에서 직접 호출하면 이벤트 루프가 점유되어 다른 요청이 대기하므로
    # /query 핸들러와 동일하게 asyncio.to_thread()로 별도 스레드에서 실행한다.
    deleted_count = await asyncio.to_thread(_delete_from_chroma)
    return {"status": "success", "deleted_chunks": deleted_count}


@app.get("/documents/{document_id}/chunks")
async def list_document_chunks(document_id: int):
    """
    ChromaDB에서 document_id에 해당하는 청크 원문과 메타데이터를 조회한다.
    관리자 문서 점검 화면에서 청킹 결과를 확인하기 위한 읽기 전용 엔드포인트다.
    """
    def _get_from_chroma() -> list[dict]:
        results = collection.get(
            where={"document_id": str(document_id)},
            include=["documents", "metadatas"]
        )
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        chunks: list[dict] = []
        for fallback_index, (chunk_id, content, metadata) in enumerate(zip(ids, documents, metadatas)):
            suffix = str(chunk_id).rsplit("_", 1)[-1]
            chunk_index = int(suffix) if suffix.isdigit() else fallback_index
            chunks.append({
                "id": chunk_id,
                "chunk_index": chunk_index,
                "content": content,
                "metadata": metadata or {}
            })

        return sorted(chunks, key=lambda chunk: chunk["chunk_index"])

    chunks = await asyncio.to_thread(_get_from_chroma)
    return {"document_id": document_id, "chunks": chunks}


@app.post("/query")
async def query_document(request: QueryRequest):
    """
    RAG 질의응답 파이프라인 (동기):
    1. 임베딩 → 검색 → 프롬프트 조합 (_prepare_query)
    2. EXAONE LLM 비동기 호출 → 답변 반환
    """
    # _prepare_query는 embed_query·Chroma 조회가 모두 동기 블로킹이다.
    # async 핸들러에서 직접 호출하면 이벤트 루프가 묶여 다른 요청이 대기하므로
    # asyncio.to_thread()로 별도 스레드에서 실행한다.
    prompt, sources = await asyncio.to_thread(_prepare_query, request.question, request.top_k)

    if prompt is None:
        return {"answer": "관련 내용을 문서에서 찾을 수 없습니다.", "sources": []}

    # async 핸들러에서 ainvoke()로 이벤트 루프 블로킹 방지
    answer = await llm.ainvoke(prompt)

    return {"answer": answer, "sources": sources}


@app.post("/query/stream")
async def query_stream(request: QueryRequest):
    """
    SSE 스트리밍 RAG 파이프라인:
    1. 임베딩 → 검색 → 프롬프트 조합 (_prepare_query)
    2. EXAONE 토큰 스트리밍 → SSE data 이벤트 전송
    3. 완료 시 sources 포함 done 이벤트 전송
    클라이언트 연결 종료 시 asyncio.CancelledError로 자동 중단된다.
    """
    prompt, sources = await asyncio.to_thread(_prepare_query, request.question, request.top_k)

    if prompt is None:
        async def empty_stream():
            payload = json.dumps(
                {"done": True, "answer": "관련 내용을 문서에서 찾을 수 없습니다.", "sources": []},
                ensure_ascii=False
            )
            yield f"data: {payload}\n\n"

        return StreamingResponse(
            empty_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    async def token_stream():
        try:
            async for chunk in llm.astream(prompt):
                if chunk:
                    yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"
            # 정상 완료 시 출처 포함 done 이벤트 전송
            yield f"data: {json.dumps({'done': True, 'sources': sources}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # 클라이언트가 연결을 끊은 정상적인 중단. 재전파해 FastAPI가 정리하도록 한다
            raise
        except Exception:
            # str(e)를 그대로 내보내면 Ollama/Chroma 내부 오류가 브라우저에 노출된다.
            # 상세 원인은 서버 로그에만 기록하고 클라이언트에는 고정 메시지만 전달한다.
            logger.exception("SSE 스트리밍 중 오류 발생")
            yield f"data: {json.dumps({'error': '응답 생성 중 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
