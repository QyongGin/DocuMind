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
from threading import Lock

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
_document_progress: dict[int, dict] = {}

logger.info(
    "[startup] ollama_base_url=%s llm_model=%s embedding_model=%s keep_alive=%s embedding_warmup=%s num_ctx=%s num_predict=%s num_thread=%s chunk_size=%s chunk_overlap=%s chunk_merge_min_size=%s embedding_batch_size=%s default_top_k=%s chroma_host=%s chroma_port=%s",
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
            sub_docs = _char_splitter.split_documents([doc])
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
    return Document(page_content=page_content, metadata=common_metadata)


def _header_signature(doc: Document) -> tuple[str, ...]:
    """청크의 전체 Markdown header 경로를 짧은 청크 병합 경계 판단용 tuple로 반환한다."""
    return tuple(str(doc.metadata.get(f"Header {level}", "")) for level in range(1, 7))


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

    for doc in docs:
        if not doc.page_content.strip():
            continue

        doc_length = len(doc.page_content)
        next_length = buffer_length + (2 if buffer else 0) + doc_length
        header_changed = bool(buffer) and _header_signature(buffer[0]) != _header_signature(doc)

        if buffer and (header_changed or buffer_length >= CHUNK_MERGE_MIN_SIZE or next_length > CHUNK_SIZE):
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
    RecursiveCharacterTextSplitter의 내장 overlap은 서로 다른 헤더 구간 간에
    작동하지 않으므로 전체 청크 리스트에 수동으로 적용한다. 문자 중간을 자르지 않는다.
    """
    if CHUNK_OVERLAP <= 0:
        return docs

    overlapped: list[Document] = []
    for i, doc in enumerate(docs):
        if i == 0:
            overlapped.append(doc)
        else:
            context_parts = []
            overlap_text = ""
            if _should_apply_general_overlap(doc.page_content):
                overlap_text = _select_overlap_text(docs[i - 1].page_content, CHUNK_OVERLAP)
            table_header_overlap = _select_table_header_overlap(docs[i - 1].page_content, doc.page_content)
            if table_header_overlap and not _starts_with_same_table_header_block(overlap_text, table_header_overlap):
                context_parts.append(table_header_overlap)

            if overlap_text:
                context_parts.append(overlap_text)

            if not context_parts:
                overlapped.append(doc)
                continue
            context_text = "\n\n".join(context_parts)
            overlapped.append(Document(
                page_content=_dedupe_adjacent_lines(context_text + "\n\n" + doc.page_content),
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


def _store_document_chunks(final_docs: list[Document], filename: str, document_id: int, page_lookup: list[dict]) -> tuple[float, float, float]:
    """
    문서 청크를 batch embedding 후 ChromaDB에 batch 저장한다.
    청크별 HTTP 호출을 피하기 위해 EMBEDDING_BATCH_SIZE 단위로 묶어 처리한다.
    """
    page_match_elapsed = 0.0
    embedding_elapsed = 0.0
    chroma_elapsed = 0.0
    total_chunks = len(final_docs)
    if total_chunks == 0:
        return page_match_elapsed, embedding_elapsed, chroma_elapsed

    for start in range(0, len(final_docs), EMBEDDING_BATCH_SIZE):
        batch_number = start // EMBEDDING_BATCH_SIZE + 1
        total_batches = math.ceil(len(final_docs) / EMBEDDING_BATCH_SIZE)
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
        _set_document_progress(
            document_id,
            30 + round((start / total_chunks) * 60),
            "embedding",
            f"임베딩 중입니다. ({start}/{total_chunks} chunks)"
        )
        logger.info(
            "[upload_embed] document_id=%s batch=%s/%s chunks=%s model=%s num_thread=%s",
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
        completed_chunks = min(start + len(batch_docs), total_chunks)
        _set_document_progress(
            document_id,
            30 + round((completed_chunks / total_chunks) * 60),
            "embedding",
            f"임베딩과 벡터 저장을 진행 중입니다. ({completed_chunks}/{total_chunks} chunks)"
        )

    return page_match_elapsed, embedding_elapsed, chroma_elapsed


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

        # 전체 텍스트 병합 후 정규화
        normalize_start = time.perf_counter()
        full_text = "\n".join([doc.page_content for doc in raw_docs])
        full_text = _normalize_text(full_text)
        normalize_elapsed = time.perf_counter() - normalize_start
        _set_document_progress(document_id, 25, "normalize", "문서 텍스트를 정리했습니다.")

        # Two-Pass 청킹 + 연속 중복 line 정리 + 수동 overlap 후처리
        split_start = time.perf_counter()
        split_docs = _two_pass_split(full_text)
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
        page_match_elapsed, embedding_elapsed, chroma_elapsed = _store_document_chunks(
            final_docs,
            filename,
            document_id,
            page_lookup
        )
        _set_document_progress(document_id, 95, "chroma", "벡터 저장을 마무리하고 있습니다.")
        total_elapsed = time.perf_counter() - total_start
        logger.info(
            "[upload] document_id=%s filename=%s raw_docs=%s split_chunks=%s deduped_chunks=%s merged_chunks=%s chunks=%s chunk_size=%s chunk_overlap=%s chunk_merge_min_size=%s batch_size=%s parse=%.2fs page_lookup=%.2fs normalize=%.2fs split=%.2fs dedupe=%.2fs merge=%.2fs overlap=%.2fs page_match=%.2fs embed=%.2fs chroma_add=%.2fs total=%.2fs",
            document_id,
            filename,
            len(raw_docs),
            len(split_docs),
            len(deduped_docs),
            len(merged_docs),
            len(final_docs),
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            CHUNK_MERGE_MIN_SIZE,
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


DEFAULT_SYSTEM_PROMPT = (
    "너는 인하공업전문대학 문서를 근거로 답변하는 안내 챗봇이다."
)

MANDATORY_RAG_PROMPT = (
    "필수 답변 규칙:\n"
    "1. 반드시 [검색 근거]에 있는 내용만 사용한다.\n"
    "2. [검색 근거]에 없는 절차, 조건, 날짜, 숫자, 서류, 주의사항, 조언은 만들지 않는다.\n"
    "3. 질문이 방법, 절차, 주의사항을 묻는 경우 [검색 근거]의 절차, 유의사항, 안내 문구를 우선 추출한다.\n"
    "4. 숫자, 날짜, 모집 인원, 점수, 기간은 추측하지 말고 근거의 값을 그대로 쓴다.\n"
    "5. '약', '일반적으로', '대부분의 경우'처럼 근거를 흐리는 표현을 쓰지 않는다.\n"
    "6. 근거가 부족하면 부족한 항목을 지어내지 말고 '제공된 문서에서는 확인할 수 없습니다.'라고 답한다.\n"
    "7. 문서에 없는 일반 조언이나 외부 지식을 덧붙이지 않는다."
)


QUERY_TERM_SYNONYMS = {
    "방법": {"방법", "절차", "신청", "신청절차", "제출"},
    "주의사항": {"주의사항", "유의사항", "유의", "주의"},
    "전과": {"전과", "전과제도", "전과시행"},
}


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
    for suffix in ("으로", "에서", "에게", "한테", "부터", "까지", "은", "는", "이", "가", "을", "를", "의", "도", "만", "와", "과"):
        if len(normalized) > len(suffix) + 1 and normalized.endswith(suffix):
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


def _select_relevant_excerpt(text: str, query_terms: set[str], window: int = 2, max_lines: int = 18) -> str:
    """청크 안에서 질문 핵심어와 가까운 실제 line들을 골라 LLM 주의 집중용 발췌를 만든다."""
    if not query_terms:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
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


def _format_context_block(index: int, doc: str, meta: dict, chunk_id: str, query_terms: set[str]) -> str:
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
    relevant_excerpt = _select_relevant_excerpt(doc, query_terms)
    if relevant_excerpt:
        return f"[출처 {index}]\n{metadata}\n질문 관련 발췌:\n{relevant_excerpt}\n전체 내용:\n{doc.strip()}"
    return f"[출처 {index}]\n{metadata}\n전체 내용:\n{doc.strip()}"


def _build_context(docs: list[str], metadatas: list[dict], ids: list[str], question: str) -> str:
    """검색된 청크들을 출처 단위 context로 변환한다."""
    query_terms = _extract_query_terms(question)
    blocks = []
    for index, (doc, meta, chunk_id) in enumerate(zip(docs, metadatas, ids), start=1):
        blocks.append(_format_context_block(index, doc, meta or {}, chunk_id, query_terms))
    return "\n\n".join(blocks)


def _prepare_query(question: str, top_k: int, system_prompt: str | None = None) -> tuple[str | None, list, dict]:
    """
    질문 임베딩 → ChromaDB 검색 → 프롬프트 + 출처 조합.
    문서가 없으면 prompt를 None으로 반환한다. 호출자가 빈 응답 처리를 담당한다.
    """
    prepare_start = time.perf_counter()
    embedding_start = time.perf_counter()
    question_vectors, embed_metadata = _embed_texts([question])
    question_vector = question_vectors[0]
    embedding_elapsed = time.perf_counter() - embedding_start
    ollama_total = _seconds_from_nanos(embed_metadata.get("total_duration"))
    ollama_load = _seconds_from_nanos(embed_metadata.get("load_duration"))
    ollama_prompt_eval = _seconds_from_nanos(embed_metadata.get("prompt_eval_duration"))

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
    distance_values = [float(distance) for distance in results["distances"][0]] if results.get("distances") else []

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
        }
        logger.info(
            "[query_prepare] top_k=%s docs=0 embed=%.2fs ollama_total=%s ollama_load=%s prompt_eval=%s chroma=%.2fs context_build=%.2fs total=%.2fs",
            top_k,
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
    context = _build_context(docs, metadatas, ids, question)
    prompt_policy = system_prompt.strip() if system_prompt and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT

    # 프롬프트 조합: 관리자 설정을 반영하되 문서 외 내용 답변 방지 제약은 서버에서 항상 덧붙인다.
    prompt = f"""{prompt_policy}

{MANDATORY_RAG_PROMPT}

[검색 근거]
{context}

[사용자 질문]
{question}

[답변 직전 확인]
- 답변은 [검색 근거]에 직접 적힌 내용만 사용한다.
- [검색 근거]의 '질문 관련 발췌'가 있으면 그 내용을 우선 사용한다.
- 근거에 없는 일반적인 대학 행정 절차나 조언은 쓰지 않는다.

[답변 작성]
"""

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
    }
    logger.info(
        "[query_context] top_k=%s docs=%s context_chars=%s source_chars=%s distances=%s distance_min=%s distance_max=%s distance_avg=%s",
        top_k,
        len(docs),
        metrics["context_chars"],
        _format_int_list(source_chars),
        _format_distance_list(distance_values),
        _format_decimal(distance_min),
        _format_decimal(distance_max),
        _format_decimal(distance_avg),
    )
    logger.info(
        "[query_prepare] top_k=%s docs=%s context_chars=%s prompt_chars=%s embed=%.2fs ollama_total=%s ollama_load=%s prompt_eval=%s chroma=%.2fs context_build=%.2fs total=%.2fs",
        top_k,
        len(docs),
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
