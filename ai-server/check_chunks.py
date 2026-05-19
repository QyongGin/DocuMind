from __future__ import annotations

import argparse
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_COLLECTION_NAME = "documents"
DEFAULT_LOCAL_CHROMA_PATH = "./chroma_db"
DEFAULT_HTTP_CHROMA_PORT = 8001
DEFAULT_LAYOUT_STORE_DIR = "./layout_store"

SHORT_LENGTH_LIMITS = (50, 100, 200)
REPEATED_LINE_MIN_COUNT = 3
REPEATED_LINE_MIN_LENGTH = 8
SAMPLE_LIMIT = 12


@dataclass(frozen=True)
class ChunkRecord:
    index: int
    document: str
    metadata: dict[str, Any]

    @property
    def length(self) -> int:
        return len(self.document)

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", ""))

    @property
    def chunk_role(self) -> str:
        return str(self.metadata.get("chunk_role", "raw"))

    @property
    def block_type(self) -> str:
        return str(self.metadata.get("block_type", "text"))

    @property
    def page(self) -> str:
        return str(self.metadata.get("page", ""))


@dataclass(frozen=True)
class ChunkIssue:
    chunk_index: int
    issue_type: str
    length: int
    page: str
    preview: str


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _preview(text: str, limit: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped or "-" not in stripped:
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _table_cells(line: str) -> list[str]:
    if not _is_table_row(line):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_empty_table_row(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(not cell or re.fullmatch(r"-+", cell) for cell in cells)


def _is_table_row_with_empty_cells(line: str) -> bool:
    if not _is_table_row(line) or _is_table_separator(line):
        return False
    cells = _table_cells(line)
    return bool(cells) and any(not cell for cell in cells) and any(cell for cell in cells)


def _is_empty_table_block(lines: list[str]) -> bool:
    if not lines or not any(_is_table_separator(line) for line in lines):
        return False

    for line in lines:
        if _is_table_separator(line):
            continue
        cells = _table_cells(line)
        if any(cell for cell in cells):
            return False
    return True


def _has_empty_table_block(text: str) -> bool:
    table_block: list[str] = []
    for line in text.splitlines():
        if _is_table_row(line):
            table_block.append(line)
            continue
        if table_block and _is_empty_table_block(table_block):
            return True
        table_block = []

    return bool(table_block and _is_empty_table_block(table_block))


def _is_visual_or_layout_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _is_table_separator(stripped) or _is_empty_table_row(stripped):
        return True
    if re.fullmatch(r"[|:\-\s]+", stripped):
        return True
    if re.fullmatch(r"#+\s*\d{2,4}", stripped):
        return True
    if re.fullmatch(r"\d{1,4}", stripped):
        return True
    return False


def _has_table(text: str) -> bool:
    return any(_is_table_row(line) for line in text.splitlines())


def _table_row_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if _is_table_row(line) and not _is_table_separator(line))


def _table_note_lines(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        normalized = _normalize_line(line)
        if not normalized:
            continue
        if normalized.startswith("※") or "표시" in normalized or "주석" in normalized or "범례" in normalized:
            result.append(normalized)
    return result


def _metadata_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _layout_sidecar_exists(layout_store_dir: str | None, store_key: str) -> bool:
    if not layout_store_dir or not store_key:
        return False
    return (Path(layout_store_dir) / store_key).exists()


def _looks_like_orphan_short_chunk(record: ChunkRecord) -> bool:
    if record.chunk_role != "raw":
        return False
    if record.length >= 100:
        return False
    if _has_table(record.document):
        return False
    lines = [_normalize_line(line) for line in record.document.splitlines() if line.strip()]
    if not lines:
        return True
    meaningful_lines = [line for line in lines if not _is_visual_or_layout_line(line)]
    return len(meaningful_lines) <= 2


def _looks_like_visual_only_chunk(record: ChunkRecord) -> bool:
    if record.chunk_role != "raw":
        return False
    lines = [_normalize_line(line) for line in record.document.splitlines() if line.strip()]
    if not lines:
        return True
    visual_lines = sum(1 for line in lines if _is_visual_or_layout_line(line))
    return visual_lines / len(lines) >= 0.75


def _metadata_path(metadata: dict[str, Any]) -> str:
    headers = []
    for level in range(1, 7):
        value = str(metadata.get(f"Header {level}", "")).strip()
        if value:
            headers.append(value)
    return " > ".join(headers)


def _get_collection(args: argparse.Namespace):
    import chromadb

    if args.chroma_host:
        client = chromadb.HttpClient(host=args.chroma_host, port=args.chroma_port)
    else:
        client = chromadb.PersistentClient(path=args.chroma_path)
    return client.get_collection(args.collection)


def _coerce_document_id(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def _get_all_records(collection) -> list[ChunkRecord]:
    results = collection.get(include=["documents", "metadatas"])
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    return [
        ChunkRecord(index=index + 1, document=document or "", metadata=metadata or {})
        for index, (document, metadata) in enumerate(zip(documents, metadatas, strict=False))
    ]


def _get_document_records(collection, document_id: str) -> list[ChunkRecord]:
    candidate_ids = [_coerce_document_id(document_id), str(document_id)]
    for candidate in candidate_ids:
        results = collection.get(where={"document_id": candidate}, include=["documents", "metadatas"])
        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []
        if documents:
            return [
                ChunkRecord(index=index + 1, document=document or "", metadata=metadata or {})
                for index, (document, metadata) in enumerate(zip(documents, metadatas, strict=False))
            ]
    return []


def _print_document_list(records: list[ChunkRecord]) -> None:
    by_document: dict[Any, list[ChunkRecord]] = defaultdict(list)
    for record in records:
        by_document[record.metadata.get("document_id")].append(record)

    print(f"저장된 document_id 목록: {sorted(by_document, key=lambda item: str(item))}")
    print(f"전체 청크 수: {len(records)}개\n")
    for document_id, doc_records in sorted(by_document.items(), key=lambda item: str(item[0])):
        source = next((record.source for record in doc_records if record.source), "")
        print(f"  document_id={document_id} | {source} | {len(doc_records)}청크")


def _print_chunks(records: list[ChunkRecord], document_id: str) -> None:
    print(f"document_id={document_id} 총 청크 수: {len(records)}개\n")
    for record in records:
        path = _metadata_path(record.metadata)
        path_suffix = f" | {path}" if path else ""
        print(f"=== 청크 {record.index} === ({record.length}글자, role={record.chunk_role}, page={record.page}{path_suffix})")
        print(record.document)
        print()


def _build_quality_report(
    records: list[ChunkRecord],
    document_id: str | None = None,
    layout_store_dir: str | None = None,
) -> dict[str, Any]:
    lengths = [record.length for record in records]
    raw_records = [record for record in records if record.chunk_role == "raw"]
    table_fact_records = [record for record in records if record.chunk_role == "table_fact"]
    table_records = [record for record in records if record.block_type == "table" or _has_table(record.document)]
    section_scope_counts = Counter(
        str(record.metadata.get("section_scope"))
        for record in records
        if record.metadata.get("section_scope")
    )

    line_counter: Counter[str] = Counter()
    issue_samples: list[ChunkIssue] = []
    note_samples: list[ChunkIssue] = []
    table_with_empty_cells_samples: list[ChunkIssue] = []
    empty_table_block_samples: list[ChunkIssue] = []
    layout_store_missing_samples: list[ChunkIssue] = []
    layout_mode_counts: Counter[str] = Counter()
    layout_bbox_coverages: list[float] = []
    layout_store_key_chunks = 0

    for record in records:
        layout_mode = str(record.metadata.get("layout_mode", "")).strip()
        if layout_mode:
            layout_mode_counts[layout_mode] += 1
        layout_store_key = str(record.metadata.get("layout_store_key", "")).strip()
        if layout_store_key:
            layout_store_key_chunks += 1
            if not _layout_sidecar_exists(layout_store_dir, layout_store_key):
                layout_store_missing_samples.append(
                    ChunkIssue(
                        record.index,
                        "layout_store_missing",
                        record.length,
                        record.page,
                        layout_store_key,
                    )
                )
        layout_bbox_coverage = _metadata_float(record.metadata.get("layout_bbox_coverage"))
        if layout_bbox_coverage is not None:
            layout_bbox_coverages.append(layout_bbox_coverage)

        for line in record.document.splitlines():
            normalized = _normalize_line(line)
            if len(normalized) >= REPEATED_LINE_MIN_LENGTH:
                line_counter[normalized] += 1

        if _looks_like_orphan_short_chunk(record):
            issue_samples.append(
                ChunkIssue(record.index, "orphan_short_chunk", record.length, record.page, _preview(record.document))
            )
        if _looks_like_visual_only_chunk(record):
            issue_samples.append(
                ChunkIssue(record.index, "visual_or_layout_only_chunk", record.length, record.page, _preview(record.document))
            )
        if _has_empty_table_block(record.document):
            empty_table_block_samples.append(
                ChunkIssue(record.index, "empty_table_block", record.length, record.page, _preview(record.document))
            )
        if any(_is_table_row_with_empty_cells(line) for line in record.document.splitlines()):
            table_with_empty_cells_samples.append(
                ChunkIssue(record.index, "table_with_empty_cells", record.length, record.page, _preview(record.document))
            )
        notes = _table_note_lines(record.document)
        if notes:
            note_samples.append(
                ChunkIssue(record.index, "table_note_candidate", record.length, record.page, " / ".join(notes[:3]))
            )

    repeated_lines = [
        {"line": line, "count": count}
        for line, count in line_counter.most_common(30)
        if count >= REPEATED_LINE_MIN_COUNT
    ]
    repeated_line_total = sum(item["count"] - 1 for item in repeated_lines)
    total_counted_lines = sum(line_counter.values())

    short_counts = {
        f"under_{limit}": sum(1 for length in lengths if length < limit)
        for limit in SHORT_LENGTH_LIMITS
    }

    report = {
        "document_id": document_id,
        "summary": {
            "total_chunks": len(records),
            "raw_chunks": len(raw_records),
            "table_fact_chunks": len(table_fact_records),
            "table_like_chunks": len(table_records),
            "total_chars": sum(lengths),
            "min_chars": min(lengths) if lengths else 0,
            "max_chars": max(lengths) if lengths else 0,
            "avg_chars": round(statistics.mean(lengths), 2) if lengths else 0,
            "median_chars": round(statistics.median(lengths), 2) if lengths else 0,
            **short_counts,
            "duplicate_line_ratio": round(repeated_line_total / total_counted_lines, 4) if total_counted_lines else 0,
        },
        "quality_flags": {
            "orphan_short_or_visual_samples": [asdict(issue) for issue in issue_samples[:SAMPLE_LIMIT]],
            "empty_table_block_samples": [asdict(issue) for issue in empty_table_block_samples[:SAMPLE_LIMIT]],
            "table_with_empty_cells_samples": [
                asdict(issue) for issue in table_with_empty_cells_samples[:SAMPLE_LIMIT]
            ],
            "layout_store_missing_samples": [
                asdict(issue) for issue in layout_store_missing_samples[:SAMPLE_LIMIT]
            ],
            "table_note_samples": [asdict(issue) for issue in note_samples[:SAMPLE_LIMIT]],
            "top_repeated_lines": repeated_lines[:SAMPLE_LIMIT],
        },
        "table_stats": {
            "max_table_rows_in_chunk": max((_table_row_count(record.document) for record in records), default=0),
            "avg_table_rows_in_table_chunks": round(
                statistics.mean([_table_row_count(record.document) for record in table_records]),
                2,
            )
            if table_records
            else 0,
        },
        "metadata_stats": {
            "section_scope_chunks": sum(section_scope_counts.values()),
            "top_section_scopes": dict(section_scope_counts.most_common(10)),
            "layout_mode_counts": dict(layout_mode_counts.most_common()),
            "layout_store_key_chunks": layout_store_key_chunks,
            "avg_layout_bbox_coverage": round(statistics.mean(layout_bbox_coverages), 4)
            if layout_bbox_coverages
            else 0,
        },
    }
    return report


def _print_quality_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    flags = report["quality_flags"]
    table_stats = report["table_stats"]
    metadata_stats = report.get("metadata_stats", {})

    print("# RAG 청크 품질 진단")
    if report.get("document_id") is not None:
        print(f"\n- document_id: {report['document_id']}")

    print("\n## 요약")
    for key, value in summary.items():
        print(f"- {key}: {value}")

    print("\n## 표 통계")
    for key, value in table_stats.items():
        print(f"- {key}: {value}")

    print("\n## metadata 통계")
    section_scope_chunks = metadata_stats.get("section_scope_chunks", 0)
    top_section_scopes = metadata_stats.get("top_section_scopes") or {}
    print(f"- section_scope_chunks: {section_scope_chunks}")
    if top_section_scopes:
        for key, value in top_section_scopes.items():
            print(f"- section_scope={key}: {value}")
    else:
        print("- section_scope: 없음")
    layout_mode_counts = metadata_stats.get("layout_mode_counts") or {}
    if layout_mode_counts:
        for key, value in layout_mode_counts.items():
            print(f"- layout_mode={key}: {value}")
    else:
        print("- layout_mode: 없음")
    print(f"- layout_store_key_chunks: {metadata_stats.get('layout_store_key_chunks', 0)}")
    print(f"- avg_layout_bbox_coverage: {metadata_stats.get('avg_layout_bbox_coverage', 0)}")

    print("\n## 주의할 샘플")
    for group_name, samples in flags.items():
        print(f"\n### {group_name}")
        if not samples:
            print("- 없음")
            continue
        for sample in samples:
            if group_name == "top_repeated_lines":
                print(f"- {sample['count']}회: {sample['line']}")
            else:
                print(
                    f"- chunk {sample['chunk_index']} | {sample['issue_type']} | "
                    f"{sample['length']}자 | page={sample['page']} | {sample['preview']}"
                )


def _write_json(report: dict[str, Any], output_path: str | None) -> None:
    if not output_path:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON 저장: {path}")


def _write_markdown(report: dict[str, Any], output_path: str | None) -> None:
    if not output_path:
        return

    summary = report["summary"]
    flags = report["quality_flags"]
    table_stats = report["table_stats"]
    metadata_stats = report.get("metadata_stats", {})

    lines = [
        "# RAG 청크 품질 진단 보고서",
        "",
        "```mermaid",
        "flowchart TD",
        '    A["ChromaDB 청크 조회"] --> B["길이/역할 통계"]',
        '    A --> C["반복 line 검사"]',
        '    A --> D["표/주석 검사"]',
        '    B --> E["청크 품질 판단"]',
        '    C --> E',
        '    D --> E',
        '    E --> F["parser 비교와 structured facts 설계 입력"]',
        "```",
        "",
        "## 요약",
        "",
        "|항목|값|",
        "|---|---:|",
    ]
    lines.extend(f"|{key}|{value}|" for key, value in summary.items())
    lines.extend(
        [
            "",
            "## 표 통계",
            "",
            "|항목|값|",
            "|---|---:|",
        ]
    )
    lines.extend(f"|{key}|{value}|" for key, value in table_stats.items())
    lines.extend(
        [
            "",
            "## metadata 통계",
            "",
            "|항목|값|",
            "|---|---:|",
        ]
    )
    section_scope_chunks = metadata_stats.get("section_scope_chunks", 0)
    top_section_scopes = metadata_stats.get("top_section_scopes") or {}
    lines.append(f"|section_scope_chunks|{section_scope_chunks}|")
    if top_section_scopes:
        lines.extend(f"|section_scope={key}|{value}|" for key, value in top_section_scopes.items())
    else:
        lines.append("|section_scope|없음|")
    layout_mode_counts = metadata_stats.get("layout_mode_counts") or {}
    if layout_mode_counts:
        lines.extend(f"|layout_mode={key}|{value}|" for key, value in layout_mode_counts.items())
    else:
        lines.append("|layout_mode|없음|")
    lines.append(f"|layout_store_key_chunks|{metadata_stats.get('layout_store_key_chunks', 0)}|")
    lines.append(f"|avg_layout_bbox_coverage|{metadata_stats.get('avg_layout_bbox_coverage', 0)}|")
    lines.append("")
    lines.append("## 주의할 샘플")
    for group_name, samples in flags.items():
        lines.append("")
        lines.append(f"### {group_name}")
        if not samples:
            lines.append("")
            lines.append("- 없음")
            continue
        lines.append("")
        for sample in samples:
            if group_name == "top_repeated_lines":
                lines.append(f"- `{sample['count']}`회: {sample['line']}")
            else:
                lines.append(
                    f"- chunk `{sample['chunk_index']}` / `{sample['issue_type']}` / "
                    f"{sample['length']}자 / page `{sample['page']}`: {sample['preview']}"
                )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Markdown 저장: {path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ChromaDB에 저장된 RAG 청크를 목록/원문/품질 지표로 확인한다.",
    )
    parser.add_argument("document_id", nargs="?", help="확인할 document_id. 없으면 문서 목록만 출력한다.")
    parser.add_argument("--quality", action="store_true", help="청크 품질 진단 보고서를 출력한다.")
    parser.add_argument("--json-output", help="품질 진단 결과 JSON 저장 경로.")
    parser.add_argument("--markdown-output", help="품질 진단 결과 Markdown 저장 경로.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME, help="ChromaDB collection 이름.")
    parser.add_argument(
        "--layout-store-dir",
        default=os.getenv("LAYOUT_STORE_DIR", DEFAULT_LAYOUT_STORE_DIR),
        help="layout sidecar store 경로.",
    )
    parser.add_argument("--chroma-host", default=os.getenv("CHROMA_HOST"), help="ChromaDB HTTP host.")
    parser.add_argument(
        "--chroma-port",
        type=int,
        default=int(os.getenv("CHROMA_PORT", str(DEFAULT_HTTP_CHROMA_PORT))),
        help="ChromaDB HTTP port.",
    )
    parser.add_argument(
        "--chroma-path",
        default=os.getenv("CHROMA_PATH", DEFAULT_LOCAL_CHROMA_PATH),
        help="PersistentClient를 사용할 때의 ChromaDB path.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    collection = _get_collection(args)

    if args.document_id:
        records = _get_document_records(collection, args.document_id)
        if not records:
            raise SystemExit(f"document_id={args.document_id} 청크를 찾지 못했다.")
    else:
        records = _get_all_records(collection)

    if args.quality:
        report = _build_quality_report(records, args.document_id, args.layout_store_dir)
        _print_quality_report(report)
        _write_json(report, args.json_output)
        _write_markdown(report, args.markdown_output)
        return

    if args.document_id:
        _print_chunks(records, args.document_id)
    else:
        _print_document_list(records)


if __name__ == "__main__":
    main()
