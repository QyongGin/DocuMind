from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from layout_blocks import (
    build_layout_summary,
    extract_opendataloader_layout,
    load_opendataloader_documents,
    validate_layout_expectations,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenDataLoader PDF markdown 출력과 JSON layout 출력을 로컬에서 비교한다.",
    )
    parser.add_argument("pdf_path", nargs="?", help="비교할 PDF 파일 경로.")
    parser.add_argument("--case-file", help="여러 layout golden case(정답 샘플셋)를 실행할 JSON 파일.")
    parser.add_argument("--pages", help="OpenDataLoader pages 인자. 예: 1 또는 3,5-7")
    parser.add_argument(
        "--output-dir",
        default="ai-server/layout_reports",
        help="비교 결과 JSON/Markdown을 저장할 폴더.",
    )
    parser.add_argument(
        "--row-tolerance",
        type=float,
        default=12.0,
        help="같은 행 후보로 볼 y 중심 좌표 허용 오차.",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=80,
        help="보고서에 표시할 block text 미리보기 글자 수.",
    )
    return parser.parse_args()


def _coerce_page(metadata: dict[str, Any]) -> int | None:
    raw_page = metadata.get("page") or metadata.get("page_number")
    if raw_page is None:
        return None
    try:
        return int(raw_page)
    except (TypeError, ValueError):
        return None


def _markdown_page_summary(markdown_docs: list[Any]) -> dict[int | str, dict[str, Any]]:
    summaries: dict[int | str, dict[str, Any]] = {}
    for index, doc in enumerate(markdown_docs, start=1):
        page = _coerce_page(getattr(doc, "metadata", {}) or {}) or f"doc-{index}"
        text = getattr(doc, "page_content", "") or ""
        lines = [line for line in text.splitlines() if line.strip()]
        summaries[page] = {
            "chars": len(text),
            "lines": len(lines),
            "heading_lines": sum(1 for line in lines if line.lstrip().startswith("#")),
            "table_lines": sum(1 for line in lines if line.strip().startswith("|") and line.strip().endswith("|")),
            "preview": re.sub(r"\s+", " ", text).strip()[:240],
        }
    return summaries


def _safe_output_stem(pdf_path: Path, pages: str | None) -> str:
    stem = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", pdf_path.stem).strip("_") or "pdf"
    if pages:
        page_label = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", pages).strip("_")
        return f"{stem}_pages_{page_label}"
    return stem


def _write_json_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# OpenDataLoader PDF Layout 비교 보고서",
        "",
        "이 보고서는 markdown text(마크다운 텍스트) 출력과 json layout(좌표 포함 레이아웃) 출력을 비교하는 진단 자료이다.",
        "자동 분리나 청킹 변경을 수행하지 않는다.",
        "",
        "```mermaid",
        "flowchart TD",
        '    A["PDF"] --> B["OpenDataLoader markdown"]',
        '    A --> C["OpenDataLoader json"]',
        '    B --> D["텍스트/heading/table 요약"]',
        '    C --> E["block type/bbox/행 후보 요약"]',
        '    D --> F["layout 기능 적용 가능성 판단"]',
        '    E --> F',
        '    F --> G["검증 통과 전 기존 청킹 유지"]',
        "```",
        "",
        "## 전체 요약",
        "",
        "|항목|값|",
        "|---|---:|",
    ]
    _append_total_rows(lines, report["totals"])
    _append_validation_rows(lines, report.get("validation"))
    _append_page_rows(lines, report["pages"])
    _append_parallel_row_samples(lines, report["pages"])
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_total_rows(lines: list[str], totals: dict[str, Any]) -> None:
    for key, value in totals.items():
        if isinstance(value, dict):
            lines.append(f"|{key}|{json.dumps(value, ensure_ascii=False)}|")
            continue
        lines.append(f"|{key}|{value}|")


def _append_validation_rows(lines: list[str], validation: dict[str, Any] | None) -> None:
    if not validation:
        return
    lines.extend(["", "## Golden Case 검증", "", "|항목|기대값|실제값|결과|", "|---|---:|---:|---|"])
    for check in validation.get("checks") or []:
        result = "통과" if check.get("passed") else "실패"
        actual = json.dumps(check.get("actual"), ensure_ascii=False)
        lines.append(f"|{check.get('name')}|{check.get('expected')}|{actual}|{result}|")


def _append_page_rows(lines: list[str], page_summaries: list[dict[str, Any]]) -> None:
    lines.extend([
        "",
        "## 페이지별 요약",
        "",
        "|page|markdown chars|markdown headings|json blocks|bbox blocks|estimated columns|parallel rows|split ready rows|split eligible|confidence|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    for page_summary in page_summaries:
        markdown = page_summary.get("markdown") or {}
        json_summary = page_summary.get("json") or {}
        confidence = json_summary.get("parallel_layout_confidence") or {}
        lines.append(
            "|{page}|{chars}|{headings}|{blocks}|{bbox}|{columns}|{parallel}|{ready}|{eligible}|{level}|".format(
                page=page_summary["page"],
                chars=markdown.get("chars", 0),
                headings=markdown.get("heading_lines", 0),
                blocks=json_summary.get("blocks", 0),
                bbox=json_summary.get("bbox_blocks", 0),
                columns=json_summary.get("estimated_column_count", 0),
                parallel=len(json_summary.get("parallel_row_candidates") or []),
                ready=confidence.get("split_ready_rows", 0),
                eligible="예" if confidence.get("eligible_for_split") else "아니오",
                level=confidence.get("level", "none"),
            )
        )
    _append_confidence_rows(lines, page_summaries)


def _append_confidence_rows(lines: list[str], page_summaries: list[dict[str, Any]]) -> None:
    lines.extend([
        "",
        "## 병렬 layout confidence",
        "",
        "|page|score|text bbox coverage|dominant columns|stable rows|body ready rows|role counts|parent region|reasons|blockers|",
        "|---|---:|---:|---:|---:|---:|---|---|---|---|",
    ])
    for page_summary in page_summaries:
        confidence = ((page_summary.get("json") or {}).get("parallel_layout_confidence") or {})
        parent_region = confidence.get("parent_region") or {}
        lines.append(
            "|{page}|{score}|{coverage}|{columns}|{rows}|{body}|{roles}|{parent}|{reasons}|{blockers}|".format(
                page=page_summary["page"],
                score=confidence.get("score", 0),
                coverage=confidence.get("text_bbox_coverage", 0),
                columns=confidence.get("dominant_column_count") or "",
                rows=confidence.get("stable_parallel_rows", 0),
                body=confidence.get("body_ready_rows", 0),
                roles=json.dumps(confidence.get("role_counts") or {}, ensure_ascii=False),
                parent=json.dumps(parent_region, ensure_ascii=False),
                reasons=", ".join(confidence.get("reasons") or []),
                blockers=", ".join(confidence.get("blockers") or []),
            )
        )


def _append_parallel_row_samples(lines: list[str], page_summaries: list[dict[str, Any]]) -> None:
    lines.append("")
    lines.append("## 같은 행의 다른 x 위치 후보")
    for page_summary in page_summaries:
        candidates = (page_summary.get("json") or {}).get("parallel_row_candidates") or []
        if not candidates:
            continue
        lines.append("")
        lines.append(f"### page {page_summary['page']}")
        for candidate in candidates[:8]:
            text = " / ".join(candidate["texts"])
            lines.append(
                f"- y={candidate['y_center']} / role={candidate.get('role', 'unknown')} / columns={candidate['distinct_columns']} / "
                f"parent={candidate.get('parent_group') or ''} / table_ancestor={candidate.get('has_table_ancestor', False)} / "
                f"x={candidate['x_ranges']} / {text}"
            )


def _build_comparison_report(
    pdf_path: Path,
    pages: str | None,
    row_tolerance: float,
    preview_chars: int,
) -> dict[str, Any]:
    markdown_docs = load_opendataloader_documents(pdf_path, "markdown", pages)
    layout_result = extract_opendataloader_layout(pdf_path, pages)
    report = build_layout_summary(
        layout_result.blocks,
        _markdown_page_summary(markdown_docs),
        row_tolerance,
        preview_chars,
    )
    report["input"] = {
        "pdf_path": str(pdf_path),
        "pages": pages,
        "row_tolerance": row_tolerance,
        "preview_chars": preview_chars,
    }
    report["layout_stats"] = asdict(layout_result.stats)
    report["layout_blocks_sample"] = [asdict(block) for block in layout_result.blocks[:100]]
    return report


def _resolve_case_pdf_path(raw_path: str, case_file: Path) -> Path:
    pdf_path = Path(raw_path).expanduser()
    if pdf_path.is_absolute():
        return pdf_path
    repo_candidate = Path.cwd() / pdf_path
    if repo_candidate.exists():
        return repo_candidate.resolve()
    return (case_file.parent / pdf_path).resolve()


def _write_report_files(report: dict[str, Any], output_dir: Path, output_stem: str) -> tuple[Path, Path]:
    json_output = output_dir / f"{output_stem}.layout-comparison.json"
    markdown_output = output_dir / f"{output_stem}.layout-comparison.md"
    _write_json_report(report, json_output)
    _write_markdown_report(report, markdown_output)
    return json_output, markdown_output


def _run_case_file(args: argparse.Namespace, output_dir: Path) -> None:
    case_file = Path(args.case_file).expanduser().resolve()
    if not case_file.exists():
        raise SystemExit(f"case file을 찾지 못했다: {case_file}")

    cases = json.loads(case_file.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise SystemExit("case file은 JSON array 형식이어야 한다.")

    failed_cases: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            raise SystemExit("case 항목은 JSON object 형식이어야 한다.")
        case_id = str(case.get("id") or "layout_case")
        pdf_path = _resolve_case_pdf_path(str(case["pdf_path"]), case_file)
        if not pdf_path.exists():
            raise SystemExit(f"PDF 파일을 찾지 못했다: {pdf_path}")

        report = _build_comparison_report(
            pdf_path,
            str(case.get("pages") or "") or None,
            args.row_tolerance,
            args.preview_chars,
        )
        report["case"] = case
        report["validation"] = validate_layout_expectations(report, case.get("expectations") or {})
        json_output, markdown_output = _write_report_files(report, output_dir, case_id)
        print(f"{case_id}: validation={report['validation']['passed']} JSON={json_output} Markdown={markdown_output}")
        if not report["validation"]["passed"]:
            failed_cases.append(case_id)

    if failed_cases:
        raise SystemExit(f"layout golden case 실패: {', '.join(failed_cases)}")


def main() -> None:
    args = _parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.case_file:
        _run_case_file(args, output_dir)
        return

    if not args.pdf_path:
        raise SystemExit("pdf_path 또는 --case-file 중 하나가 필요하다.")

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF 파일을 찾지 못했다: {pdf_path}")

    report = _build_comparison_report(
        pdf_path,
        args.pages,
        args.row_tolerance,
        args.preview_chars,
    )
    output_stem = _safe_output_stem(pdf_path, args.pages)
    json_output, markdown_output = _write_report_files(report, output_dir, output_stem)
    print(f"JSON: {json_output}")
    print(f"Markdown: {markdown_output}")


if __name__ == "__main__":
    main()
