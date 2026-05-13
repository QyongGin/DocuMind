from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_ollama import OllamaLLM
from ollama import Client
from pydantic import BaseModel, Field
import chromadb
import tempfile
import os
import re
import json
import asyncio
import logging
import math
import time
from dataclasses import dataclass
from threading import Lock

try:
    from kiwipiepy import Kiwi
except ImportError:
    Kiwi = None

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="DocuMind AI Server", version="1.0.0")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """정수 환경변수를 읽되 범위를 벗어난 값이면 기본값으로 되돌린다."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("%s=%s 값이 정수가 아니어서 기본값 %s를 사용합니다.", name, raw_value, default)
        return default

    if value < minimum:
        logger.warning("%s=%s 값이 최소값 %s보다 작아서 기본값 %s를 사용합니다.", name, raw_value, minimum, default)
        return default

    return value


def _env_bool(name: str, default: bool = False) -> bool:
    """boolean 환경변수를 읽는다."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


# 환경변수로 로컬/Docker 환경 분기
# 로컬: OLLAMA_BASE_URL 미설정 시 localhost 사용
# Docker: OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# 환경변수로 LLM 모델명 분기. Docker: OLLAMA_LLM_MODEL=exaone3.5:7.8b
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "exaone3.5:7.8b")
# 환경변수로 임베딩 모델명 분기. VRAM이 작은 서버에서는 qwen3-embedding:4b를 우선 사용한다.
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_EMBEDDING_WARMUP_ON_STARTUP = _env_bool("OLLAMA_EMBEDDING_WARMUP_ON_STARTUP")
OLLAMA_NUM_CTX = _env_int("OLLAMA_NUM_CTX", 4096)
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 512)
OLLAMA_NUM_THREAD = _env_int("OLLAMA_NUM_THREAD", 0, minimum=0) or None
CHUNK_SIZE = _env_int("CHUNK_SIZE", 800, minimum=100)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 80, minimum=0)
CHUNK_MERGE_MIN_SIZE = _env_int("CHUNK_MERGE_MIN_SIZE", 300, minimum=0)
EMBEDDING_BATCH_SIZE = _env_int("EMBEDDING_BATCH_SIZE", 64)
UPLOAD_READ_CHUNK_BYTES = _env_int("UPLOAD_READ_CHUNK_BYTES", 1024 * 1024)
DEFAULT_TOP_K = _env_int("AI_DEFAULT_TOP_K", 5)
TABLE_FACT_MAX_PER_CHUNK = _env_int("TABLE_FACT_MAX_PER_CHUNK", 40)
TABLE_FACT_MAX_CHARS = _env_int("TABLE_FACT_MAX_CHARS", 420)
EMBED_TABLE_RAW_CHUNKS = _env_bool("EMBED_TABLE_RAW_CHUNKS", True)

if CHUNK_OVERLAP >= CHUNK_SIZE:
    logger.warning(
        "CHUNK_OVERLAP=%s 값이 CHUNK_SIZE=%s 이상이라서 overlap을 0으로 조정합니다.",
        CHUNK_OVERLAP,
        CHUNK_SIZE
    )
    CHUNK_OVERLAP = 0

ollama_client = Client(host=OLLAMA_BASE_URL)

# 질의응답에 사용할 LLM. 임베딩 모델과 분리해 별도 관리
llm = OllamaLLM(
    model=OLLAMA_LLM_MODEL,
    base_url=OLLAMA_BASE_URL,
    keep_alive=OLLAMA_KEEP_ALIVE,
    num_ctx=OLLAMA_NUM_CTX,
    num_predict=OLLAMA_NUM_PREDICT,
    num_thread=OLLAMA_NUM_THREAD
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

_progress_lock = Lock()
_kiwi_lock = Lock()
_kiwi_analyzer = None
_document_progress: dict[int, dict] = {}

logger.info(
    "[startup] ollama_base_url=%s llm_model=%s embedding_model=%s keep_alive=%s embedding_warmup=%s num_ctx=%s num_predict=%s num_thread=%s chunk_size=%s chunk_overlap=%s chunk_merge_min_size=%s embedding_batch_size=%s default_top_k=%s embed_table_raw_chunks=%s chroma_host=%s chroma_port=%s",
    OLLAMA_BASE_URL,
    OLLAMA_LLM_MODEL,
    OLLAMA_EMBEDDING_MODEL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_EMBEDDING_WARMUP_ON_STARTUP,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
    OLLAMA_NUM_THREAD or "auto",
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    CHUNK_MERGE_MIN_SIZE,
    EMBEDDING_BATCH_SIZE,
    DEFAULT_TOP_K,
    EMBED_TABLE_RAW_CHUNKS,
    CHROMA_HOST or "persistent",
    CHROMA_PORT
)

# Two-Pass 청킹 설정
# 1단계: 마크다운 헤더(# ~ ######) 경계에서 분할, 헤더 경로를 메타데이터로 자동 부여
# PDF 파서가 실제 소제목을 ######로 내보내는 경우가 있어 H6까지 주제 경계로 반영한다.
_MD_HEADERS = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
    ("####", "Header 4"),
    ("#####", "Header 5"),
    ("######", "Header 6"),
]
_md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_MD_HEADERS, strip_headers=False)

# 2단계: CHUNK_SIZE 초과 청크만 재분할. 내장 overlap은 서로 다른 헤더 구간 간 미적용 버그가
# 있으므로 0으로 두고 수동 후처리(_apply_overlap)로 대체한다.
_char_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
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


def _normalize_loaded_documents(raw_docs: list[Document]) -> list[Document]:
    """로더가 반환한 Document의 본문은 정규화하되 metadata는 보존한다."""
    return [
        Document(page_content=_normalize_text(doc.page_content), metadata=dict(doc.metadata))
        for doc in raw_docs
        if doc.page_content and doc.page_content.strip()
    ]


def _has_page_metadata(docs: list[Document]) -> bool:
    """PDF처럼 page metadata가 있는 Document 목록인지 확인한다."""
    return any(doc.metadata.get("page") is not None for doc in docs)


def _update_active_headers(active_headers: dict[str, str], chunk_metadata: dict) -> None:
    """페이지가 바뀌어도 직전 Markdown header 경로를 이어가기 위해 현재 chunk의 header를 반영한다."""
    for level in range(1, 7):
        key = f"Header {level}"
        value = str(chunk_metadata.get(key, "")).strip()
        if not value:
            continue

        active_headers[key] = value
        for lower_level in range(level + 1, 7):
            active_headers.pop(f"Header {lower_level}", None)


def _split_loaded_documents(docs: list[Document]) -> list[Document]:
    """
    로더 Document를 청킹한다.
    PDF는 page metadata를 가진 raw Document를 페이지별 구조 범위로 사용하고,
    DOCX/PPTX/XLSX처럼 page 개념이 없는 문서는 기존처럼 전체 Markdown을 청킹한다.
    """
    if not _has_page_metadata(docs):
        full_text = "\n".join(doc.page_content for doc in docs)
        return _two_pass_split(full_text)

    split_docs: list[Document] = []
    active_headers: dict[str, str] = {}
    for raw_doc in docs:
        page_chunks = _two_pass_split(raw_doc.page_content)
        for chunk in page_chunks:
            _update_active_headers(active_headers, chunk.metadata)
            metadata = dict(raw_doc.metadata)
            metadata.update(active_headers)
            metadata.update(chunk.metadata)
            split_docs.append(Document(page_content=chunk.page_content, metadata=metadata))

    return split_docs


def _two_pass_split(full_text: str) -> list[Document]:
    """
    Two-Pass 청킹: MarkdownHeaderTextSplitter → RecursiveCharacterTextSplitter.

    1단계: 헤더 경계에서 분할해 헤더 경로 메타데이터를 부여한다.
    2단계: CHUNK_SIZE 초과 청크만 char_splitter로 재분할한다.
           split_documents()는 부모 Document의 metadata를 자식에게 복사하므로
           1단계 헤더 메타데이터가 유지된다.
    """
    header_chunks = _md_splitter.split_text(full_text)

    result: list[Document] = []
    for doc in header_chunks:
        if len(doc.page_content) > CHUNK_SIZE:
            sub_docs = _split_large_chunk_preserving_tables(doc)
            result.extend(sub_docs)
        else:
            result.append(doc)

    return result


def _combine_chunk_documents(docs: list[Document]) -> Document:
    """
    인접한 짧은 청크를 하나로 합친다.
    서로 다른 헤더 metadata가 섞이면 공통으로 같은 값만 유지해 위치 정보를 과장하지 않는다.
    """
    page_content = "\n\n".join(doc.page_content for doc in docs if doc.page_content)
    common_metadata: dict = {}
    if docs:
        first_metadata = docs[0].metadata
        for key, value in first_metadata.items():
            if all(doc.metadata.get(key) == value for doc in docs[1:]):
                common_metadata[key] = value

    common_metadata["merged_chunk_count"] = len(docs)
    if any(doc.metadata.get("block_type") == "table" for doc in docs):
        common_metadata["block_type"] = "table"
    return Document(page_content=page_content, metadata=common_metadata)


def _header_signature(doc: Document) -> tuple[str, ...]:
    """청크의 상위 Markdown header 경로를 짧은 청크 병합 경계 판단용 tuple로 반환한다."""
    return tuple(str(doc.metadata.get(f"Header {level}", "")) for level in range(1, 4))


def _chunk_block_signature(doc: Document) -> str:
    """짧은 청크 병합 시 표와 일반 문단이 섞이지 않도록 block 성격을 반환한다."""
    if doc.metadata.get("block_type") == "table":
        return "table"
    return "text"


def _can_merge_text_prefix_into_table(buffer: list[Document], doc: Document, next_length: int, short_threshold: int) -> bool:
    """표 바로 앞의 짧은 제목·설명 청크는 table chunk와 함께 보존한다."""
    if not buffer:
        return False
    if _chunk_block_signature(buffer[-1]) != "text" or _chunk_block_signature(doc) != "table":
        return False
    buffer_text = "\n\n".join(item.page_content for item in buffer if item.page_content)
    if len(buffer_text) >= short_threshold:
        return False
    return next_length <= CHUNK_SIZE + CHUNK_OVERLAP


def _normalize_line_for_dedupe(line: str) -> str:
    """연속 중복 판단을 위해 line 내부 공백을 정규화한다."""
    return re.sub(r"\s+", " ", line).strip()


def _is_markdown_table_separator(line: str) -> bool:
    """Markdown table 구분선인지 확인한다."""
    stripped = line.strip()
    if "|" not in stripped or "-" not in stripped:
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _is_markdown_table_row(line: str) -> bool:
    """Markdown table row 형태인지 확인한다."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _first_non_empty_line(text: str) -> str:
    """텍스트에서 첫 번째 비어 있지 않은 line을 반환한다."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _starts_with_table_body_row(text: str) -> bool:
    """청크가 table header 없이 table body row로 시작하는지 확인한다."""
    first_line = _first_non_empty_line(text)
    return bool(first_line) and _is_markdown_table_row(first_line) and not _is_markdown_table_separator(first_line)


def _has_table_header_block_at_start(text: str) -> bool:
    """청크 시작부에 Markdown table header block이 이미 있는지 확인한다."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) >= 2 and _is_markdown_table_row(lines[0]) and _is_markdown_table_separator(lines[1])


def _starts_with_same_table_header_block(text: str, header_block: str) -> bool:
    """텍스트 시작부가 주어진 table header block과 같은지 확인한다."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header_lines = [line.strip() for line in header_block.splitlines() if line.strip()]
    if len(lines) < 2 or len(header_lines) < 2:
        return False
    return (
        _normalize_line_for_dedupe(lines[0]) == _normalize_line_for_dedupe(header_lines[0])
        and _normalize_line_for_dedupe(lines[1]) == _normalize_line_for_dedupe(header_lines[1])
    )


def _find_active_table_header_block(text: str) -> str:
    """
    이전 청크 끝까지 이어지는 table의 마지막 header block을 찾는다.
    header 뒤에 일반 문단이 나오면 이미 끝난 표로 보고 carry-forward하지 않는다.
    """
    lines = text.splitlines()
    last_header_block = ""

    for index in range(len(lines) - 1):
        if not (_is_markdown_table_row(lines[index]) and _is_markdown_table_separator(lines[index + 1])):
            continue

        has_body_row = False
        has_non_table_after_header = False
        for tail_line in lines[index + 2:]:
            if not tail_line.strip():
                continue
            if _is_markdown_table_row(tail_line) or _is_markdown_table_separator(tail_line):
                has_body_row = has_body_row or not _is_markdown_table_separator(tail_line)
                continue
            has_non_table_after_header = True
            break

        if has_body_row and not has_non_table_after_header:
            last_header_block = f"{lines[index].strip()}\n{lines[index + 1].strip()}"

    return last_header_block


def _select_table_header_overlap(previous_text: str, current_text: str) -> str:
    """표가 청크 경계에서 이어질 때 다음 청크 앞에 붙일 table header block을 선택한다."""
    if not _starts_with_table_body_row(current_text) or _has_table_header_block_at_start(current_text):
        return ""
    return _find_active_table_header_block(previous_text)


def _contains_table_block_near_start(text: str, max_lines: int = 12) -> bool:
    """청크 시작부에 표 block이 있는지 확인한다."""
    lines = [line.strip() for line in text.splitlines() if line.strip()][:max_lines]
    table_rows = 0
    for index, line in enumerate(lines):
        if _is_markdown_table_row(line):
            table_rows += 1
        next_line_is_separator = (
            index + 1 < len(lines)
            and _is_markdown_table_row(line)
            and _is_markdown_table_separator(lines[index + 1])
        )
        if next_line_is_separator:
            return True
    return table_rows >= 3


def _is_table_context_line(line: str) -> bool:
    """표 해석에 필요한 범례·주의 문구 후보인지 확인한다."""
    stripped = line.strip()
    if not stripped or _is_markdown_table_row(stripped) or _is_markdown_table_separator(stripped):
        return False

    note_prefixes = (
        "※",
        "- ※",
        "* ※",
        "주)",
        "주:",
        "비고",
        "참고",
        "단위",
        "범례",
        "legend",
    )
    marker_symbols = ("♣", "■", "□", "◈", "○", "●", "★", "☆")
    keywords = (
        "표시",
        "기호",
        "해당",
        "제외",
        "제한",
        "불가",
        "가능",
        "선택",
        "필수",
        "모집",
        "전형",
    )
    normalized = stripped.lower()
    return (
        stripped.startswith(note_prefixes)
        or any(symbol in stripped for symbol in marker_symbols)
        or any(keyword in normalized for keyword in keywords)
    )


def _select_table_context_overlap(
    previous_text: str,
    current_text: str,
    max_lines: int = 8,
    max_chars: int = 700,
) -> str:
    """
    표 본문과 분리된 직전 범례·주의 문구를 현재 표 청크 앞에 붙인다.
    예: '♣표시 : 4년제 학사학위(전공심화)과정 개설 학과' + 다음 모집인원 표.
    """
    if not _contains_table_block_near_start(current_text):
        return ""

    selected: list[str] = []
    for line in reversed([line.strip() for line in previous_text.splitlines() if line.strip()]):
        if _is_table_context_line(line):
            selected.insert(0, line)
            selected_text = "\n".join(selected)
            if len(selected) >= max_lines or len(selected_text) >= max_chars:
                break
            continue
        if selected:
            break

    return "\n".join(selected)


def _select_table_context_from_start(text: str, max_lines: int = 8, max_chars: int = 700) -> str:
    """표 뒤에 이어지는 범례·주의 문구를 앞쪽 line부터 선택한다."""
    selected: list[str] = []
    for line in [line.strip() for line in text.splitlines() if line.strip()]:
        if _is_table_context_line(line):
            selected.append(line)
            selected_text = "\n".join(selected)
            if len(selected) >= max_lines or len(selected_text) >= max_chars:
                break
            continue
        if selected:
            break
        if _is_markdown_table_line(line):
            break

    return "\n".join(selected)


def _is_table_like_document(doc: Document) -> bool:
    """현재 Document가 표 본문 성격인지 확인한다."""
    return doc.metadata.get("block_type") == "table" or _contains_table_block_near_start(doc.page_content, max_lines=20)


def _select_following_table_context(docs: list[Document], index: int) -> str:
    """연속된 표 chunk 뒤에 있는 범례·주의 문구를 현재 표 chunk에 붙일 context로 선택한다."""
    if not _is_table_like_document(docs[index]):
        return ""

    next_index = index + 1
    while next_index < len(docs) and _is_table_like_document(docs[next_index]):
        next_index += 1

    if next_index >= len(docs):
        return ""
    return _select_table_context_from_start(docs[next_index].page_content)


def _is_markdown_table_line(line: str) -> bool:
    """Markdown table row 또는 separator line인지 확인한다."""
    stripped = line.strip()
    return _is_markdown_table_row(stripped) or _is_markdown_table_separator(stripped)


def _split_markdown_table_blocks(text: str) -> list[tuple[str, str]]:
    """Markdown 본문을 text/table block으로 나눈다."""
    blocks: list[tuple[str, str]] = []
    current_type: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_type, current_lines
        if current_type and any(line.strip() for line in current_lines):
            blocks.append((current_type, "\n".join(current_lines).strip()))
        current_type = None
        current_lines = []

    for line in text.splitlines():
        line_type = "table" if _is_markdown_table_line(line) else "text"
        if current_type is None:
            current_type = line_type
        if line_type != current_type and line.strip():
            flush()
            current_type = line_type
        current_lines.append(line)

    flush()
    return blocks


def _document_with_metadata(page_content: str, metadata: dict, **extra_metadata) -> Document:
    """본문과 metadata를 함께 가진 Document를 만든다."""
    merged_metadata = dict(metadata)
    merged_metadata.update(extra_metadata)
    return Document(page_content=page_content, metadata=merged_metadata)


def _split_markdown_cells(line: str) -> list[str]:
    """Markdown table row를 cell 목록으로 분해한다."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_clean_table_cell(cell) for cell in stripped.split("|")]


def _clean_table_cell(cell: str) -> str:
    """표 cell 내부의 HTML 줄바꿈과 불필요한 공백을 정리한다."""
    cleaned = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _is_empty_table_cell(cell: str) -> bool:
    """Markdown 파싱 과정에서 생긴 빈 cell인지 확인한다."""
    return not cell or cell in {"-", "–", "—"}


def _normalize_table_symbol(symbol: str) -> str:
    """범례 symbol 표기를 정리한다."""
    return re.sub(r"\s+", "", symbol.strip())


def _extract_table_legends(text: str) -> dict[str, str]:
    """표 주변의 '기호 표시: 의미' 형태 범례를 추출한다."""
    legends: dict[str, str] = {}
    symbol_pattern = r"([♣■□◆◇◈●○◎△▲▣★☆※]+)"
    for raw_line in text.splitlines():
        line = re.sub(r"^[-*ㆍ·]\s*", "", raw_line.strip())
        if not line or "표시" not in line:
            continue

        match = re.search(symbol_pattern + r"\s*표시\s*[:：]?\s*(.+)", line)
        if not match:
            continue

        symbol = _normalize_table_symbol(match.group(1))
        description = match.group(2).strip()
        if not symbol or not description:
            continue
        legends[symbol] = description

    return legends


def _extract_table_caption(text: str, metadata: dict) -> str:
    """표 fact에 붙일 문서 내 표 제목 또는 섹션 경로를 찾는다."""
    caption_candidates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_markdown_table_line(stripped):
            break
        if stripped.startswith("######"):
            caption_candidates.append(stripped.lstrip("#").strip())
            continue
        if re.match(r"^(표|Table)\s*\d", stripped, flags=re.IGNORECASE):
            caption_candidates.append(stripped)
            continue
        if (
            len(stripped) <= 80
            and not stripped.startswith("- ※")
            and not stripped.endswith(">")
            and len(re.findall(r"\d{4}\.\d", stripped)) < 2
        ):
            caption_candidates.append(stripped.lstrip("- ").strip())

    if caption_candidates:
        return caption_candidates[-1]

    header_path = _format_header_path(metadata)
    return header_path or "문서 표"


def _parse_markdown_table(block_text: str) -> tuple[list[list[str]], list[list[str]]]:
    """Markdown table block에서 header row와 body row를 분리한다."""
    lines = [line.strip() for line in block_text.splitlines() if _is_markdown_table_line(line)]
    if len(lines) < 2:
        return [], []

    separator_index = next((index for index, line in enumerate(lines) if _is_markdown_table_separator(line)), -1)
    if separator_index <= 0:
        return [], []

    header_rows = [_split_markdown_cells(line) for line in lines[:separator_index]]
    body_rows = [_split_markdown_cells(line) for line in lines[separator_index + 1:]]
    column_count = max((len(row) for row in header_rows + body_rows), default=0)
    if column_count == 0:
        return [], []

    padded_headers = [row + [""] * (column_count - len(row)) for row in header_rows]
    padded_body = [row + [""] * (column_count - len(row)) for row in body_rows]
    return padded_headers, padded_body


def _is_probable_subheader_row(row: list[str]) -> bool:
    """본문 첫 줄이 실제 데이터가 아니라 병합 header 보강 row인지 추정한다."""
    non_empty_cells = [cell for cell in row if not _is_empty_table_cell(cell)]
    if len(non_empty_cells) < 2:
        return False
    if any(re.search(r"\d", cell) for cell in non_empty_cells):
        return False
    return True


def _compose_column_labels(header_rows: list[list[str]], subheader_row: list[str] | None = None) -> list[str]:
    """다중 header row와 보강 header row를 합쳐 column label을 만든다."""
    if not header_rows:
        return []

    column_count = len(header_rows[0])
    labels: list[str] = []
    last_seen_by_depth = [""] * len(header_rows)

    for column_index in range(column_count):
        parts: list[str] = []
        for depth, header_row in enumerate(header_rows):
            cell = header_row[column_index] if column_index < len(header_row) else ""
            if not _is_empty_table_cell(cell):
                last_seen_by_depth[depth] = cell
            value = last_seen_by_depth[depth]
            if value and value not in parts:
                parts.append(value)

        if subheader_row and column_index < len(subheader_row):
            subheader = subheader_row[column_index]
            if not _is_empty_table_cell(subheader) and subheader not in parts:
                parts.append(subheader)

        labels.append(" ".join(parts).strip() or f"열 {column_index + 1}")

    return labels


def _select_row_subject(row: list[str], column_labels: list[str]) -> tuple[str, list[str]]:
    """행 fact의 주어와 앞쪽 식별 cell 설명을 만든다."""
    descriptors: list[str] = []
    subject = ""
    preferred_subject = ""
    for index, cell in enumerate(row):
        if _is_empty_table_cell(cell):
            continue
        label = column_labels[index] if index < len(column_labels) else f"열 {index + 1}"
        descriptors.append(f"{label}={cell}")
        if (
            not preferred_subject
            and any(keyword in label for keyword in ("모집단위", "학과", "항목", "요소", "구분", "전형", "프로젝트 유형"))
            and not re.fullmatch(r"[\d.,]+", cell)
        ):
            preferred_subject = cell
        if not subject and not re.fullmatch(r"[\d.,]+", cell):
            subject = cell
        if len(descriptors) >= 3:
            break

    return preferred_subject or subject or "해당 행", descriptors


def _build_symbol_facts(caption: str, row: list[str], column_labels: list[str], legends: dict[str, str]) -> list[str]:
    """범례 기호가 들어간 행을 검색 가능한 fact 문장으로 바꾼다."""
    facts: list[str] = []
    if not legends:
        return facts

    subject, descriptors = _select_row_subject(row, column_labels)
    row_text = " ".join(cell for cell in row if cell)
    descriptor_text = ", ".join(descriptors)
    for symbol, description in legends.items():
        if symbol not in row_text:
            continue
        fact = f"{caption}: {subject} 행에는 {symbol} 표시가 있으며, {symbol} 표시는 {description}를 의미한다."
        if descriptor_text:
            fact = f"{fact} 행 정보: {descriptor_text}."
        facts.append(fact)

    return facts


def _build_matrix_facts(caption: str, row: list[str], column_labels: list[str]) -> list[str]:
    """행/열/값 관계가 있는 표를 cell 단위 fact로 바꾼다."""
    facts: list[str] = []
    subject, descriptors = _select_row_subject(row, column_labels)
    descriptor_text = ", ".join(descriptor for descriptor in descriptors if not re.search(r"=[\d.,]+$", descriptor))

    for index, value in enumerate(row):
        if index >= len(column_labels) or _is_empty_table_cell(value):
            continue
        if index < 2:
            continue
        column_label = column_labels[index]
        if not column_label or column_label.startswith("열 "):
            continue
        fact = f"{caption}: {subject}의 {column_label} 값은 {value}이다."
        if descriptor_text:
            fact = f"{fact} 행 정보: {descriptor_text}."
        facts.append(fact)

    return facts


def _clean_table_subject(subject: str) -> str:
    """검색 fact의 행 주어에서 범례 기호를 제거한다."""
    return re.sub(r"\s*[♣■◈◆◇□●○▲△★☆]\s*", "", subject).strip() or subject.strip()


def _should_generate_matrix_facts(column_labels: list[str]) -> bool:
    """등급/단계 열을 가진 매트릭스 표인지 보수적으로 판단한다."""
    matrix_keywords = ("매우 낮음", "낮음", "정상", "높음", "매우 높음", "극히 높음")
    if any(any(keyword in label for keyword in matrix_keywords) for label in column_labels):
        return True
    return False


def _build_row_legend_pairs(row: list[str], legends: dict[str, str]) -> list[str]:
    """행 안의 범례 기호와 표 주변 범례 설명을 key=value 형태로 만든다."""
    if not legends:
        return []

    row_text = " ".join(cell for cell in row if cell)
    pairs: list[str] = []
    for symbol, description in legends.items():
        if symbol in row_text:
            pairs.append(f"{symbol} 표시={description}")
    return pairs


def _build_row_summary_fact(caption: str, row: list[str], column_labels: list[str], legends: dict[str, str] | None = None) -> str:
    """표의 한 행을 key=value 형태의 검색 가능한 문장으로 만든다."""
    pairs: list[str] = _build_row_legend_pairs(row, legends or {})
    subject, _ = _select_row_subject(row, column_labels)
    subject = _clean_table_subject(subject)
    for index, value in enumerate(row):
        if _is_empty_table_cell(value):
            continue
        label = column_labels[index] if index < len(column_labels) else f"열 {index + 1}"
        if label.startswith("열 "):
            continue
        pairs.append(f"{label}={value}")

    if not pairs:
        return ""
    return f"{caption}: {subject} 행 정보는 {'; '.join(pairs)}이다."


def _truncate_table_fact(fact: str) -> str:
    """너무 긴 fact는 임베딩 품질과 토큰 비용을 위해 잘라낸다."""
    normalized = re.sub(r"\s+", " ", fact).strip()
    if len(normalized) <= TABLE_FACT_MAX_CHARS:
        return normalized
    return normalized[:TABLE_FACT_MAX_CHARS].rstrip() + "..."


def _extract_table_facts(text: str, metadata: dict) -> list[str]:
    """Markdown 표에서 원본 청크와 별도로 색인할 구조화 fact를 생성한다."""
    legends = _extract_table_legends(text)
    caption = _extract_table_caption(text, metadata)
    facts: list[str] = []
    seen: set[str] = set()

    def append_fact(fact: str) -> None:
        if len(facts) >= TABLE_FACT_MAX_PER_CHUNK:
            return
        normalized = _truncate_table_fact(fact)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        facts.append(normalized)

    for block_type, block_text in _split_markdown_table_blocks(text):
        if block_type != "table":
            continue

        header_rows, body_rows = _parse_markdown_table(block_text)
        if not header_rows or not body_rows:
            continue

        subheader_row = body_rows[0] if body_rows and _is_probable_subheader_row(body_rows[0]) else None
        data_rows = body_rows[1:] if subheader_row else body_rows
        column_labels = _compose_column_labels(header_rows, subheader_row)
        generate_matrix_facts = _should_generate_matrix_facts(column_labels)
        previous_values: dict[int, str] = {}
        table_facts: list[str] = []

        for row in data_rows:
            if not any(not _is_empty_table_cell(cell) for cell in row):
                continue

            filled_row = list(row)
            for index in range(min(2, len(filled_row))):
                if _is_empty_table_cell(filled_row[index]) and previous_values.get(index):
                    filled_row[index] = previous_values[index]
                elif not _is_empty_table_cell(filled_row[index]):
                    previous_values[index] = filled_row[index]

            row_summary = _build_row_summary_fact(caption, filled_row, column_labels, legends)
            if row_summary:
                table_facts.append(row_summary)
            else:
                table_facts.extend(_build_symbol_facts(caption, filled_row, column_labels, legends))

            if generate_matrix_facts:
                table_facts.extend(_build_matrix_facts(caption, filled_row, column_labels))

        for fact in table_facts:
            append_fact(fact)

    return facts


def _split_text_block(block_text: str, metadata: dict) -> list[Document]:
    """일반 text block은 기존 RecursiveCharacterTextSplitter로 분할한다."""
    document = Document(page_content=block_text, metadata=dict(metadata))
    if len(block_text) <= CHUNK_SIZE:
        return [document]
    return _char_splitter.split_documents([document])


def _split_table_block(block_text: str, metadata: dict) -> list[Document]:
    """
    Markdown table block은 문자 중간에서 자르지 않고 row group 단위로 분할한다.
    header row와 separator가 있으면 각 분할 table 앞에 반복한다.
    """
    lines = [line.strip() for line in block_text.splitlines() if line.strip()]
    if not lines:
        return []

    table_metadata = dict(metadata)
    table_metadata["block_type"] = "table"

    if len(block_text) <= CHUNK_SIZE:
        return [_document_with_metadata(block_text, table_metadata)]

    header_lines: list[str] = []
    body_lines = lines
    if len(lines) >= 2 and _is_markdown_table_row(lines[0]) and _is_markdown_table_separator(lines[1]):
        header_lines = lines[:2]
        body_lines = lines[2:]

    if not body_lines:
        return [_document_with_metadata(block_text, table_metadata)]

    chunks: list[Document] = []
    current_rows: list[str] = []

    def build_table(rows: list[str]) -> str:
        if header_lines:
            return "\n".join(header_lines + rows)
        return "\n".join(rows)

    for row in body_lines:
        candidate_rows = current_rows + [row]
        candidate = build_table(candidate_rows)
        if current_rows and len(candidate) > CHUNK_SIZE:
            chunks.append(_document_with_metadata(build_table(current_rows), table_metadata))
            current_rows = [row]
            continue
        current_rows = candidate_rows

    if current_rows:
        chunks.append(_document_with_metadata(build_table(current_rows), table_metadata))

    return chunks


def _split_large_chunk_preserving_tables(doc: Document) -> list[Document]:
    """큰 청크를 나눌 때 Markdown table은 row group 단위로 보존한다."""
    blocks = _split_markdown_table_blocks(doc.page_content)
    if not any(block_type == "table" for block_type, _ in blocks):
        return _char_splitter.split_documents([doc])

    split_docs: list[Document] = []
    for block_type, block_text in blocks:
        if block_type == "table":
            split_docs.extend(_split_table_block(block_text, doc.metadata))
        else:
            split_docs.extend(_split_text_block(block_text, doc.metadata))
    return split_docs


def _starts_with_structural_boundary(text: str) -> bool:
    """현재 청크가 새 장·조·부칙 같은 강한 문서 경계에서 시작하는지 확인한다."""
    first_line = _first_non_empty_line(text)
    if not first_line:
        return False

    normalized = re.sub(r"\s+", "", first_line)
    if first_line.startswith("#"):
        return True
    if normalized.startswith("부칙"):
        return True
    return bool(re.match(r"^[-*ㆍ·]?(제\d+(장|절|조|조의\d+))", normalized))


def _should_apply_general_overlap(current_text: str) -> bool:
    """표 header carry-forward와 별개로 일반 line overlap을 붙일지 판단한다."""
    return not _starts_with_structural_boundary(current_text)


def _dedupe_adjacent_lines(text: str) -> str:
    """
    같은 청크 안에서 바로 반복되는 동일 line 또는 동일 table header block만 제거한다.
    표 구조 자체는 보존하고, 페이지 반복 header/footer 후보처럼 떨어져 반복되는 line은 제거하지 않는다.
    """
    lines = text.splitlines()
    deduped: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        normalized_line = _normalize_line_for_dedupe(line)

        if normalized_line and deduped and normalized_line == _normalize_line_for_dedupe(deduped[-1]):
            index += 1
            continue

        has_table_header_block = (
            index + 1 < len(lines)
            and _is_markdown_table_row(line)
            and _is_markdown_table_separator(lines[index + 1])
        )
        has_same_previous_header_block = (
            has_table_header_block
            and len(deduped) >= 2
            and normalized_line == _normalize_line_for_dedupe(deduped[-2])
            and _normalize_line_for_dedupe(lines[index + 1]) == _normalize_line_for_dedupe(deduped[-1])
        )
        if has_same_previous_header_block:
            index += 2
            continue

        deduped.append(line)
        index += 1

    return "\n".join(deduped).strip()


def _dedupe_chunk_documents(docs: list[Document]) -> list[Document]:
    """청크별 연속 중복 line을 제거하되 metadata는 유지한다."""
    return [
        Document(page_content=_dedupe_adjacent_lines(doc.page_content), metadata=doc.metadata)
        for doc in docs
    ]


def _select_long_line_suffix(line: str, max_chars: int) -> str:
    """완성된 줄 하나가 overlap 예산보다 길 때 마지막 일부를 fallback 문맥으로 선택한다."""
    normalized_line = line.strip()
    if len(normalized_line) <= max_chars:
        return normalized_line

    return normalized_line[-max_chars:].strip()


def _select_overlap_text(previous_text: str, max_chars: int) -> str:
    """이전 청크의 마지막 완성 line들을 max_chars 안에서 overlap 문맥으로 선택한다."""
    if max_chars <= 0:
        return ""

    selected: list[str] = []
    selected_length = 0
    lines = [line.rstrip() for line in previous_text.splitlines() if line.strip()]
    if lines and _is_markdown_table_line(lines[-1]):
        return ""

    for line in reversed(lines):
        normalized_line = line.strip()
        next_length = selected_length + (1 if selected else 0) + len(normalized_line)
        if selected and next_length > max_chars:
            break
        if not selected and len(normalized_line) > max_chars:
            return _select_long_line_suffix(normalized_line, max_chars)
        selected.insert(0, normalized_line)
        selected_length = next_length

    return "\n".join(selected)


def _percentile(sorted_values: list[int], percentile: int) -> int:
    """정렬된 숫자 목록에서 지정한 백분위 값을 반환한다."""
    if not sorted_values:
        return 0

    index = math.ceil((percentile / 100) * len(sorted_values)) - 1
    bounded_index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[bounded_index]


def _duplicate_line_metrics(docs: list[Document]) -> dict:
    """
    반복 header/footer 후보를 찾기 위한 line 중복 통계를 만든다.
    원문 line은 운영 로그에 남기지 않고 후보 개수와 비율만 기록한다.
    """
    line_counts: dict[str, int] = {}
    line_candidates = 0

    for doc in docs:
        for line in doc.page_content.splitlines():
            normalized_line = re.sub(r"\s+", " ", line).strip()
            if len(normalized_line) < 8 or len(normalized_line) > 120:
                continue
            line_candidates += 1
            line_counts[normalized_line] = line_counts.get(normalized_line, 0) + 1

    duplicate_counts = [count for count in line_counts.values() if count > 1]
    duplicate_occurrences = sum(count - 1 for count in duplicate_counts)
    duplicate_ratio = duplicate_occurrences / line_candidates if line_candidates else 0.0
    return {
        "line_candidates": line_candidates,
        "duplicate_line_candidates": len(duplicate_counts),
        "duplicate_line_occurrences": duplicate_occurrences,
        "duplicate_line_ratio": duplicate_ratio,
    }


def _chunk_stats(docs: list[Document]) -> dict:
    """청크 길이 분포와 반복 line 후보 통계를 계산한다."""
    lengths = sorted(len(doc.page_content) for doc in docs)
    duplicate_metrics = _duplicate_line_metrics(docs)
    short_threshold = CHUNK_MERGE_MIN_SIZE if CHUNK_MERGE_MIN_SIZE > 0 else max(1, CHUNK_SIZE // 3)

    if not lengths:
        return {
            "chunks": 0,
            "total_chars": 0,
            "avg_chars": 0.0,
            "min_chars": 0,
            "p50_chars": 0,
            "p90_chars": 0,
            "max_chars": 0,
            "short_chunks": 0,
            "short_threshold": short_threshold,
            **duplicate_metrics,
        }

    return {
        "chunks": len(lengths),
        "total_chars": sum(lengths),
        "avg_chars": sum(lengths) / len(lengths),
        "min_chars": lengths[0],
        "p50_chars": _percentile(lengths, 50),
        "p90_chars": _percentile(lengths, 90),
        "max_chars": lengths[-1],
        "short_chunks": sum(1 for length in lengths if length < short_threshold),
        "short_threshold": short_threshold,
        **duplicate_metrics,
    }


def _log_chunk_stats(document_id: int, filename: str, stage: str, docs: list[Document]) -> None:
    """청크 정책 실험 비교에 필요한 통계형 로그를 남긴다."""
    stats = _chunk_stats(docs)
    logger.info(
        "[chunk_stats] document_id=%s filename=%s stage=%s chunks=%s total_chars=%s avg_chars=%.1f min_chars=%s p50_chars=%s p90_chars=%s max_chars=%s short_chunks=%s short_threshold=%s line_candidates=%s duplicate_line_candidates=%s duplicate_line_occurrences=%s duplicate_line_ratio=%.3f",
        document_id,
        filename,
        stage,
        stats["chunks"],
        stats["total_chars"],
        stats["avg_chars"],
        stats["min_chars"],
        stats["p50_chars"],
        stats["p90_chars"],
        stats["max_chars"],
        stats["short_chunks"],
        stats["short_threshold"],
        stats["line_candidates"],
        stats["duplicate_line_candidates"],
        stats["duplicate_line_occurrences"],
        stats["duplicate_line_ratio"],
    )


def _set_document_progress(document_id: int | None, percent: int, stage: str, message: str, status: str = "processing") -> None:
    """문서 처리 진행률을 메모리에 기록한다."""
    if document_id is None:
        return

    normalized_percent = max(0, min(100, int(percent)))
    progress = {
        "document_id": document_id,
        "percent": normalized_percent,
        "stage": stage,
        "message": message,
        "status": status,
        "updated_at": time.time(),
    }
    with _progress_lock:
        _document_progress[document_id] = progress


def _get_document_progress(document_id: int) -> dict:
    """문서 처리 진행률을 조회한다."""
    with _progress_lock:
        progress = _document_progress.get(document_id)
        if progress is None:
            return {
                "document_id": document_id,
                "percent": 0,
                "stage": "unknown",
                "message": "진행 정보를 준비 중입니다.",
                "status": "unknown",
                "updated_at": time.time(),
            }
        return dict(progress)


def _merge_short_chunks(docs: list[Document]) -> list[Document]:
    """
    같은 header 경로의 짧은 인접 청크를 CHUNK_SIZE를 넘지 않는 범위에서 병합한다.
    LlamaIndex ingestion pipeline의 node 관리처럼 embedding 대상 수를 줄이는 목적이다.
    """
    if CHUNK_MERGE_MIN_SIZE <= 0:
        return docs

    merged: list[Document] = []
    buffer: list[Document] = []
    buffer_length = 0
    short_threshold = CHUNK_MERGE_MIN_SIZE if CHUNK_MERGE_MIN_SIZE > 0 else max(1, CHUNK_SIZE // 3)

    for doc in docs:
        if not doc.page_content.strip():
            continue

        doc_length = len(doc.page_content)
        next_length = buffer_length + (2 if buffer else 0) + doc_length
        header_changed = bool(buffer) and _header_signature(buffer[0]) != _header_signature(doc)
        block_type_changed = bool(buffer) and _chunk_block_signature(buffer[-1]) != _chunk_block_signature(doc)
        can_merge_text_prefix_into_table = _can_merge_text_prefix_into_table(
            buffer,
            doc,
            next_length,
            short_threshold,
        )

        if buffer and (
            header_changed
            or (block_type_changed and not can_merge_text_prefix_into_table)
            or buffer_length >= CHUNK_MERGE_MIN_SIZE
            or (next_length > CHUNK_SIZE and not can_merge_text_prefix_into_table)
        ):
            merged.append(_combine_chunk_documents(buffer))
            buffer = []
            buffer_length = 0

        buffer.append(doc)
        buffer_length += (2 if buffer_length else 0) + doc_length

    if buffer:
        merged.append(_combine_chunk_documents(buffer))

    return merged


def _apply_overlap(docs: list[Document]) -> list[Document]:
    """
    이전 청크의 마지막 완성 line들을 다음 청크 앞에 prepend하는 수동 overlap 후처리.
    표가 청크 경계에서 끊기면 이전 청크의 활성 table header block도 함께 prepend한다.
    표의 범례·주의 문구가 표 앞이나 뒤에 분리되어 있으면 해당 문구도 표 청크에 붙인다.
    RecursiveCharacterTextSplitter의 내장 overlap은 서로 다른 헤더 구간 간에
    작동하지 않으므로 전체 청크 리스트에 수동으로 적용한다. 문자 중간을 자르지 않는다.
    """
    overlapped: list[Document] = []
    for i, doc in enumerate(docs):
        following_table_context = _select_following_table_context(docs, i)
        content_text = doc.page_content
        if following_table_context and following_table_context not in content_text:
            content_text = f"{content_text}\n\n{following_table_context}"

        if i == 0:
            if following_table_context:
                overlapped.append(Document(
                    page_content=_dedupe_adjacent_lines(content_text),
                    metadata=doc.metadata
                ))
                continue
            overlapped.append(doc)
        else:
            context_parts = []
            overlap_text = ""
            if CHUNK_OVERLAP > 0 and _should_apply_general_overlap(content_text):
                overlap_text = _select_overlap_text(docs[i - 1].page_content, CHUNK_OVERLAP)
            table_context_overlap = _select_table_context_overlap(docs[i - 1].page_content, content_text)
            if table_context_overlap:
                context_parts.append(table_context_overlap)

            table_header_overlap = _select_table_header_overlap(docs[i - 1].page_content, content_text)
            if table_header_overlap and not _starts_with_same_table_header_block(overlap_text, table_header_overlap):
                context_parts.append(table_header_overlap)

            if overlap_text and not table_context_overlap and not table_header_overlap:
                context_parts.append(overlap_text)

            if not context_parts and not following_table_context:
                overlapped.append(doc)
                continue
            context_text = "\n\n".join(context_parts)
            combined_text = f"{context_text}\n\n{content_text}" if context_text else content_text
            overlapped.append(Document(
                page_content=_dedupe_adjacent_lines(combined_text),
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


def _ollama_embedding_options() -> dict:
    """Ollama embed API에 전달할 runtime options를 만든다."""
    options = {"num_ctx": OLLAMA_NUM_CTX}
    if OLLAMA_NUM_THREAD is not None:
        options["num_thread"] = OLLAMA_NUM_THREAD
    return options


def _seconds_from_nanos(value: int | None) -> float | None:
    """Ollama가 반환한 nanosecond duration을 초 단위로 바꾼다."""
    return value / 1_000_000_000 if value is not None else None


def _format_seconds(value: float | None) -> str:
    """로그에 남길 duration 문자열을 만든다."""
    return f"{value:.2f}s" if value is not None else "n/a"


def _format_int_list(values: list[int]) -> str:
    """짧은 숫자 목록을 로그용 문자열로 만든다."""
    return ",".join(str(value) for value in values) if values else "none"


def _format_distance_list(values: list[float]) -> str:
    """Chroma distance 목록을 로그용 문자열로 만든다."""
    return ",".join(f"{value:.4f}" for value in values) if values else "none"


def _format_decimal(value: float | None) -> str:
    """소수 로그 값을 고정 폭 문자열로 만든다."""
    return f"{value:.4f}" if value is not None else "n/a"


def _round_float(value: float | int | None, digits: int = 6) -> float | None:
    """trace 응답에 넣을 실수 값을 JSON 친화적인 고정 소수로 정리한다."""
    if value is None:
        return None
    return round(float(value), digits)


def _vector_preview(vector: list[float] | None, size: int) -> list[float]:
    """긴 임베딩 벡터에서 앞부분 일부만 trace 응답에 노출한다."""
    if vector is None or size <= 0:
        return []
    return [_round_float(value) for value in list(vector)[:size]]


def _vector_norm(vector: list[float]) -> float:
    """질의 벡터의 L2 norm을 계산해 벡터가 실제 생성됐는지 확인할 수 있게 한다."""
    return math.sqrt(sum(float(value) * float(value) for value in vector))


def _collection_distance_metric() -> str:
    """Chroma collection에 명시된 distance metric을 반환한다."""
    metadata = getattr(collection, "metadata", None) or {}
    if isinstance(metadata, dict):
        return str(metadata.get("hnsw:space") or "unspecified")
    return "unspecified"


def _similarity_if_cosine(distance: float | None, metric: str) -> float | None:
    """collection이 cosine metric일 때만 distance를 similarity로 변환한다."""
    if distance is None or metric != "cosine":
        return None
    return _round_float(1 - float(distance))


def _preview_text(text: str, limit: int = 360) -> str:
    """trace 후보 목록에서 본문을 너무 길게 보내지 않도록 미리보기로 줄인다."""
    stripped = str(text).strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit].rstrip()}..."


def _embed_texts(texts: list[str]) -> tuple[list[list[float]], dict]:
    """
    Ollama embed API로 batch embedding을 수행하고 duration metadata를 함께 반환한다.
    LangChain wrapper가 숨기는 total/load/prompt timing을 로그 분석에 사용한다.
    """
    response = ollama_client.embed(
        model=OLLAMA_EMBEDDING_MODEL,
        input=texts,
        options=_ollama_embedding_options(),
        keep_alive=OLLAMA_KEEP_ALIVE,
    )
    response_data = response.model_dump()
    return response_data["embeddings"], response_data


def _warm_up_embedding_model() -> None:
    """첫 사용자 업로드가 Ollama cold load 시간을 떠안지 않도록 임베딩 모델을 미리 로딩한다."""
    started = time.perf_counter()
    response = ollama_client.embed(
        model=OLLAMA_EMBEDDING_MODEL,
        input=["warmup"],
        options=_ollama_embedding_options(),
        keep_alive=OLLAMA_KEEP_ALIVE,
    )
    elapsed = time.perf_counter() - started
    response_data = response.model_dump()
    logger.info(
        "[startup_embedding_warmup_done] model=%s wall=%.2fs ollama_total=%s ollama_load=%s prompt_eval=%s prompt_eval_count=%s",
        OLLAMA_EMBEDDING_MODEL,
        elapsed,
        _format_seconds(_seconds_from_nanos(response_data.get("total_duration"))),
        _format_seconds(_seconds_from_nanos(response_data.get("load_duration"))),
        _format_seconds(_seconds_from_nanos(response_data.get("prompt_eval_duration"))),
        response_data.get("prompt_eval_count", "n/a"),
    )


@app.on_event("startup")
async def warm_up_embedding_model_on_startup() -> None:
    """옵션이 켜져 있으면 앱 시작 시 임베딩 모델 로딩까지 완료한다."""
    if not OLLAMA_EMBEDDING_WARMUP_ON_STARTUP:
        return

    logger.info(
        "[startup_embedding_warmup] model=%s keep_alive=%s",
        OLLAMA_EMBEDDING_MODEL,
        OLLAMA_KEEP_ALIVE,
    )
    await asyncio.to_thread(_warm_up_embedding_model)


def _build_index_documents(
    final_docs: list[Document],
    filename: str,
    document_id: int,
    page_lookup: list[dict],
) -> tuple[list[Document], float, int]:
    """원본 청크와 검색용 table fact 문서를 함께 만든다."""
    index_docs: list[Document] = []
    page_match_elapsed = 0.0
    table_fact_count = 0

    for chunk_index, doc in enumerate(final_docs):
        metadata_start = time.perf_counter()
        raw_metadata = _build_chunk_metadata(doc, filename, document_id, chunk_index, page_lookup)
        page_match_elapsed += time.perf_counter() - metadata_start
        raw_metadata["chunk_role"] = "raw"

        parent_chunk_id = f"{document_id}_{chunk_index}"
        table_facts = _extract_table_facts(doc.page_content, raw_metadata)
        should_embed_raw_chunk = EMBED_TABLE_RAW_CHUNKS or not table_facts
        if should_embed_raw_chunk:
            index_docs.append(Document(page_content=doc.page_content, metadata=raw_metadata))

        for fact_index, fact in enumerate(table_facts):
            fact_metadata = dict(raw_metadata)
            fact_metadata.update({
                "chunk_role": "table_fact",
                "parent_chunk_id": parent_chunk_id,
                "parent_chunk_index": chunk_index,
                "fact_index": fact_index,
            })
            if not should_embed_raw_chunk:
                fact_metadata["parent_content"] = doc.page_content
            index_docs.append(Document(page_content=fact, metadata=fact_metadata))
            table_fact_count += 1

    return index_docs, page_match_elapsed, table_fact_count


def _build_index_document_id(document_id: int, metadata: dict, fallback_index: int) -> str:
    """ChromaDB에 저장할 원본 청크와 파생 fact id를 만든다."""
    if metadata.get("chunk_role") == "table_fact":
        parent_index = metadata.get("parent_chunk_index", fallback_index)
        fact_index = metadata.get("fact_index", 0)
        return f"{document_id}_{parent_index}_fact_{fact_index}"
    chunk_index = metadata.get("chunk_index", fallback_index)
    return f"{document_id}_{chunk_index}"


def _store_document_chunks(final_docs: list[Document], filename: str, document_id: int, page_lookup: list[dict]) -> tuple[float, float, float, int, int]:
    """
    문서 청크를 batch embedding 후 ChromaDB에 batch 저장한다.
    청크별 HTTP 호출을 피하기 위해 EMBEDDING_BATCH_SIZE 단위로 묶어 처리한다.
    """
    index_docs, page_match_elapsed, table_fact_count = _build_index_documents(
        final_docs,
        filename,
        document_id,
        page_lookup,
    )
    embedding_elapsed = 0.0
    chroma_elapsed = 0.0
    total_entries = len(index_docs)
    if total_entries == 0:
        return page_match_elapsed, embedding_elapsed, chroma_elapsed, 0, 0

    for start in range(0, len(index_docs), EMBEDDING_BATCH_SIZE):
        batch_number = start // EMBEDDING_BATCH_SIZE + 1
        total_batches = math.ceil(len(index_docs) / EMBEDDING_BATCH_SIZE)
        batch_docs = index_docs[start:start + EMBEDDING_BATCH_SIZE]
        batch_ids = [
            _build_index_document_id(document_id, doc.metadata, start + offset)
            for offset, doc in enumerate(batch_docs)
        ]
        batch_texts = [doc.page_content for doc in batch_docs]
        batch_metadatas = [doc.metadata for doc in batch_docs]

        embedding_start = time.perf_counter()
        _set_document_progress(
            document_id,
            30 + round((start / total_entries) * 60),
            "embedding",
            f"임베딩 중입니다. ({start}/{total_entries} index entries)"
        )
        logger.info(
            "[upload_embed] document_id=%s batch=%s/%s entries=%s model=%s num_thread=%s",
            document_id,
            batch_number,
            total_batches,
            len(batch_docs),
            OLLAMA_EMBEDDING_MODEL,
            OLLAMA_NUM_THREAD or "auto"
        )
        batch_vectors, embed_metadata = _embed_texts(batch_texts)
        batch_embedding_elapsed = time.perf_counter() - embedding_start
        embedding_elapsed += batch_embedding_elapsed
        ollama_total = _seconds_from_nanos(embed_metadata.get("total_duration"))
        ollama_load = _seconds_from_nanos(embed_metadata.get("load_duration"))
        ollama_prompt_eval = _seconds_from_nanos(embed_metadata.get("prompt_eval_duration"))
        logger.info(
            "[upload_embed_done] document_id=%s batch=%s/%s wall=%.2fs ollama_total=%s ollama_load=%s prompt_eval=%s prompt_eval_count=%s",
            document_id,
            batch_number,
            total_batches,
            batch_embedding_elapsed,
            _format_seconds(ollama_total),
            _format_seconds(ollama_load),
            _format_seconds(ollama_prompt_eval),
            embed_metadata.get("prompt_eval_count")
        )

        chroma_start = time.perf_counter()
        collection.add(
            ids=batch_ids,
            embeddings=batch_vectors,
            documents=batch_texts,
            metadatas=batch_metadatas
        )
        chroma_elapsed += time.perf_counter() - chroma_start
        completed_entries = min(start + len(batch_docs), total_entries)
        _set_document_progress(
            document_id,
            30 + round((completed_entries / total_entries) * 60),
            "embedding",
            f"임베딩과 벡터 저장을 진행 중입니다. ({completed_entries}/{total_entries} index entries)"
        )

    return page_match_elapsed, embedding_elapsed, chroma_elapsed, total_entries, table_fact_count


async def _run_upload_pipeline(tmp_path: str, filename: str, document_id: int) -> int:
    """문서 전처리 파이프라인: 로딩 → 정규화 → Two-Pass 청킹 → overlap → 임베딩 → ChromaDB 저장"""

    def _execute() -> int:
        total_start = time.perf_counter()
        _set_document_progress(document_id, 8, "parse", "문서를 파싱하고 있습니다.")

        # 파서 분기: 확장자에 따라 PDF 또는 Docling 로더 사용
        parse_start = time.perf_counter()
        raw_docs = _load_documents(tmp_path, filename)
        parse_elapsed = time.perf_counter() - parse_start
        _set_document_progress(document_id, 18, "parse", "문서 파싱을 완료했습니다.")

        page_lookup_start = time.perf_counter()
        page_lookup = _build_page_lookup(raw_docs)
        page_lookup_elapsed = time.perf_counter() - page_lookup_start
        _set_document_progress(document_id, 22, "page_lookup", "페이지 정보를 분석하고 있습니다.")

        # 로더 Document 단위 정규화. PDF는 page metadata를 보존해 구조 단서로 활용한다.
        normalize_start = time.perf_counter()
        normalized_docs = _normalize_loaded_documents(raw_docs)
        normalize_elapsed = time.perf_counter() - normalize_start
        _set_document_progress(document_id, 25, "normalize", "문서 텍스트를 정리했습니다.")

        # Two-Pass 청킹 + 연속 중복 line 정리 + 수동 overlap 후처리
        split_start = time.perf_counter()
        split_docs = _split_loaded_documents(normalized_docs)
        split_elapsed = time.perf_counter() - split_start
        _log_chunk_stats(document_id, filename, "split", split_docs)

        dedupe_start = time.perf_counter()
        deduped_docs = _dedupe_chunk_documents(split_docs)
        dedupe_elapsed = time.perf_counter() - dedupe_start
        _log_chunk_stats(document_id, filename, "deduped", deduped_docs)
        _set_document_progress(document_id, 28, "chunking", "문서를 청크로 나누고 있습니다.")

        merge_start = time.perf_counter()
        merged_docs = _merge_short_chunks(deduped_docs)
        merge_elapsed = time.perf_counter() - merge_start
        _log_chunk_stats(document_id, filename, "merged", merged_docs)

        overlap_start = time.perf_counter()
        final_docs = _apply_overlap(merged_docs)
        overlap_elapsed = time.perf_counter() - overlap_start
        _log_chunk_stats(document_id, filename, "final", final_docs)
        _set_document_progress(document_id, 30, "chunking", f"청킹을 완료했습니다. ({len(final_docs)} chunks)")

        # 임베딩 + ChromaDB 저장. 청크별 호출 대신 batch 단위로 처리해 HTTP 왕복과 저장 오버헤드를 줄인다.
        page_match_elapsed, embedding_elapsed, chroma_elapsed, index_entries, table_fact_entries = _store_document_chunks(
            final_docs,
            filename,
            document_id,
            page_lookup
        )
        _set_document_progress(document_id, 95, "chroma", "벡터 저장을 마무리하고 있습니다.")
        total_elapsed = time.perf_counter() - total_start
        logger.info(
            "[upload] document_id=%s filename=%s raw_docs=%s split_chunks=%s deduped_chunks=%s merged_chunks=%s chunks=%s index_entries=%s table_fact_entries=%s chunk_size=%s chunk_overlap=%s chunk_merge_min_size=%s table_fact_max_per_chunk=%s embed_table_raw_chunks=%s batch_size=%s parse=%.2fs page_lookup=%.2fs normalize=%.2fs split=%.2fs dedupe=%.2fs merge=%.2fs overlap=%.2fs page_match=%.2fs embed=%.2fs chroma_add=%.2fs total=%.2fs",
            document_id,
            filename,
            len(raw_docs),
            len(split_docs),
            len(deduped_docs),
            len(merged_docs),
            len(final_docs),
            index_entries,
            table_fact_entries,
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            CHUNK_MERGE_MIN_SIZE,
            TABLE_FACT_MAX_PER_CHUNK,
            EMBED_TABLE_RAW_CHUNKS,
            EMBEDDING_BATCH_SIZE,
            parse_elapsed,
            page_lookup_elapsed,
            normalize_elapsed,
            split_elapsed,
            dedupe_elapsed,
            merge_elapsed,
            overlap_elapsed,
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
    _set_document_progress(document_id, 0, "upload", "파일 업로드를 준비하고 있습니다.")
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

    _set_document_progress(document_id, 5, "upload", "파일 저장을 완료했습니다.")
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
        _set_document_progress(document_id, 100, "completed", "문서 처리가 완료되었습니다.", status="completed")
        return {
            "status": "success",
            "filename": filename,
            "chunks": chunk_count
        }
    except Exception:
        _set_document_progress(document_id, 100, "failed", "문서 처리에 실패했습니다.", status="failed")
        raise
    finally:
        os.unlink(tmp_path)


@app.get("/documents/{document_id}/progress")
def document_progress(document_id: int):
    """문서 처리 진행률을 반환한다."""
    return _get_document_progress(document_id)


# 질의응답 요청 스키마. Pydantic BaseModel로 JSON body를 자동 파싱·검증
class QueryRequest(BaseModel):
    question: str
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)  # 검색할 유사 청크 수
    system_prompt: str | None = None  # Spring Boot 관리자 프롬프트 설정. 미전달 시 기본값 사용


class RagTraceRequest(BaseModel):
    """RAG 검색 파이프라인을 답변 생성 없이 추적하기 위한 디버그 요청이다."""
    question: str
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)
    system_prompt: str | None = None
    include_vectors: bool = False
    vector_preview_size: int = Field(default=8, ge=0, le=32)


DEFAULT_SYSTEM_PROMPT = (
    "너는 인하공업전문대학 문서를 근거로 답변하는 안내 챗봇이다."
)

MANDATORY_RAG_PROMPT = (
    "필수 답변 규칙:\n"
    "1. 반드시 [검색 근거]에 있는 내용만 사용한다.\n"
    "2. [검색 근거]에 없는 절차, 조건, 날짜, 숫자, 서류, 주의사항, 조언은 만들지 않는다.\n"
    "3. 질문이 방법, 절차, 주의사항을 묻는 경우 [검색 근거]의 절차, 유의사항, 안내 문구를 우선 추출한다.\n"
    "4. 검색 근거에 '표 검색 정보'가 있으면 원본 표보다 먼저 사용해 행, 열, 값 관계를 판단한다.\n"
    "5. 표에서 숫자, 날짜, 인원, 점수, 기간을 답할 때는 질문의 행 이름과 열 이름에 직접 대응하는 값만 사용한다.\n"
    "6. 여러 표가 검색되면 질문의 단어와 가장 많이 겹치는 표 제목, 행 이름, 열 이름을 가진 근거를 우선한다.\n"
    "7. 질문에 없는 다른 표나 다른 섹션의 통계값을 섞지 않는다.\n"
    "8. '약', '일반적으로', '대부분의 경우'처럼 근거를 흐리는 표현을 쓰지 않는다.\n"
    "9. 근거가 부족하면 부족한 항목을 지어내지 말고 '제공된 문서에서는 확인할 수 없습니다.'라고 답한다.\n"
    "10. 문서에 없는 일반 조언이나 외부 지식을 덧붙이지 않는다."
)


QUERY_TERM_SYNONYMS = {
    "방법": {"방법", "절차", "신청", "신청절차", "제출"},
    "주의사항": {"주의사항", "유의사항", "유의", "주의"},
    "전과": {"전과", "전과제도", "전과시행"},
    "모집": {"모집", "모집인원", "모집정원", "정원"},
    "인원": {"인원", "모집인원", "모집정원", "정원"},
    "정원": {"정원", "모집인원", "모집정원", "인원"},
    "공식": {"공식", "수식"},
    "수식": {"수식", "공식"},
    "상수": {"상수", "계수", "값"},
    "계수": {"계수", "상수", "값"},
    "값": {"값", "수치"},
    "일정": {"일정", "기간", "날짜"},
    "기간": {"기간", "일정", "날짜"},
    "날짜": {"날짜", "일정", "기간"},
}

QUERY_GENERIC_TERMS = {
    "방법", "절차", "신청", "주의사항", "유의사항", "모집", "인원", "정원",
    "모집인원", "모집정원", "정보", "알려줘", "어디", "어떤", "뭐야", "무엇",
}

QUERY_TABLE_INTENT_TERMS = {
    "값", "수치", "공식", "수식", "상수", "계수", "인원", "정원", "모집", "모집인원", "모집정원",
    "점수", "가산점", "등급", "기간", "날짜", "일정", "서류", "자격", "학과", "과목", "항목",
}

TABLE_STATISTIC_TERMS = {"결과", "평균", "최저", "최고", "경쟁", "경쟁률", "예비", "순위", "등급"}
BM25_K1 = 1.5
BM25_B = 0.75
KIWI_SEARCH_TAG_PREFIXES = ("NN", "SL", "SN", "XR")
INTENT_PRIORITY = ("location", "time", "cost", "documents", "eligibility", "count", "schedule", "method", "formula", "list")
INTENT_QUERY_TERMS = {
    "list": {"무엇", "뭐", "무슨", "어떤", "목록", "종류", "있어", "있나요", "있습니까", "포함"},
    "location": {"어디", "위치", "장소", "주소", "소재지", "몇층", "층", "호관", "찾아오"},
    "time": {"시간", "이용시간", "운영시간", "언제", "몇시", "기간", "평일", "주말", "공휴일", "방학"},
    "cost": {"비용", "금액", "얼마", "요금", "가격", "납부", "원", "무료"},
    "documents": {"서류", "제출서류", "증빙", "첨부", "제출", "준비물"},
    "eligibility": {"자격", "지원자격", "대상", "조건", "요건"},
    "count": {"인원", "정원", "모집인원", "모집정원", "몇명", "명"},
    "method": {"방법", "절차", "어떻게", "신청", "진행", "처리"},
    "schedule": {"일정", "날짜", "기간", "접수", "발표", "마감"},
    "formula": {"공식", "수식", "계산", "산식"},
}
INTENT_EVIDENCE_TERMS = {
    "list": {"시설", "목록", "종류", "항목", "포함", "운영", "이용"},
    "location": {"위치", "장소", "주소", "소재지", "호관", "층", "도로", "길", "정문", "후문", "옆", "앞", "뒤", "내", "근처", "캠퍼스"},
    "time": {"시간", "이용", "이용시간", "운영시간", "기간", "평일", "주말", "공휴일", "방학", "중식", "휴무", "운영"},
    "cost": {"비용", "금액", "요금", "가격", "납부", "원", "무료", "환불"},
    "documents": {"서류", "제출서류", "증빙", "첨부", "제출", "발급", "원본", "사본"},
    "eligibility": {"자격", "대상", "조건", "요건", "해당자", "지원"},
    "count": {"인원", "정원", "모집", "모집인원", "모집정원", "명", "합계", "총"},
    "method": {"방법", "절차", "신청", "제출", "접수", "처리", "승인"},
    "schedule": {"일정", "날짜", "기간", "접수", "발표", "마감", "등록"},
    "formula": {"공식", "수식", "계산", "산식", "계수", "상수", "값"},
}
INTENT_EVIDENCE_PATTERNS = {
    "location": [
        r"\d+\s*호관",
        r"\d+\s*층",
        r"(정문|후문|도로|길|로|동|번지)\s*(앞|옆|뒤|근처|내)?",
    ],
    "time": [
        r"\d{1,2}\s*:\s*\d{2}",
        r"\d{1,2}\s*시",
        r"(평일|주말|공휴일|방학|중식|휴무)",
    ],
    "cost": [
        r"\d[\d,]*\s*원",
        r"(무료|비용|금액|요금)",
    ],
    "count": [
        r"\d[\d,]*\s*명",
        r"(모집\s*정원|모집\s*인원|합계|총)\s*[=:]?\s*\d+",
    ],
    "list": [
        r"^\s*[-*]\s+",
        r".+\s*:\s*.+",
    ],
}
QUERY_NON_SUBJECT_PATTERNS = (
    r"^(몇)?명(이야|인가요|인가|인지|입니까|이에요|예요)?$",
    r"^(몇)?시(야|인가요|인가|인지|입니까|이에요|예요)?$",
    r"^(어디|언제|무엇|뭐|어떤|무슨|어떻게)(.*)?$",
    r"^(있어|있나요|있습니까|돼|되나요|될까|인가요)$",
)


@dataclass(frozen=True)
class QueryAnalysis:
    """검색 재정렬에 사용할 질문 분석 결과다."""
    tokens: list[str]
    subject_terms: set[str]
    intent: str | None
    primary_terms: set[str]
    context_terms: set[str]


def _format_page_label(meta: dict) -> str:
    """검색 근거 context에 넣을 PDF page label을 만든다."""
    start_page = meta.get("page_start") or meta.get("page")
    end_page = meta.get("page_end")
    if start_page is None:
        return ""
    if end_page is not None and str(end_page) != str(start_page):
        return f"PDF {start_page}-{end_page}페이지"
    return f"PDF {start_page}페이지"


def _format_header_path(meta: dict) -> str:
    """검색 근거 context에 넣을 Markdown header 경로를 만든다."""
    headers = [
        str(meta.get(header_key, "")).strip()
        for header_key in ("Header 1", "Header 2", "Header 3", "Header 4", "Header 5", "Header 6")
        if str(meta.get(header_key, "")).strip()
    ]
    return " > ".join(headers)


def _format_chunk_label(meta: dict, chunk_id: str) -> str:
    """검색 근거 context에 넣을 문서 내 청크 순번 label을 만든다."""
    chunk_index = meta.get("chunk_index", _parse_chunk_index(chunk_id))
    if chunk_index is None:
        return ""
    try:
        return f"문서 내 {int(chunk_index) + 1}번째 청크"
    except (TypeError, ValueError):
        return f"문서 내 {chunk_index}번째 청크"


def _normalize_query_token(token: str) -> str:
    """조사와 어미가 붙은 질문 token을 검색 발췌용 핵심어로 정리한다."""
    normalized = token.strip().lower()
    for suffix in (
        "에게는", "한테는", "에서는", "으로는", "로는", "에는",
        "으로", "에서", "에게", "한테", "부터", "까지",
        "은", "는", "이", "가", "을", "를", "의", "도", "만", "와", "과", "에", "로",
    ):
        if len(normalized) > len(suffix) and normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _extract_query_terms(question: str) -> set[str]:
    """질문에서 검색 context 발췌에 사용할 핵심어와 간단한 동의어를 추출한다."""
    terms: set[str] = set()
    for token in re.findall(r"[0-9A-Za-z가-힣]+", question):
        normalized = _normalize_query_token(token)
        if len(normalized) < 2:
            continue
        terms.add(normalized)
        terms.update(QUERY_TERM_SYNONYMS.get(normalized, set()))
    return terms


def _extract_lexical_query_terms(question: str) -> tuple[set[str], set[str]]:
    """table_fact lexical 보강 검색에 사용할 주제어와 의도어를 나눈다."""
    subject_terms: set[str] = set()
    intent_terms: set[str] = set()

    for token in re.findall(r"[0-9A-Za-z가-힣]+", question):
        raw_token = token.strip().lower()
        normalized = _normalize_query_token(raw_token)
        if len(normalized) < 2 and normalized not in QUERY_TABLE_INTENT_TERMS:
            continue

        expanded_terms = {raw_token, normalized}
        expanded_terms.update(QUERY_TERM_SYNONYMS.get(normalized, set()))
        if expanded_terms & QUERY_TABLE_INTENT_TERMS:
            intent_terms.update(term for term in expanded_terms if len(term) >= 2)
        else:
            subject_terms.update(term for term in expanded_terms if len(term) >= 3 and term not in QUERY_GENERIC_TERMS)

    return subject_terms, intent_terms


def _score_table_fact_for_question(fact: str, question: str) -> int:
    """질문과 table_fact의 lexical 관련도를 계산한다."""
    fact_lower = fact.lower()
    subject_terms, intent_terms = _extract_lexical_query_terms(question)
    if subject_terms and not any(term in fact_lower for term in subject_terms):
        return 0

    score = 0
    score += sum(12 for term in subject_terms if term in fact_lower)
    score += sum(4 for term in intent_terms if term in fact_lower)

    asks_count_value = bool(intent_terms & {"모집", "인원", "정원", "모집인원", "모집정원"})
    has_primary_count_column = bool(re.search(r"(모집\s*정원|모집정원|합계|총|전체|total)\s*=", fact_lower))
    if asks_count_value and has_primary_count_column:
        score += 20
    if asks_count_value and any(term in fact_lower for term in TABLE_STATISTIC_TERMS):
        score -= 10

    return max(score, 0)


def _lookup_lexical_table_fact_candidates(question: str, limit: int = 5) -> list[dict]:
    """표 질의에서 벡터 검색이 놓치는 table_fact 후보를 score와 함께 찾는다."""
    subject_terms, intent_terms = _extract_lexical_query_terms(question)
    if not subject_terms or not intent_terms:
        return []

    try:
        results = collection.get(
            where={"chunk_role": "table_fact"},
            include=["documents", "metadatas"],
        )
    except Exception:
        logger.exception("[query_table_fact_lexical] failed")
        return []

    candidates: list[tuple[int, str, dict, str]] = []
    for chunk_id, document, metadata in zip(
        results.get("ids", []),
        results.get("documents", []),
        results.get("metadatas", []),
    ):
        score = _score_table_fact_for_question(str(document), question)
        if score <= 0:
            continue
        candidates.append((score, str(chunk_id), metadata or {}, str(document)))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    selected = candidates[:limit]
    logger.info(
        "[query_table_fact_lexical] subject_terms=%s intent_terms=%s candidates=%s selected=%s",
        ",".join(sorted(subject_terms)) or "none",
        ",".join(sorted(intent_terms)) or "none",
        len(candidates),
        len(selected),
    )
    return [
        {
            "rank": index + 1,
            "table_fact_score": score,
            "chunk_id": chunk_id,
            "document": document,
            "metadata": metadata,
        }
        for index, (score, chunk_id, metadata, document) in enumerate(selected)
    ]


def _lookup_lexical_table_facts(question: str, limit: int = 5) -> tuple[list[str], list[dict], list[str]]:
    """표 질의에서 벡터 검색이 놓치는 table_fact를 얇은 lexical 보강으로 찾는다."""
    selected = _lookup_lexical_table_fact_candidates(question, limit)
    return (
        [candidate["document"] for candidate in selected],
        [candidate["metadata"] for candidate in selected],
        [candidate["chunk_id"] for candidate in selected],
    )


def _get_kiwi():
    """Kiwi 형태소 분석기를 lazy initialization으로 준비한다."""
    global _kiwi_analyzer
    if Kiwi is None:
        return None
    if _kiwi_analyzer is None:
        with _kiwi_lock:
            if _kiwi_analyzer is None:
                _kiwi_analyzer = Kiwi()
    return _kiwi_analyzer


def _tokenize_sparse_search_fallback(text: str) -> list[str]:
    """Kiwi를 사용할 수 없을 때 BM25 검색에 쓸 fallback token을 만든다."""
    tokens: list[str] = []
    for raw_token in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()):
        normalized = _normalize_query_token(raw_token)
        for token in {raw_token, normalized}:
            if len(token) < 2:
                continue
            tokens.append(token)
    return tokens


def _tokenize_sparse_search(text: str) -> list[str]:
    """한국어 형태소 분석 기반 BM25 token을 만든다."""
    kiwi = _get_kiwi()
    if kiwi is None:
        return _tokenize_sparse_search_fallback(text)

    tokens: list[str] = []
    try:
        analyzed_tokens = kiwi.tokenize(text, normalize_coda=True)
    except Exception:
        logger.exception("[query_tokenize] kiwi_failed")
        return _tokenize_sparse_search_fallback(text)

    for token in analyzed_tokens:
        form = str(getattr(token, "form", "")).strip().lower()
        tag = str(getattr(token, "tag", ""))
        if len(form) < 2:
            continue
        if tag.startswith(KIWI_SEARCH_TAG_PREFIXES):
            tokens.append(form)

    if tokens:
        return tokens
    return _tokenize_sparse_search_fallback(text)


def _detect_query_intent(question: str, tokens: list[str]) -> str | None:
    """질문이 묻는 속성 intent를 보수적으로 분류한다."""
    normalized_question = question.lower().replace(" ", "")
    token_set = set(tokens)
    for intent in INTENT_PRIORITY:
        terms = INTENT_QUERY_TERMS.get(intent, set())
        if token_set & terms:
            return intent
        if any(term in normalized_question for term in terms if len(term) >= 2):
            return intent
    return None


def _is_non_subject_query_token(token: str, intent_terms: set[str]) -> bool:
    """질문 기능어와 intent 표현을 subject 후보에서 제외한다."""
    if token in QUERY_GENERIC_TERMS or token in intent_terms:
        return True
    if any(re.match(pattern, token) for pattern in QUERY_NON_SUBJECT_PATTERNS):
        return True
    if any(term in token for term in intent_terms if len(term) >= 2):
        return True
    return False


def _analyze_query(question: str) -> QueryAnalysis:
    """검색 후보 재정렬에 사용할 subject와 intent를 분석한다."""
    tokens = _tokenize_sparse_search(question)
    intent = _detect_query_intent(question, tokens)
    intent_terms = set().union(*INTENT_QUERY_TERMS.values())
    subject_exclusion_terms = set(intent_terms)
    if intent and intent != "list":
        subject_exclusion_terms.update(INTENT_EVIDENCE_TERMS.get(intent, set()))
    subject_terms: set[str] = set()
    for token in tokens:
        normalized = _normalize_query_token(token)
        candidate = normalized if len(normalized) >= 2 else token
        if len(candidate) >= 2 and not _is_non_subject_query_token(candidate, subject_exclusion_terms):
            subject_terms.add(candidate)
    raw_terms = _extract_query_terms(question)
    primary_terms = {
        term for term in raw_terms
        if len(term) >= 2 and not _is_non_subject_query_token(term, subject_exclusion_terms)
    }
    context_terms = set(tokens)
    context_terms.update(raw_terms)
    context_terms.update(subject_terms)
    context_terms.update(primary_terms)
    return QueryAnalysis(
        tokens=tokens,
        subject_terms=subject_terms,
        intent=intent,
        primary_terms=primary_terms,
        context_terms={term for term in context_terms if len(term) >= 2},
    )


def _build_sparse_search_text(document: str, metadata: dict) -> str:
    """raw chunk 본문과 header 경로를 BM25 scoring 대상 text로 합친다."""
    header_path = _format_header_path(metadata)
    if not header_path:
        return document
    return f"{header_path}\n{header_path}\n{document}"


def _calculate_bm25_scores(query_tokens: list[str], corpus_tokens: list[list[str]]) -> list[float]:
    """raw chunk corpus에 대해 BM25 sparse retrieval score를 계산한다."""
    if not query_tokens or not corpus_tokens:
        return []

    document_count = len(corpus_tokens)
    document_frequencies: dict[str, int] = {}
    term_frequencies: list[dict[str, int]] = []
    document_lengths: list[int] = []

    for tokens in corpus_tokens:
        frequencies: dict[str, int] = {}
        for token in tokens:
            frequencies[token] = frequencies.get(token, 0) + 1
        term_frequencies.append(frequencies)
        document_lengths.append(len(tokens))
        for token in frequencies:
            document_frequencies[token] = document_frequencies.get(token, 0) + 1

    average_length = sum(document_lengths) / document_count if document_count else 0.0
    if average_length <= 0:
        return [0.0 for _ in corpus_tokens]

    scores: list[float] = []
    for frequencies, document_length in zip(term_frequencies, document_lengths):
        score = 0.0
        for token in query_tokens:
            term_frequency = frequencies.get(token, 0)
            if term_frequency <= 0:
                continue

            frequency = document_frequencies.get(token, 0)
            inverse_document_frequency = math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))
            denominator = term_frequency + BM25_K1 * (1 - BM25_B + BM25_B * document_length / average_length)
            score += inverse_document_frequency * (term_frequency * (BM25_K1 + 1) / denominator)
        scores.append(score)
    return scores


def _lookup_bm25_raw_chunk_candidates(analysis: QueryAnalysis, limit: int = 5) -> list[dict]:
    """BM25 sparse retrieval 후보를 score와 함께 반환한다."""
    query_tokens = analysis.tokens
    if not query_tokens:
        return []

    try:
        results = collection.get(include=["documents", "metadatas"])
    except Exception:
        logger.exception("[query_bm25] failed")
        return []

    records: list[tuple[str, str, dict]] = []
    corpus_tokens: list[list[str]] = []
    for chunk_id, document, metadata in zip(
        results.get("ids", []),
        results.get("documents", []),
        results.get("metadatas", []),
    ):
        metadata = metadata or {}
        if metadata.get("chunk_role") == "table_fact":
            continue

        document_text = str(document)
        records.append((str(chunk_id), document_text, metadata))
        corpus_tokens.append(_tokenize_sparse_search(_build_sparse_search_text(document_text, metadata)))

    scores = _calculate_bm25_scores(query_tokens, corpus_tokens)
    candidates = [
        (score, position, *record)
        for position, (score, record) in enumerate(zip(scores, records))
        if score > 0
    ]
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    selected = candidates[:limit]
    logger.info(
        "[query_bm25] query_tokens=%s intent=%s subject_terms=%s candidates=%s selected=%s top_score=%s",
        ",".join(query_tokens) or "none",
        analysis.intent or "none",
        ",".join(sorted(analysis.subject_terms)) or "none",
        len(candidates),
        len(selected),
        _format_decimal(selected[0][0] if selected else None),
    )
    return [
        {
            "rank": index + 1,
            "bm25_score": float(score),
            "chunk_id": chunk_id,
            "document": document,
            "metadata": metadata,
        }
        for index, (score, _, chunk_id, document, metadata) in enumerate(selected)
    ]


def _lookup_bm25_raw_chunks(analysis: QueryAnalysis, limit: int = 5) -> tuple[list[str], list[dict], list[str]]:
    """BM25 sparse retrieval로 vector search가 놓친 raw chunk 후보를 보강한다."""
    selected = _lookup_bm25_raw_chunk_candidates(analysis, limit)
    return (
        [candidate["document"] for candidate in selected],
        [candidate["metadata"] for candidate in selected],
        [candidate["chunk_id"] for candidate in selected],
    )


def _is_table_value_question(question: str) -> bool:
    """표 행/열 값을 묻는 질문인지 보수적으로 판단한다."""
    subject_terms, intent_terms = _extract_lexical_query_terms(question)
    return bool(subject_terms and intent_terms)


def _attach_runtime_table_facts(question: str, docs: list[str], metadatas: list[dict]) -> list[dict]:
    """검색된 raw 청크 안의 표에서 질문과 맞는 fact를 런타임 metadata에 붙인다."""
    if not _is_table_value_question(question):
        return metadatas

    updated_metadatas: list[dict] = []
    for doc, meta in zip(docs, metadatas):
        runtime_meta = dict(meta or {})
        if runtime_meta.get("chunk_role") == "table_fact":
            updated_metadatas.append(runtime_meta)
            continue

        scored_facts: list[tuple[int, str]] = []
        for fact in _extract_table_facts(doc, runtime_meta):
            score = _score_table_fact_for_question(fact, question)
            if score > 0:
                scored_facts.append((score, fact))

        scored_facts.sort(key=lambda item: item[0], reverse=True)
        for _, fact in scored_facts[:2]:
            runtime_meta = _append_runtime_table_fact(runtime_meta, fact)
        updated_metadatas.append(runtime_meta)

    return updated_metadatas


def _best_runtime_table_fact_score(meta: dict, question: str) -> int:
    """runtime metadata에 붙은 table_fact 중 질문과 가장 관련 높은 점수를 반환한다."""
    matched_table_facts = meta.get("matched_table_facts", "")
    if isinstance(matched_table_facts, list):
        facts = [str(fact) for fact in matched_table_facts]
    elif matched_table_facts:
        facts = [str(matched_table_facts)]
    else:
        facts = []
    return max((_score_table_fact_for_question(fact, question) for fact in facts), default=0)


def _score_subject_match(text: str, analysis: QueryAnalysis) -> int:
    """후보 청크가 질문 subject와 얼마나 직접적으로 맞는지 계산한다."""
    if not analysis.subject_terms and not analysis.primary_terms:
        return 0

    normalized_text = text.lower()
    score = 0
    for term in analysis.primary_terms:
        count = normalized_text.count(term)
        if count > 0:
            score += min(count, 4) * 18

    matched = 0
    for term in analysis.subject_terms:
        count = normalized_text.count(term)
        if count <= 0:
            continue
        matched += 1
        score += min(count, 5) * 12

    if matched == len(analysis.subject_terms):
        score += 20
    return score


def _count_item_like_lines(text: str) -> int:
    """목록형 답변에 도움이 되는 항목 line 개수를 계산한다."""
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^[-*]\s+", stripped) or re.search(r"\S+\s*:\s*\S+", stripped):
            count += 1
    return count


def _score_intent_evidence(text: str, analysis: QueryAnalysis) -> int:
    """후보 청크가 질문 intent에 답할 증거 패턴을 포함하는지 계산한다."""
    if not analysis.intent:
        return 0

    normalized_text = text.lower()
    evidence_terms = INTENT_EVIDENCE_TERMS.get(analysis.intent, set())
    score = sum(6 for term in evidence_terms if term in normalized_text)

    for pattern in INTENT_EVIDENCE_PATTERNS.get(analysis.intent, []):
        score += min(len(re.findall(pattern, normalized_text, flags=re.MULTILINE)), 5) * 8

    if analysis.intent == "list":
        score += min(_count_item_like_lines(text), 8) * 8
    return score


def _score_heading_match(text: str, analysis: QueryAnalysis) -> int:
    """Markdown heading이 질문 subject 또는 intent와 직접 맞는지 계산한다."""
    if not analysis.context_terms:
        return 0

    score = 0
    for line in text.splitlines():
        if _markdown_heading_level(line) is None:
            continue
        normalized_line = line.lower()
        if any(term in normalized_line for term in analysis.primary_terms):
            score += 40
        if any(term in normalized_line for term in analysis.subject_terms):
            score += 30
        if analysis.intent and any(term in normalized_line for term in INTENT_EVIDENCE_TERMS.get(analysis.intent, set())):
            score += 10
    return score


def _score_candidate_for_query(doc: str, meta: dict, question: str, analysis: QueryAnalysis) -> int:
    """subject와 intent를 함께 고려해 검색 후보를 재정렬할 점수를 만든다."""
    search_text = _build_sparse_search_text(doc, meta)
    score = 0
    score += _score_subject_match(search_text, analysis)
    score += _score_intent_evidence(search_text, analysis)
    score += _score_heading_match(search_text, analysis)
    score += _best_runtime_table_fact_score(meta or {}, question)
    return score


def _rerank_by_query_analysis(
    docs: list[str],
    metadatas: list[dict],
    ids: list[str],
    question: str,
    analysis: QueryAnalysis,
) -> tuple[list[str], list[dict], list[str]]:
    """질문 subject와 intent가 모두 맞는 후보를 앞쪽으로 재정렬한다."""
    if not docs or (not analysis.subject_terms and not analysis.intent):
        return docs, metadatas, ids

    ranked: list[tuple[int, int, str, dict, str]] = []
    for index, (doc, meta, chunk_id) in enumerate(zip(docs, metadatas, ids)):
        meta = meta or {}
        score = _score_candidate_for_query(doc, meta, question, analysis)
        ranked.append((-score, index, doc, meta, chunk_id))

    ranked.sort(key=lambda item: (item[0], item[1]))
    best_score = -ranked[0][0] if ranked else 0
    logger.info(
        "[query_rerank] intent=%s subject_terms=%s best_score=%s candidates=%s",
        analysis.intent or "none",
        ",".join(sorted(analysis.subject_terms)) or "none",
        best_score,
        len(ranked),
    )
    return (
        [doc for _, _, doc, _, _ in ranked],
        [meta for _, _, _, meta, _ in ranked],
        [chunk_id for _, _, _, _, chunk_id in ranked],
    )


def _prioritize_query_results(docs: list[str], metadatas: list[dict], ids: list[str], question: str) -> tuple[list[str], list[dict], list[str]]:
    """표 값 질문에서는 질문과 가장 잘 맞는 table_fact context를 앞세운다."""
    if not _is_table_value_question(question):
        return docs, metadatas, ids

    scores = [_best_runtime_table_fact_score(meta or {}, question) for meta in metadatas]
    best_score = max(scores, default=0)
    if best_score <= 0:
        return docs, metadatas, ids

    ranked: list[tuple[int, int, str, dict, str]] = []
    for index, (doc, meta, chunk_id) in enumerate(zip(docs, metadatas, ids)):
        meta = meta or {}
        score = scores[index]
        if best_score >= 40 and score < best_score - 15:
            continue
        if score == 0 and best_score >= 20:
            continue
        priority = -score
        ranked.append((priority, index, doc, meta, chunk_id))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return (
        [doc for _, _, doc, _, _ in ranked],
        [meta for _, _, _, meta, _ in ranked],
        [chunk_id for _, _, _, _, chunk_id in ranked],
    )


def _markdown_heading_level(line: str) -> int | None:
    """Markdown heading line이면 heading level을 반환한다."""
    match = re.match(r"^(#{1,6})\s+", line.strip())
    if not match:
        return None
    return len(match.group(1))


def _select_heading_section_excerpt(lines: list[str], query_terms: set[str], max_lines: int) -> list[str]:
    """질문어가 heading에 걸리면 해당 heading 아래 section을 발췌한다."""
    if not query_terms:
        return []

    for index, line in enumerate(lines):
        line_level = _markdown_heading_level(line)
        if line_level is None:
            continue

        normalized_line = line.lower()
        if not any(term in normalized_line for term in query_terms):
            continue

        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            next_level = _markdown_heading_level(lines[next_index])
            if next_level is not None and next_level <= line_level:
                end = next_index
                break
        return lines[index:end][:max_lines]
    return []


def _find_parent_heading_index(lines: list[str], line_index: int) -> int | None:
    """line이 속한 가장 가까운 이전 Markdown heading 위치를 찾는다."""
    for index in range(line_index - 1, -1, -1):
        if _markdown_heading_level(lines[index]) is not None:
            return index
    return None


def _find_next_heading_index(lines: list[str], line_index: int) -> int:
    """line 이후에 나오는 다음 Markdown heading 위치를 찾는다."""
    for index in range(line_index + 1, len(lines)):
        if _markdown_heading_level(lines[index]) is not None:
            return index
    return len(lines)


def _select_item_with_parent_excerpt(lines: list[str], query_terms: set[str], window: int, max_lines: int) -> list[str]:
    """질문어가 항목 line에 걸리면 부모 heading과 해당 항목 주변을 함께 발췌한다."""
    if not query_terms:
        return []

    for index, line in enumerate(lines):
        if _markdown_heading_level(line) is not None:
            continue

        normalized_line = line.lower()
        if not any(term in normalized_line for term in query_terms):
            continue

        selected: list[str] = []
        parent_heading_index = _find_parent_heading_index(lines, index)
        section_start = parent_heading_index + 1 if parent_heading_index is not None else 0
        section_end = _find_next_heading_index(lines, index)
        if parent_heading_index is not None:
            selected.append(lines[parent_heading_index])

        start = max(section_start, index - window)
        end = min(section_end, index + window + 1)
        for candidate_index in range(start, end):
            candidate = lines[candidate_index]
            if _markdown_heading_level(candidate) is not None:
                continue
            selected.append(candidate)
        return selected[:max_lines]
    return []


def _select_relevant_excerpt(text: str, query_terms: set[str], window: int = 2, max_lines: int = 18) -> str:
    """청크 안에서 질문 핵심어와 가까운 실제 line들을 골라 LLM 주의 집중용 발췌를 만든다."""
    if not query_terms:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    heading_excerpt = _select_heading_section_excerpt(lines, query_terms, max_lines)
    if heading_excerpt:
        return "\n".join(heading_excerpt)

    item_excerpt = _select_item_with_parent_excerpt(lines, query_terms, window, max_lines)
    if item_excerpt:
        return "\n".join(item_excerpt)

    selected_indexes: set[int] = set()

    for index, line in enumerate(lines):
        normalized_line = line.lower()
        if not any(term in normalized_line for term in query_terms):
            continue
        start = max(0, index - window)
        end = min(len(lines), index + window + 1)
        selected_indexes.update(range(start, end))

    if not selected_indexes:
        return ""

    selected_lines = [lines[index] for index in sorted(selected_indexes)]
    return "\n".join(selected_lines[:max_lines])


def _line_matches_query_subject(line: str, analysis: QueryAnalysis) -> bool:
    """line이 질문 subject 항목을 직접 설명하는지 판단한다."""
    normalized_line = line.lower()
    has_item_label = ":" in line or "：" in line
    label_text = re.split(r"[:：]", line, maxsplit=1)[0].strip().lower() if has_item_label else normalized_line
    search_text = label_text if has_item_label else normalized_line

    primary_terms = {term for term in analysis.primary_terms if len(term) >= 2}
    if any(term in search_text for term in primary_terms):
        return True

    subject_terms = {term for term in analysis.subject_terms if len(term) >= 2}
    if len(subject_terms) >= 2 and all(term in search_text for term in subject_terms):
        return True
    return len(subject_terms) == 1 and any(term in search_text for term in subject_terms)


def _extract_item_label(line: str, analysis: QueryAnalysis) -> str:
    """항목형 line에서 답변에 사용할 label을 추출한다."""
    if ":" in line:
        return line.split(":", 1)[0].strip()
    if "：" in line:
        return line.split("：", 1)[0].strip()
    for term in sorted(analysis.primary_terms, key=len, reverse=True):
        if term in line:
            return term
    for term in sorted(analysis.subject_terms, key=len, reverse=True):
        if term in line:
            return term
    return "관련 항목"


def _extract_colon_value(line: str) -> str:
    """항목형 line에서 첫 번째 colon 뒤 값을 추출한다."""
    if ":" in line:
        return line.split(":", 1)[1].strip()
    if "：" in line:
        return line.split("：", 1)[1].strip()
    return line.strip()


def _extract_location_answer_value(line: str) -> str:
    """위치 질문에 답할 수 있는 항목 값을 line에서 추출한다."""
    value = _extract_colon_value(line)
    value = re.split(
        r"\s*/\s*|\s+이용\s*시간|\s+이용시간|\s+운영\s*시간|\s+운영시간|\s+\d{2,3}-\d{3,4}-\d{4}|\s+\d{1,2}\s*시간",
        value,
        maxsplit=1,
    )[0].strip()
    return value or line.strip()


def _extract_time_answer_value(line: str) -> str:
    """시간 질문에 답할 수 있는 항목 값을 line에서 추출한다."""
    time_label_match = re.search(r"(?:이용\s*시간|이용시간|운영\s*시간|운영시간)[^:：]*[:：]\s*(.+)", line)
    if time_label_match:
        return time_label_match.group(1).strip()

    time_range_match = re.search(r"\d{1,2}\s*:\s*\d{2}\s*[~∼-]\s*\d{1,2}\s*:\s*\d{2}(?:\([^)]*\))?", line)
    if time_range_match:
        return time_range_match.group(0).strip()
    return line.strip()


def _format_query_evidence_fact(line: str, analysis: QueryAnalysis) -> str:
    """검색된 항목 line을 질문 intent에 맞는 구조화 근거로 바꾼다."""
    label = _extract_item_label(line, analysis)
    if analysis.intent == "location":
        return f"- {label} 위치: {_extract_location_answer_value(line)}"
    if analysis.intent == "time":
        return f"- {label} 이용/운영시간: {_extract_time_answer_value(line)}"
    if analysis.intent == "list":
        return f"- 관련 항목: {line.strip()}"
    return f"- 관련 근거: {line.strip()}"


def _extract_query_evidence_facts(text: str, analysis: QueryAnalysis, max_facts: int = 3) -> str:
    """검색된 chunk에서 질문 subject와 intent가 직접 만나는 항목 근거를 추출한다."""
    if not analysis.intent:
        return ""

    facts: list[str] = []
    seen: set[str] = set()
    for line in (line.strip() for line in text.splitlines() if line.strip()):
        if _markdown_heading_level(line) is not None:
            continue
        if not _line_matches_query_subject(line, analysis):
            continue

        fact = _format_query_evidence_fact(line, analysis)
        if fact in seen:
            continue
        seen.add(fact)
        facts.append(fact)
        if len(facts) >= max_facts:
            break

    return "\n".join(facts)


def _format_context_block(index: int, doc: str, meta: dict, chunk_id: str, analysis: QueryAnalysis) -> str:
    """LLM이 검색 근거 단위를 구분할 수 있도록 출처 metadata와 청크 본문을 함께 포맷한다."""
    source_name = str(meta.get("source", "")).strip() or "알 수 없는 문서"
    metadata_lines = [f"문서: {source_name}"]

    page_label = _format_page_label(meta)
    if page_label:
        metadata_lines.append(f"위치: {page_label}")

    chunk_label = _format_chunk_label(meta, chunk_id)
    if chunk_label:
        metadata_lines.append(f"청크: {chunk_label}")

    header_path = _format_header_path(meta)
    if header_path:
        metadata_lines.append(f"섹션: {header_path}")

    metadata = "\n".join(metadata_lines)
    evidence_facts = _extract_query_evidence_facts(doc, analysis)
    relevant_excerpt = _select_relevant_excerpt(doc, analysis.primary_terms)
    if not relevant_excerpt:
        relevant_excerpt = _select_relevant_excerpt(doc, analysis.context_terms)
    matched_table_facts = meta.get("matched_table_facts", "")
    fact_text = ""
    if isinstance(matched_table_facts, list):
        fact_text = "\n".join(str(fact).strip() for fact in matched_table_facts if str(fact).strip())
    elif matched_table_facts:
        fact_text = str(matched_table_facts).strip()

    table_fact_block = f"\n표 검색 정보:\n{fact_text}" if fact_text else ""
    evidence_fact_block = f"\n질문 의도 추출 정보:\n{evidence_facts}" if evidence_facts else ""
    if relevant_excerpt:
        return f"[출처 {index}]\n{metadata}{table_fact_block}{evidence_fact_block}\n질문 관련 발췌:\n{relevant_excerpt}\n전체 내용:\n{doc.strip()}"
    return f"[출처 {index}]\n{metadata}{table_fact_block}{evidence_fact_block}\n전체 내용:\n{doc.strip()}"


def _build_context(docs: list[str], metadatas: list[dict], ids: list[str], analysis: QueryAnalysis) -> str:
    """검색된 청크들을 출처 단위 context로 변환한다."""
    blocks = []
    for index, (doc, meta, chunk_id) in enumerate(zip(docs, metadatas, ids), start=1):
        blocks.append(_format_context_block(index, doc, meta or {}, chunk_id, analysis))
    return "\n\n".join(blocks)


def _load_parent_chunk(parent_chunk_id: str) -> tuple[str | None, dict | None]:
    """table_fact 검색 결과가 가리키는 원본 청크를 ChromaDB에서 조회한다."""
    if not parent_chunk_id:
        return None, None

    try:
        result = collection.get(ids=[parent_chunk_id], include=["documents", "metadatas"])
    except Exception:
        logger.exception("[query_context] failed_to_load_parent_chunk parent_id=%s", parent_chunk_id)
        return None, None

    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    if not documents:
        return None, None
    return documents[0], (metadatas[0] if metadatas else {})


def _build_parent_metadata_from_fact(fact_meta: dict) -> dict:
    """table_fact metadata에서 사용자에게 노출할 부모 raw 청크 metadata를 복원한다."""
    parent_meta = dict(fact_meta or {})
    parent_meta["chunk_role"] = "raw"
    if "parent_chunk_index" in parent_meta:
        parent_meta["chunk_index"] = parent_meta["parent_chunk_index"]

    for key in ("parent_content", "parent_chunk_id", "parent_chunk_index", "fact_index"):
        parent_meta.pop(key, None)
    return parent_meta


def _append_runtime_table_fact(meta: dict, fact_text: str) -> dict:
    """검색된 table_fact를 원본 청크 runtime metadata에 누적한다."""
    if not fact_text.strip():
        return meta

    next_meta = dict(meta)
    existing = next_meta.get("matched_table_facts")
    if isinstance(existing, list):
        if fact_text not in existing:
            existing.append(fact_text)
        next_meta["matched_table_facts"] = existing
    elif existing:
        if fact_text != existing:
            next_meta["matched_table_facts"] = [str(existing), fact_text]
    else:
        next_meta["matched_table_facts"] = [fact_text]
    return next_meta


def _expand_table_fact_results(docs: list[str], metadatas: list[dict], ids: list[str]) -> tuple[list[str], list[dict], list[str]]:
    """검색된 table_fact를 부모 원본 청크와 연결해 답변 context를 구성한다."""
    expanded_docs: list[str] = []
    expanded_metadatas: list[dict] = []
    expanded_ids: list[str] = []
    seen_indexes: dict[str, int] = {}

    for doc, meta, chunk_id in zip(docs, metadatas, ids):
        meta = meta or {}
        if meta.get("chunk_role") != "table_fact":
            result_id = str(chunk_id)
            if result_id in seen_indexes:
                continue
            seen_indexes[result_id] = len(expanded_docs)
            expanded_docs.append(doc)
            expanded_metadatas.append(meta)
            expanded_ids.append(result_id)
            continue

        parent_chunk_id = str(meta.get("parent_chunk_id", "")).strip()
        parent_doc, parent_meta = _load_parent_chunk(parent_chunk_id)
        if not parent_doc and meta.get("parent_content"):
            parent_doc = str(meta.get("parent_content", ""))
            parent_meta = _build_parent_metadata_from_fact(meta)
        if not parent_doc:
            result_id = str(chunk_id)
            seen_indexes[result_id] = len(expanded_docs)
            expanded_docs.append(doc)
            expanded_metadatas.append(meta)
            expanded_ids.append(result_id)
            continue

        result_id = parent_chunk_id
        fact_text = doc.strip()
        if result_id in seen_indexes:
            existing_index = seen_indexes[result_id]
            expanded_metadatas[existing_index] = _append_runtime_table_fact(expanded_metadatas[existing_index], fact_text)
            continue

        runtime_meta = dict(parent_meta or {})
        runtime_meta["matched_chunk_role"] = "table_fact"
        runtime_meta = _append_runtime_table_fact(runtime_meta, fact_text)
        seen_indexes[result_id] = len(expanded_docs)
        expanded_docs.append(parent_doc)
        expanded_metadatas.append(runtime_meta)
        expanded_ids.append(result_id)

    return expanded_docs, expanded_metadatas, expanded_ids


def _build_rag_prompt(system_prompt: str | None, context: str, question: str) -> str:
    """검색 근거와 사용자 질문을 LLM 입력 프롬프트로 조합한다."""
    prompt_policy = system_prompt.strip() if system_prompt and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT
    return f"""{prompt_policy}

{MANDATORY_RAG_PROMPT}

[검색 근거]
{context}

[사용자 질문]
{question}

[답변 직전 확인]
- 답변은 [검색 근거]에 직접 적힌 내용만 사용한다.
- [검색 근거]의 '질문 의도 추출 정보'가 있으면 답변에 가장 먼저 사용한다.
- [검색 근거]의 '표 검색 정보'가 있으면 표의 행/열/값 판단에 우선 사용한다.
- [검색 근거]의 '질문 관련 발췌'가 있으면 그 발췌에 직접 적힌 항목만 우선 사용한다.
- 질문 단어와 일치하는 섹션 제목이 있으면 해당 섹션 아래 내용만 답변한다.
- 같은 청크 안에 다른 섹션이 있어도 질문과 맞지 않으면 답변에 섞지 않는다.
- 근거에 없는 일반적인 대학 행정 절차나 조언은 쓰지 않는다.

[답변 작성]
"""


def _candidate_parent_key(chunk_id: str, metadata: dict) -> str:
    """table_fact 후보는 부모 raw chunk 기준으로 trace key를 통일한다."""
    parent_chunk_id = str(metadata.get("parent_chunk_id", "")).strip()
    if metadata.get("chunk_role") == "table_fact" and parent_chunk_id:
        return parent_chunk_id
    return str(chunk_id)


def _ensure_trace_entry(trace_by_id: dict[str, dict], key: str) -> dict:
    """후보별 retrieval trace 누적 공간을 만든다."""
    if key not in trace_by_id:
        trace_by_id[key] = {"retrieval_methods": []}
    return trace_by_id[key]


def _append_trace_method(entry: dict, method: str) -> None:
    """후보가 어떤 검색 단계에서 들어왔는지 중복 없이 기록한다."""
    methods = entry.setdefault("retrieval_methods", [])
    if method not in methods:
        methods.append(method)


def _candidate_location_summary(chunk_id: str, doc: str, meta: dict, preview_chars: int = 360) -> dict:
    """trace 후보의 문서 위치와 본문 미리보기를 만든다."""
    meta = meta or {}
    return {
        "chunk_id": str(chunk_id),
        "document_id": meta.get("document_id", ""),
        "source": meta.get("source", ""),
        "chunk_role": meta.get("chunk_role", "raw"),
        "matched_chunk_role": meta.get("matched_chunk_role"),
        "page": meta.get("page"),
        "page_start": meta.get("page_start"),
        "page_end": meta.get("page_end"),
        "chunk_index": meta.get("chunk_index", _parse_chunk_index(str(chunk_id))),
        "header_path": _format_header_path(meta),
        "content_preview": _preview_text(doc, preview_chars),
    }


def _record_vector_trace(
    trace_by_id: dict[str, dict],
    chunk_id: str,
    doc: str,
    meta: dict,
    rank: int,
    distance: float | None,
    metric: str,
) -> None:
    """벡터 검색 후보의 distance와 원본 hit 정보를 trace에 기록한다."""
    key = _candidate_parent_key(chunk_id, meta)
    entry = _ensure_trace_entry(trace_by_id, key)
    _append_trace_method(entry, "vector")
    entry.setdefault("vector_rank", rank)
    entry.setdefault("vector_distance", _round_float(distance))
    entry.setdefault("vector_similarity_if_cosine", _similarity_if_cosine(distance, metric))
    entry.setdefault("vector_hit_chunk_id", str(chunk_id))
    entry.setdefault("vector_hit_chunk_role", meta.get("chunk_role", "raw"))
    if meta.get("chunk_role") == "table_fact":
        entry.setdefault("vector_hit_fact_preview", _preview_text(doc, 240))


def _record_bm25_trace(trace_by_id: dict[str, dict], candidate: dict) -> None:
    """BM25 후보의 score를 trace에 기록한다."""
    chunk_id = str(candidate["chunk_id"])
    meta = candidate["metadata"] or {}
    entry = _ensure_trace_entry(trace_by_id, chunk_id)
    _append_trace_method(entry, "bm25")
    entry.setdefault("bm25_rank", candidate["rank"])
    entry.setdefault("bm25_score", _round_float(candidate["bm25_score"], 4))


def _record_table_fact_trace(trace_by_id: dict[str, dict], candidate: dict) -> None:
    """table_fact lexical 후보의 score와 부모 chunk 정보를 trace에 기록한다."""
    chunk_id = str(candidate["chunk_id"])
    meta = candidate["metadata"] or {}
    key = _candidate_parent_key(chunk_id, meta)
    entry = _ensure_trace_entry(trace_by_id, key)
    _append_trace_method(entry, "table_fact_lexical")
    entry.setdefault("table_fact_rank", candidate["rank"])
    entry.setdefault("table_fact_score", candidate["table_fact_score"])
    entry.setdefault("table_fact_hit_chunk_id", chunk_id)
    entry.setdefault("table_fact_preview", _preview_text(candidate["document"], 240))


def _format_vector_candidate(
    rank: int,
    chunk_id: str,
    doc: str,
    meta: dict,
    distance: float | None,
    metric: str,
    embedding: list[float] | None,
    vector_preview_size: int,
) -> dict:
    """초기 Chroma vector search 후보를 trace 응답 형태로 만든다."""
    candidate = _candidate_location_summary(chunk_id, doc, meta)
    candidate.update({
        "rank": rank,
        "distance": _round_float(distance),
        "similarity_if_cosine": _similarity_if_cosine(distance, metric),
    })
    if embedding is not None:
        candidate["embedding_dimension"] = len(embedding)
        candidate["embedding_preview"] = _vector_preview(embedding, vector_preview_size)
    return candidate


def _format_bm25_candidate(candidate: dict) -> dict:
    """BM25 후보를 trace 응답 형태로 만든다."""
    formatted = _candidate_location_summary(
        str(candidate["chunk_id"]),
        candidate["document"],
        candidate["metadata"] or {},
    )
    formatted.update({
        "rank": candidate["rank"],
        "bm25_score": _round_float(candidate["bm25_score"], 4),
    })
    return formatted


def _format_table_fact_candidate(candidate: dict) -> dict:
    """table_fact lexical 후보를 trace 응답 형태로 만든다."""
    formatted = _candidate_location_summary(
        str(candidate["chunk_id"]),
        candidate["document"],
        candidate["metadata"] or {},
    )
    formatted.update({
        "rank": candidate["rank"],
        "table_fact_score": candidate["table_fact_score"],
        "parent_chunk_id": (candidate["metadata"] or {}).get("parent_chunk_id"),
    })
    return formatted


def _format_rerank_candidate(
    rank: int,
    doc: str,
    meta: dict,
    chunk_id: str,
    trace_by_id: dict[str, dict],
    question: str,
    analysis: QueryAnalysis,
    selected: bool,
) -> dict:
    """재정렬 단계의 후보별 점수와 최종 선택 여부를 trace 응답 형태로 만든다."""
    meta = meta or {}
    search_text = _build_sparse_search_text(doc, meta)
    subject_score = _score_subject_match(search_text, analysis)
    intent_score = _score_intent_evidence(search_text, analysis)
    heading_score = _score_heading_match(search_text, analysis)
    runtime_table_fact_score = _best_runtime_table_fact_score(meta, question)
    rerank_score = subject_score + intent_score + heading_score + runtime_table_fact_score
    matched_table_facts = meta.get("matched_table_facts", [])
    if isinstance(matched_table_facts, str) and matched_table_facts:
        matched_table_facts = [matched_table_facts]
    elif not isinstance(matched_table_facts, list):
        matched_table_facts = []

    trace_key = _candidate_parent_key(str(chunk_id), meta)
    retrieval = trace_by_id.get(str(chunk_id)) or trace_by_id.get(trace_key) or {"retrieval_methods": []}
    formatted = _candidate_location_summary(chunk_id, doc, meta)
    formatted.update({
        "rank": rank,
        "selected_for_prompt": selected,
        "retrieval": retrieval,
        "scores": {
            "subject_match": subject_score,
            "intent_evidence": intent_score,
            "heading_match": heading_score,
            "runtime_table_fact": runtime_table_fact_score,
            "rerank_total": rerank_score,
        },
        "matched_table_facts": matched_table_facts,
    })
    return formatted


def _query_embeddings_for_trace(
    question_vector: list[float],
    retrieval_limit: int,
    include_vectors: bool,
) -> dict:
    """trace용 Chroma vector search를 실행한다."""
    include_fields = ["documents", "metadatas", "distances"]
    if include_vectors:
        include_fields.append("embeddings")
    return collection.query(
        query_embeddings=[question_vector],
        n_results=retrieval_limit,
        include=include_fields,
    )


def _trace_query_retrieval(
    question: str,
    top_k: int,
    system_prompt: str | None,
    include_vectors: bool,
    vector_preview_size: int,
) -> dict:
    """답변 생성 직전까지의 RAG 검색 파이프라인을 단계별 JSON으로 만든다."""
    trace_start = time.perf_counter()
    analysis = _analyze_query(question)

    embedding_start = time.perf_counter()
    question_vectors, embed_metadata = _embed_texts([question])
    question_vector = question_vectors[0]
    embedding_elapsed = time.perf_counter() - embedding_start
    ollama_total = _seconds_from_nanos(embed_metadata.get("total_duration"))
    ollama_load = _seconds_from_nanos(embed_metadata.get("load_duration"))
    ollama_prompt_eval = _seconds_from_nanos(embed_metadata.get("prompt_eval_duration"))

    chroma_start = time.perf_counter()
    retrieval_limit = min(20, max(top_k, top_k * 3))
    metric = _collection_distance_metric()
    results = _query_embeddings_for_trace(question_vector, retrieval_limit, include_vectors)
    chroma_elapsed = time.perf_counter() - chroma_start

    vector_docs = results["documents"][0] if results.get("documents") else []
    vector_metadatas = results["metadatas"][0] if results.get("metadatas") else []
    vector_ids = results["ids"][0] if results.get("ids") else []
    vector_distances = [float(distance) for distance in results["distances"][0]] if results.get("distances") else []
    vector_embeddings = results.get("embeddings", [[]])
    vector_embeddings = vector_embeddings[0] if include_vectors and vector_embeddings else []

    trace_by_id: dict[str, dict] = {}
    vector_candidates = []
    for index, (doc, meta, chunk_id) in enumerate(zip(vector_docs, vector_metadatas, vector_ids)):
        meta = meta or {}
        distance = vector_distances[index] if index < len(vector_distances) else None
        embedding = vector_embeddings[index] if include_vectors and index < len(vector_embeddings) else None
        _record_vector_trace(trace_by_id, str(chunk_id), doc, meta, index + 1, distance, metric)
        vector_candidates.append(
            _format_vector_candidate(
                index + 1,
                str(chunk_id),
                doc,
                meta,
                distance,
                metric,
                embedding,
                vector_preview_size,
            )
        )

    bm25_candidates = _lookup_bm25_raw_chunk_candidates(analysis, limit=top_k)
    for candidate in bm25_candidates:
        _record_bm25_trace(trace_by_id, candidate)

    table_fact_candidates = _lookup_lexical_table_fact_candidates(question)
    for candidate in table_fact_candidates:
        _record_table_fact_trace(trace_by_id, candidate)

    docs = vector_docs
    metadatas = vector_metadatas
    ids = vector_ids
    if bm25_candidates:
        docs = [candidate["document"] for candidate in bm25_candidates] + docs
        metadatas = [candidate["metadata"] for candidate in bm25_candidates] + metadatas
        ids = [candidate["chunk_id"] for candidate in bm25_candidates] + ids
    if table_fact_candidates:
        docs = [candidate["document"] for candidate in table_fact_candidates] + docs
        metadatas = [candidate["metadata"] for candidate in table_fact_candidates] + metadatas
        ids = [candidate["chunk_id"] for candidate in table_fact_candidates] + ids

    docs, metadatas, ids = _expand_table_fact_results(docs, metadatas, ids)
    metadatas = _attach_runtime_table_facts(question, docs, metadatas)
    expanded_candidates = [
        _format_rerank_candidate(index + 1, doc, meta, chunk_id, trace_by_id, question, analysis, False)
        for index, (doc, meta, chunk_id) in enumerate(zip(docs, metadatas, ids))
    ]

    prioritized_docs, prioritized_metadatas, prioritized_ids = _prioritize_query_results(
        docs,
        metadatas,
        ids,
        question,
    )
    after_table_priority_candidates = [
        _format_rerank_candidate(index + 1, doc, meta, chunk_id, trace_by_id, question, analysis, False)
        for index, (doc, meta, chunk_id) in enumerate(zip(prioritized_docs, prioritized_metadatas, prioritized_ids))
    ]

    reranked_docs, reranked_metadatas, reranked_ids = _rerank_by_query_analysis(
        prioritized_docs,
        prioritized_metadatas,
        prioritized_ids,
        question,
        analysis,
    )
    final_docs = reranked_docs[:top_k]
    final_metadatas = reranked_metadatas[:top_k]
    final_ids = reranked_ids[:top_k]
    context = _build_context(final_docs, final_metadatas, final_ids, analysis) if final_docs else ""
    prompt = _build_rag_prompt(system_prompt, context, question) if final_docs else ""
    final_candidates = [
        _format_rerank_candidate(
            index + 1,
            doc,
            meta,
            chunk_id,
            trace_by_id,
            question,
            analysis,
            index < top_k,
        )
        for index, (doc, meta, chunk_id) in enumerate(zip(reranked_docs, reranked_metadatas, reranked_ids))
    ]

    logger.info(
        "[rag_trace] top_k=%s retrieval_limit=%s vector=%s bm25=%s table_fact=%s final=%s context_chars=%s embed=%.2fs chroma=%.2fs total=%.2fs",
        top_k,
        retrieval_limit,
        len(vector_candidates),
        len(bm25_candidates),
        len(table_fact_candidates),
        len(final_docs),
        len(context),
        embedding_elapsed,
        chroma_elapsed,
        time.perf_counter() - trace_start,
    )
    return {
        "question": question,
        "top_k": top_k,
        "retrieval_limit": retrieval_limit,
        "answer_generated": False,
        "distance_metric": metric,
        "distance_note": "similarity_if_cosine은 collection metric이 cosine으로 명시된 경우에만 계산한다.",
        "query_analysis": {
            "tokens": analysis.tokens,
            "intent": analysis.intent,
            "subject_terms": sorted(analysis.subject_terms),
            "primary_terms": sorted(analysis.primary_terms),
            "context_terms": sorted(analysis.context_terms),
        },
        "query_vector": {
            "dimension": len(question_vector),
            "norm": _round_float(_vector_norm(question_vector)),
            "preview_size": vector_preview_size,
            "preview": _vector_preview(question_vector, vector_preview_size),
        },
        "stages": {
            "vector_candidates": vector_candidates,
            "bm25_candidates": [_format_bm25_candidate(candidate) for candidate in bm25_candidates],
            "table_fact_candidates": [_format_table_fact_candidate(candidate) for candidate in table_fact_candidates],
            "expanded_candidates": expanded_candidates,
            "after_table_priority_candidates": after_table_priority_candidates,
            "final_candidates": final_candidates,
        },
        "final_context": context,
        "final_prompt_preview": _preview_text(prompt, 3000),
        "timing": {
            "embedding_elapsed": _round_float(embedding_elapsed, 4),
            "chroma_elapsed": _round_float(chroma_elapsed, 4),
            "total_elapsed": _round_float(time.perf_counter() - trace_start, 4),
            "ollama_total": _round_float(ollama_total, 4),
            "ollama_load": _round_float(ollama_load, 4),
            "ollama_prompt_eval": _round_float(ollama_prompt_eval, 4),
        },
    }


def _prepare_query(question: str, top_k: int, system_prompt: str | None = None) -> tuple[str | None, list, dict]:
    """
    질문 임베딩 → ChromaDB 검색 → 프롬프트 + 출처 조합.
    문서가 없으면 prompt를 None으로 반환한다. 호출자가 빈 응답 처리를 담당한다.
    """
    prepare_start = time.perf_counter()
    analysis = _analyze_query(question)
    embedding_start = time.perf_counter()
    question_vectors, embed_metadata = _embed_texts([question])
    question_vector = question_vectors[0]
    embedding_elapsed = time.perf_counter() - embedding_start
    ollama_total = _seconds_from_nanos(embed_metadata.get("total_duration"))
    ollama_load = _seconds_from_nanos(embed_metadata.get("load_duration"))
    ollama_prompt_eval = _seconds_from_nanos(embed_metadata.get("prompt_eval_duration"))

    chroma_start = time.perf_counter()
    retrieval_limit = min(20, max(top_k, top_k * 3))
    results = collection.query(
        query_embeddings=[question_vector],
        n_results=retrieval_limit,
        include=["documents", "metadatas", "distances"]
    )
    chroma_elapsed = time.perf_counter() - chroma_start

    docs = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    ids = results["ids"][0] if results["ids"] else []
    distance_values = [float(distance) for distance in results["distances"][0]] if results.get("distances") else []
    raw_result_count = len(docs)
    bm25_docs, bm25_metadatas, bm25_ids = _lookup_bm25_raw_chunks(analysis, limit=top_k)
    lexical_docs, lexical_metadatas, lexical_ids = _lookup_lexical_table_facts(question)
    if bm25_docs:
        docs = bm25_docs + docs
        metadatas = bm25_metadatas + metadatas
        ids = bm25_ids + ids
    if lexical_docs:
        docs = lexical_docs + docs
        metadatas = lexical_metadatas + metadatas
        ids = lexical_ids + ids
    docs, metadatas, ids = _expand_table_fact_results(docs, metadatas, ids)
    metadatas = _attach_runtime_table_facts(question, docs, metadatas)
    docs, metadatas, ids = _prioritize_query_results(docs, metadatas, ids, question)
    docs, metadatas, ids = _rerank_by_query_analysis(docs, metadatas, ids, question, analysis)
    docs = docs[:top_k]
    metadatas = metadatas[:top_k]
    ids = ids[:top_k]

    if not docs:
        prepare_elapsed = time.perf_counter() - prepare_start
        metrics = {
            "prepare_elapsed": prepare_elapsed,
            "embedding_elapsed": embedding_elapsed,
            "chroma_elapsed": chroma_elapsed,
            "context_build_elapsed": 0.0,
            "context_chars": 0,
            "prompt_chars": 0,
            "source_chars": [],
            "distances": distance_values,
            "bm25_raw_chunks": len(bm25_docs),
            "lexical_table_facts": len(lexical_docs),
            "query_intent": analysis.intent,
            "query_subject_terms": sorted(analysis.subject_terms),
        }
        logger.info(
            "[query_prepare] top_k=%s retrieval_limit=%s docs=0 embed=%.2fs ollama_total=%s ollama_load=%s prompt_eval=%s chroma=%.2fs context_build=%.2fs total=%.2fs",
            top_k,
            retrieval_limit,
            embedding_elapsed,
            _format_seconds(ollama_total),
            _format_seconds(ollama_load),
            _format_seconds(ollama_prompt_eval),
            chroma_elapsed,
            metrics["context_build_elapsed"],
            prepare_elapsed
        )
        return None, [], metrics

    context_build_start = time.perf_counter()
    context = _build_context(docs, metadatas, ids, analysis)
    # 프롬프트 조합: 관리자 설정을 반영하되 문서 외 내용 답변 방지 제약은 서버에서 항상 덧붙인다.
    prompt = _build_rag_prompt(system_prompt, context, question)

    # 출처 목록 구성: document_id, source(파일명), 페이지, 청크 미리보기, 헤더 메타데이터 포함
    sources = []
    source_chars = [len(doc) for doc in docs]
    for doc, meta, chunk_id in zip(docs, metadatas, ids):
        meta = meta or {}
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

    context_build_elapsed = time.perf_counter() - context_build_start
    prepare_elapsed = time.perf_counter() - prepare_start
    distance_min = min(distance_values) if distance_values else None
    distance_max = max(distance_values) if distance_values else None
    distance_avg = sum(distance_values) / len(distance_values) if distance_values else None
    metrics = {
        "prepare_elapsed": prepare_elapsed,
        "embedding_elapsed": embedding_elapsed,
        "chroma_elapsed": chroma_elapsed,
        "context_build_elapsed": context_build_elapsed,
        "context_chars": len(context),
        "prompt_chars": len(prompt),
        "source_chars": source_chars,
        "distances": distance_values,
        "distance_min": distance_min,
        "distance_max": distance_max,
        "distance_avg": distance_avg,
        "bm25_raw_chunks": len(bm25_docs),
        "lexical_table_facts": len(lexical_docs),
        "query_intent": analysis.intent,
        "query_subject_terms": sorted(analysis.subject_terms),
    }
    logger.info(
        "[query_context] top_k=%s retrieval_limit=%s raw_docs=%s bm25_raw_chunks=%s lexical_table_facts=%s docs=%s intent=%s subject_terms=%s context_chars=%s source_chars=%s distances=%s distance_min=%s distance_max=%s distance_avg=%s",
        top_k,
        retrieval_limit,
        raw_result_count,
        len(bm25_docs),
        len(lexical_docs),
        len(docs),
        analysis.intent or "none",
        ",".join(sorted(analysis.subject_terms)) or "none",
        metrics["context_chars"],
        _format_int_list(source_chars),
        _format_distance_list(distance_values),
        _format_decimal(distance_min),
        _format_decimal(distance_max),
        _format_decimal(distance_avg),
    )
    logger.info(
        "[query_prepare] top_k=%s retrieval_limit=%s raw_docs=%s bm25_raw_chunks=%s lexical_table_facts=%s docs=%s intent=%s subject_terms=%s context_chars=%s prompt_chars=%s embed=%.2fs ollama_total=%s ollama_load=%s prompt_eval=%s chroma=%.2fs context_build=%.2fs total=%.2fs",
        top_k,
        retrieval_limit,
        raw_result_count,
        len(bm25_docs),
        len(lexical_docs),
        len(docs),
        analysis.intent or "none",
        ",".join(sorted(analysis.subject_terms)) or "none",
        metrics["context_chars"],
        metrics["prompt_chars"],
        embedding_elapsed,
        _format_seconds(ollama_total),
        _format_seconds(ollama_load),
        _format_seconds(ollama_prompt_eval),
        chroma_elapsed,
        context_build_elapsed,
        prepare_elapsed
    )
    return prompt, sources, metrics


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

        chunks_by_index: dict[int, dict] = {}
        for fallback_index, (chunk_id, content, metadata) in enumerate(zip(ids, documents, metadatas)):
            metadata = metadata or {}
            if metadata.get("chunk_role") == "table_fact":
                parent_content = str(metadata.get("parent_content", "")).strip()
                if not parent_content:
                    continue
                parent_index = metadata.get("parent_chunk_index", fallback_index)
                chunk_index = int(parent_index) if str(parent_index).isdigit() else fallback_index
                if chunk_index in chunks_by_index:
                    continue
                chunks_by_index[chunk_index] = {
                    "id": metadata.get("parent_chunk_id", chunk_id),
                    "chunk_index": chunk_index,
                    "content": parent_content,
                    "metadata": _build_parent_metadata_from_fact(metadata)
                }
                continue
            suffix = str(chunk_id).rsplit("_", 1)[-1]
            chunk_index = int(suffix) if suffix.isdigit() else fallback_index
            chunks_by_index[chunk_index] = {
                "id": chunk_id,
                "chunk_index": chunk_index,
                "content": content,
                "metadata": metadata
            }

        return [chunks_by_index[index] for index in sorted(chunks_by_index)]

    chunks = await asyncio.to_thread(_get_from_chroma)
    return {"document_id": document_id, "chunks": chunks}


@app.post("/debug/rag-trace")
async def debug_rag_trace(request: RagTraceRequest):
    """
    답변 생성 없이 RAG 검색 파이프라인을 단계별로 추적한다.
    vector, BM25, table_fact, rerank 후보를 JSON으로 반환해 검색 품질 디버깅에 사용한다.
    """
    return await asyncio.to_thread(
        _trace_query_retrieval,
        request.question,
        request.top_k,
        request.system_prompt,
        request.include_vectors,
        request.vector_preview_size,
    )


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
    prompt, sources, query_metrics = await asyncio.to_thread(
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
        "[query] top_k=%s sources=%s context_chars=%s prompt_chars=%s prepare=%.2fs llm=%.2fs total=%.2fs",
        request.top_k,
        len(sources),
        query_metrics["context_chars"],
        query_metrics["prompt_chars"],
        query_metrics["prepare_elapsed"],
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
    prompt, sources, query_metrics = await asyncio.to_thread(
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
        llm_first_token_elapsed = None
        chunk_count = 0
        llm_start = time.perf_counter()
        try:
            async for chunk in llm.astream(prompt):
                if chunk:
                    if first_token_elapsed is None:
                        first_token_elapsed = time.perf_counter() - stream_start
                        llm_first_token_elapsed = time.perf_counter() - llm_start
                        logger.info(
                            "[query_stream] first_token top_k=%s sources=%s context_chars=%s prompt_chars=%s prepare=%.2fs llm_first_token=%.2fs first_token=%.2fs",
                            request.top_k,
                            len(sources),
                            query_metrics["context_chars"],
                            query_metrics["prompt_chars"],
                            query_metrics["prepare_elapsed"],
                            llm_first_token_elapsed,
                            first_token_elapsed
                        )
                    chunk_count += 1
                    yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"
            logger.info(
                "[query_stream] done top_k=%s sources=%s chunks=%s context_chars=%s prompt_chars=%s prepare=%.2fs llm_first_token=%s first_token=%s total=%.2fs",
                request.top_k,
                len(sources),
                chunk_count,
                query_metrics["context_chars"],
                query_metrics["prompt_chars"],
                query_metrics["prepare_elapsed"],
                f"{llm_first_token_elapsed:.2f}s" if llm_first_token_elapsed is not None else "none",
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
