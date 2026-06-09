from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
AI_BASE_URL = os.getenv("RAG_LAB_AI_BASE_URL", "http://localhost:8000").rstrip("/")
HOST = os.getenv("RAG_LAB_HOST", "127.0.0.1")
PORT = int(os.getenv("RAG_LAB_PORT", "7860"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("RAG_LAB_REQUEST_TIMEOUT", "180"))


class RagLabError(RuntimeError):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_GATEWAY):
        super().__init__(message)
        self.status = status


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = urllib.parse.urljoin(f"{AI_BASE_URL}/", path.lstrip("/"))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RagLabError(f"AI 서버가 {error.code} 응답을 반환했다: {detail}", error.code) from error
    except urllib.error.URLError as error:
        raise RagLabError(f"AI 서버에 연결할 수 없다: {error.reason}") from error
    except TimeoutError as error:
        raise RagLabError("AI 서버 응답 시간이 초과됐다.") from error
    except json.JSONDecodeError as error:
        raise RagLabError("AI 서버 응답을 JSON으로 해석할 수 없다.") from error


def inline_markdown(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)


def is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def split_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_table(lines: list[str], start: int) -> tuple[str, int]:
    header = split_table_cells(lines[start])
    body_start = start + 2
    rows: list[list[str]] = []
    index = body_start

    while index < len(lines) and is_table_row(lines[index]) and not is_table_separator(lines[index]):
        rows.append(split_table_cells(lines[index]))
        index += 1

    header_html = "".join(f"<th>{inline_markdown(cell)}</th>" for cell in header)
    row_html = []
    for row in rows:
        padded = row + [""] * max(0, len(header) - len(row))
        cells = "".join(f"<td>{inline_markdown(cell)}</td>" for cell in padded[: len(header)])
        row_html.append(f"<tr>{cells}</tr>")

    table = (
        '<div class="markdown-table-wrap">'
        "<table>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table>"
        "</div>"
    )
    return table, index


def render_list(lines: list[str], start: int, ordered: bool) -> tuple[str, int]:
    tag = "ol" if ordered else "ul"
    items = []
    index = start
    pattern = r"^\s*\d+\.\s+(.+)$" if ordered else r"^\s*[-*]\s+(.+)$"

    while index < len(lines):
        match = re.match(pattern, lines[index])
        if not match:
            break
        items.append(f"<li>{inline_markdown(match.group(1))}</li>")
        index += 1

    return f"<{tag}>{''.join(items)}</{tag}>", index


def render_markdown(markdown: str) -> str:
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{'<br>'.join(inline_markdown(line) for line in paragraph)}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            code_lines = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            code = html.escape("\n".join(code_lines), quote=True)
            blocks.append(f"<pre><code>{code}</code></pre>")
            continue

        if index + 1 < len(lines) and is_table_row(line) and is_table_separator(lines[index + 1]):
            flush_paragraph()
            table_html, index = render_table(lines, index)
            blocks.append(table_html)
            continue

        heading_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            blocks.append(f"<h{level}>{inline_markdown(heading_match.group(2))}</h{level}>")
            index += 1
            continue

        if re.match(r"^\s*[-*]\s+", line):
            flush_paragraph()
            list_html, index = render_list(lines, index, ordered=False)
            blocks.append(list_html)
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            flush_paragraph()
            list_html, index = render_list(lines, index, ordered=True)
            blocks.append(list_html)
            continue

        paragraph.append(line)
        index += 1

    flush_paragraph()
    return "\n".join(blocks)


def clamp_top_k(value: Any) -> int:
    try:
        top_k = int(value)
    except (TypeError, ValueError):
        return 5
    return min(20, max(1, top_k))


def build_query_payload(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question", "")).strip()
    if not question:
        raise RagLabError("질문을 입력해야 한다.", HTTPStatus.BAD_REQUEST)

    query_payload: dict[str, Any] = {
        "question": question,
        "top_k": clamp_top_k(payload.get("top_k", 5)),
    }
    system_prompt = str(payload.get("system_prompt", "")).strip()
    if system_prompt:
        query_payload["system_prompt"] = system_prompt
    return query_payload


def summarize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    stages = trace.get("stages") or {}
    final_candidates = stages.get("final_candidates") or []
    evidence_candidates = stages.get("after_evidence_focus_candidates") or []
    query_analysis = trace.get("query_analysis") or {}
    timing = trace.get("timing") or {}

    return {
        "intent": query_analysis.get("intent"),
        "subject_terms": query_analysis.get("subject_terms") or [],
        "primary_terms": query_analysis.get("primary_terms") or [],
        "total_elapsed": timing.get("total_elapsed"),
        "embedding_elapsed": timing.get("embedding_elapsed"),
        "chroma_elapsed": timing.get("chroma_elapsed"),
        "vector_count": len(stages.get("vector_candidates") or []),
        "bm25_count": len(stages.get("bm25_candidates") or []),
        "table_fact_count": len(stages.get("table_fact_candidates") or []),
        "evidence_focus_count": len(evidence_candidates),
        "final_count": len(final_candidates),
        "final_candidates": final_candidates[:5],
    }


class RagLabHandler(SimpleHTTPRequestHandler):
    server_version = "DocuMindRagLab/0.1"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[rag-lab] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self.path = "/static/index.html"
        if self.path == "/api/health":
            self.write_json({
                "status": "ok",
                "ai_base_url": AI_BASE_URL,
                "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            })
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            if self.path == "/api/query":
                self.handle_query(payload)
                return
            if self.path == "/api/trace":
                self.handle_trace(payload)
                return
            self.write_json({"error": "지원하지 않는 경로이다."}, HTTPStatus.NOT_FOUND)
        except RagLabError as error:
            self.write_json({"error": str(error)}, error.status)
        except Exception as error:
            self.write_json({"error": f"실험 웹 처리 중 오류가 발생했다: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_query(self, payload: dict[str, Any]) -> None:
        query_payload = build_query_payload(payload)
        started_at = time.perf_counter()
        response = post_json("/query", query_payload)
        answer = str(response.get("answer", ""))
        self.write_json({
            "answer": answer,
            "answer_html": render_markdown(answer),
            "sources": response.get("sources") or [],
            "elapsed": round(time.perf_counter() - started_at, 3),
            "ai_base_url": AI_BASE_URL,
        })

    def handle_trace(self, payload: dict[str, Any]) -> None:
        query_payload = build_query_payload(payload)
        query_payload["include_vectors"] = bool(payload.get("include_vectors", False))
        query_payload["vector_preview_size"] = clamp_top_k(payload.get("vector_preview_size", 8))
        started_at = time.perf_counter()
        trace = post_json("/debug/rag-trace", query_payload)
        self.write_json({
            "trace": trace,
            "summary": summarize_trace(trace),
            "elapsed": round(time.perf_counter() - started_at, 3),
            "ai_base_url": AI_BASE_URL,
        })

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RagLabError("요청 JSON 형식이 올바르지 않다.", HTTPStatus.BAD_REQUEST) from error
        if not isinstance(payload, dict):
            raise RagLabError("요청 본문은 JSON 객체여야 한다.", HTTPStatus.BAD_REQUEST)
        return payload

    def write_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), RagLabHandler)
    print(f"DocuMind RAG Lab: http://{HOST}:{PORT}")
    print(f"AI server: {AI_BASE_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRAG Lab stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
