from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from pydantic import BaseModel, Field
import chromadb
import tempfile
import os
import re
import json
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

app = FastAPI(title="DocuMind AI Server", version="1.0.0")


def _env_int(name: str, default: int) -> int:
    """정수 환경변수를 읽되 잘못된 값이면 기본값으로 되돌린다."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s=%s 값이 정수가 아니어서 기본값 %s를 사용합니다.", name, raw_value, default)
        return default

    if value <= 0:
        logger.warning("%s=%s 값이 0 이하라서 기본값 %s를 사용합니다.", name, raw_value, default)
        return default

    return value


def _keep_alive_seconds(value: str | None) -> int | None:
    """
    OllamaEmbeddings는 keep_alive를 int로 받으므로 duration 문자열을 초 단위로 변환한다.
    OllamaLLM에는 원문 값을 넘겨 `30m` 같은 Ollama duration 표현을 유지한다.
    """
    if not value:
        return None

    normalized = value.strip().lower()
    if normalized.isdigit():
        return int(normalized)

    unit = normalized[-1]
    amount = normalized[:-1]
    if not amount.isdigit():
        logger.warning("OLLAMA_KEEP_ALIVE=%s 값을 초 단위로 변환하지 못해 embedding keep_alive를 생략합니다.", value)
        return None

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None:
        logger.warning("OLLAMA_KEEP_ALIVE=%s 단위를 지원하지 않아 embedding keep_alive를 생략합니다.", value)
        return None

    return int(amount) * multiplier

# 환경변수로 로컬/Docker 환경 분기
# 로컬: OLLAMA_BASE_URL 미설정 시 localhost 사용
# Docker: OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# 환경변수로 LLM 모델명 분기. Docker: OLLAMA_LLM_MODEL=exaone3.5:7.8b
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "exaone3.5:7.8b")
# 환경변수로 임베딩 모델명 분기. 배포 서버에서는 qwen3-embedding:8b 사용 가능
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_CTX = _env_int("OLLAMA_NUM_CTX", 4096)
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 512)
EMBEDDING_BATCH_SIZE = _env_int("EMBEDDING_BATCH_SIZE", 64)
UPLOAD_READ_CHUNK_BYTES = _env_int("UPLOAD_READ_CHUNK_BYTES", 1024 * 1024)
DEFAULT_TOP_K = _env_int("AI_DEFAULT_TOP_K", 3)

embeddings = OllamaEmbeddings(
    model=OLLAMA_EMBEDDING_MODEL,
    base_url=OLLAMA_BASE_URL,
    keep_alive=_keep_alive_seconds(OLLAMA_KEEP_ALIVE),
    num_ctx=OLLAMA_NUM_CTX
)

# 질의응답에 사용할 LLM. 임베딩 모델과 분리해 별도 관리
llm = OllamaLLM(
    model=OLLAMA_LLM_MODEL,
    base_url=OLLAMA_BASE_URL,
    keep_alive=OLLAMA_KEEP_ALIVE,
    num_ctx=OLLAMA_NUM_CTX,
    num_predict=OLLAMA_NUM_PREDICT
)

# 환경변수로 ChromaDB 모드 분기
# 로컬: CHROMA_HOST 미설정 시 in-process PersistentClient 사용
# Docker: CHROMA_HOST=chromadb 설정 시 서버 모드 HttpClient 사용
CHROMA_HOST = os.getenv("CHROMA_HOST")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
if CHROMA_HOST:
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
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


def _build_chunk_metadata(doc: Document, filename: str, document_id: int, chunk_index: int, page_lookup: list[dict]) -> dict:
    """
    ChromaDB에 저장할 청크 metadata를 만든다.
    Header metadata와 페이지 추정값을 함께 보존한다.
    """
    metadata: dict = {
        "document_id": str(document_id),
        "source": filename,
        "chunk_index": chunk_index,
    }
    page_start, page_end = _resolve_page_range(doc.page_content, page_lookup)
    if page_start is not None:
        metadata["page"] = page_start
        metadata["page_start"] = page_start
        metadata["page_end"] = page_end if page_end is not None else page_start
    for key, value in doc.metadata.items():
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value

    return metadata


def _store_document_chunks(final_docs: list[Document], filename: str, document_id: int, page_lookup: list[dict]) -> tuple[float, float, float]:
    """
    문서 청크를 batch embedding 후 ChromaDB에 batch 저장한다.
    청크별 HTTP 호출을 피하기 위해 EMBEDDING_BATCH_SIZE 단위로 묶어 처리한다.
    """
    page_match_elapsed = 0.0
    embedding_elapsed = 0.0
    chroma_elapsed = 0.0

    for start in range(0, len(final_docs), EMBEDDING_BATCH_SIZE):
        batch_docs = final_docs[start:start + EMBEDDING_BATCH_SIZE]
        batch_ids = [f"{document_id}_{start + offset}" for offset in range(len(batch_docs))]
        batch_texts = [doc.page_content for doc in batch_docs]

        metadata_start = time.perf_counter()
        batch_metadatas = [
            _build_chunk_metadata(doc, filename, document_id, start + offset, page_lookup)
            for offset, doc in enumerate(batch_docs)
        ]
        page_match_elapsed += time.perf_counter() - metadata_start

        embedding_start = time.perf_counter()
        batch_vectors = embeddings.embed_documents(batch_texts)
        embedding_elapsed += time.perf_counter() - embedding_start

        chroma_start = time.perf_counter()
        collection.add(
            ids=batch_ids,
            embeddings=batch_vectors,
            documents=batch_texts,
            metadatas=batch_metadatas
        )
        chroma_elapsed += time.perf_counter() - chroma_start

    return page_match_elapsed, embedding_elapsed, chroma_elapsed


async def _run_upload_pipeline(tmp_path: str, filename: str, document_id: int) -> int:
    """문서 전처리 파이프라인: 로딩 → 정규화 → Two-Pass 청킹 → overlap → 임베딩 → ChromaDB 저장"""

    def _execute() -> int:
        total_start = time.perf_counter()

        # 파서 분기: 확장자에 따라 PDF 또는 Docling 로더 사용
        parse_start = time.perf_counter()
        raw_docs = _load_documents(tmp_path, filename)
        parse_elapsed = time.perf_counter() - parse_start

        page_lookup_start = time.perf_counter()
        page_lookup = _build_page_lookup(raw_docs)
        page_lookup_elapsed = time.perf_counter() - page_lookup_start

        # 전체 텍스트 병합 후 정규화
        normalize_start = time.perf_counter()
        full_text = "\n".join([doc.page_content for doc in raw_docs])
        full_text = _normalize_text(full_text)
        normalize_elapsed = time.perf_counter() - normalize_start

        # Two-Pass 청킹 + 수동 overlap 후처리
        split_start = time.perf_counter()
        split_docs = _two_pass_split(full_text)
        final_docs = _apply_overlap(split_docs)
        split_elapsed = time.perf_counter() - split_start

        # 임베딩 + ChromaDB 저장. 청크별 호출 대신 batch 단위로 처리해 HTTP 왕복과 저장 오버헤드를 줄인다.
        page_match_elapsed, embedding_elapsed, chroma_elapsed = _store_document_chunks(
            final_docs,
            filename,
            document_id,
            page_lookup
        )
        total_elapsed = time.perf_counter() - total_start
        logger.info(
            "[upload] document_id=%s filename=%s raw_docs=%s chunks=%s batch_size=%s parse=%.2fs page_lookup=%.2fs normalize=%.2fs split=%.2fs page_match=%.2fs embed=%.2fs chroma_add=%.2fs total=%.2fs",
            document_id,
            filename,
            len(raw_docs),
            len(final_docs),
            EMBEDDING_BATCH_SIZE,
            parse_elapsed,
            page_lookup_elapsed,
            normalize_elapsed,
            split_elapsed,
            page_match_elapsed,
            embedding_elapsed,
            chroma_elapsed,
            total_elapsed
        )
        return len(final_docs)

    return await asyncio.to_thread(_execute)


@app.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    document_id: int = Form(None)
):
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 파일 형식입니다. 허용: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 확장자를 임시 파일 suffix로 사용해야 파서가 형식을 올바르게 인식한다
    file_save_start = time.perf_counter()
    bytes_written = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(UPLOAD_READ_CHUNK_BYTES):
            tmp.write(chunk)
            bytes_written += len(chunk)

    logger.info(
        "[upload_file] document_id=%s filename=%s bytes=%s chunk_bytes=%s save=%.2fs",
        document_id,
        filename,
        bytes_written,
        UPLOAD_READ_CHUNK_BYTES,
        time.perf_counter() - file_save_start
    )

    try:
        chunk_count = await _run_upload_pipeline(tmp_path, filename, document_id)
        return {
            "status": "success",
            "filename": filename,
            "chunks": chunk_count
        }
    finally:
        os.unlink(tmp_path)


# 질의응답 요청 스키마. Pydantic BaseModel로 JSON body를 자동 파싱·검증
class QueryRequest(BaseModel):
    question: str
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)  # 검색할 유사 청크 수
    system_prompt: str | None = None  # Spring Boot 관리자 프롬프트 설정. 미전달 시 기본값 사용


DEFAULT_SYSTEM_PROMPT = (
    "주어진 문서를 참고하여 질문에 답변하세요."
)


def _prepare_query(question: str, top_k: int, system_prompt: str | None = None) -> tuple[str | None, list]:
    """
    질문 임베딩 → ChromaDB 검색 → 프롬프트 + 출처 조합.
    문서가 없으면 (None, []) 반환. 호출자가 빈 응답 처리를 담당한다.
    """
    prepare_start = time.perf_counter()
    embedding_start = time.perf_counter()
    question_vector = embeddings.embed_query(question)
    embedding_elapsed = time.perf_counter() - embedding_start

    chroma_start = time.perf_counter()
    results = collection.query(
        query_embeddings=[question_vector],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    chroma_elapsed = time.perf_counter() - chroma_start

    docs = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    ids = results["ids"][0] if results["ids"] else []

    if not docs:
        logger.info(
            "[query_prepare] top_k=%s docs=0 embed=%.2fs chroma=%.2fs total=%.2fs",
            top_k,
            embedding_elapsed,
            chroma_elapsed,
            time.perf_counter() - prepare_start
        )
        return None, []

    context = "\n\n".join(docs)
    prompt_policy = system_prompt.strip() if system_prompt and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT

    # 프롬프트 조합: 관리자 설정을 반영하되 문서 외 내용 답변 방지 제약은 서버에서 항상 덧붙인다
    prompt = f"""{prompt_policy}
문서에 없는 내용은 "관련 내용을 문서에서 찾을 수 없습니다."라고 답하세요.

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

    logger.info(
        "[query_prepare] top_k=%s docs=%s prompt_chars=%s embed=%.2fs chroma=%.2fs total=%.2fs",
        top_k,
        len(docs),
        len(prompt),
        embedding_elapsed,
        chroma_elapsed,
        time.perf_counter() - prepare_start
    )
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
    query_start = time.perf_counter()
    # _prepare_query는 embed_query·Chroma 조회가 모두 동기 블로킹이다.
    # async 핸들러에서 직접 호출하면 이벤트 루프가 묶여 다른 요청이 대기하므로
    # asyncio.to_thread()로 별도 스레드에서 실행한다.
    prompt, sources = await asyncio.to_thread(
        _prepare_query,
        request.question,
        request.top_k,
        request.system_prompt
    )

    if prompt is None:
        return {"answer": "관련 내용을 문서에서 찾을 수 없습니다.", "sources": []}

    # async 핸들러에서 ainvoke()로 이벤트 루프 블로킹 방지
    llm_start = time.perf_counter()
    answer = await llm.ainvoke(prompt)
    llm_elapsed = time.perf_counter() - llm_start
    logger.info(
        "[query] top_k=%s sources=%s prompt_chars=%s llm=%.2fs total=%.2fs",
        request.top_k,
        len(sources),
        len(prompt),
        llm_elapsed,
        time.perf_counter() - query_start
    )

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
    stream_start = time.perf_counter()
    prompt, sources = await asyncio.to_thread(
        _prepare_query,
        request.question,
        request.top_k,
        request.system_prompt
    )

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
        first_token_elapsed = None
        chunk_count = 0
        try:
            async for chunk in llm.astream(prompt):
                if chunk:
                    if first_token_elapsed is None:
                        first_token_elapsed = time.perf_counter() - stream_start
                        logger.info(
                            "[query_stream] first_token top_k=%s sources=%s prompt_chars=%s first_token=%.2fs",
                            request.top_k,
                            len(sources),
                            len(prompt),
                            first_token_elapsed
                        )
                    chunk_count += 1
                    yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"
            logger.info(
                "[query_stream] done top_k=%s sources=%s chunks=%s first_token=%s total=%.2fs",
                request.top_k,
                len(sources),
                chunk_count,
                f"{first_token_elapsed:.2f}s" if first_token_elapsed is not None else "none",
                time.perf_counter() - stream_start
            )
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
