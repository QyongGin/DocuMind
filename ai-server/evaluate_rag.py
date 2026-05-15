#!/usr/bin/env python3
"""Run deterministic DocuMind RAG trace/query evaluation cases."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_QUESTIONS_PATH = Path(__file__).with_name("rag_quality_questions.json")
DEFAULT_UNSUPPORTED_KEYWORDS = [
    "제공된 문서에서는 확인할 수 없습니다",
    "문서에서는 확인할 수 없습니다",
    "찾을 수 없습니다",
]


def _normalize_text(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def _contains_keyword(text: str, keyword: str) -> bool:
    return _normalize_text(keyword) in _normalize_text(text)


def _missing_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if not _contains_keyword(text, keyword)]


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if _contains_keyword(text, keyword)]


def _contains_any_keyword(text: str, keywords: list[str]) -> bool:
    return any(_contains_keyword(text, keyword) for keyword in keywords)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_stringify(item)}" for key, item in value.items())
    return str(value)


def _post_json(base_url: str, path: str, payload: dict, timeout: float) -> dict:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _first_matching_rank(candidates: list[dict], keywords: list[str]) -> int | None:
    if not keywords:
        return None
    for candidate in candidates:
        text = _stringify(candidate)
        if not _missing_keywords(text, keywords):
            rank = candidate.get("rank")
            return int(rank) if isinstance(rank, int) else None
    return None


def _evaluate_trace(case: dict, trace: dict) -> dict:
    expected_evidence_keywords = case.get("expected_evidence_keywords", [])
    expected_source_keywords = case.get("expected_source_keywords", [])
    unsupported = bool(case.get("unsupported", False))
    stages = trace.get("stages", {})
    final_candidates = stages.get("final_candidates", [])
    final_context = trace.get("final_context", "")
    final_text = final_context + "\n" + _stringify(final_candidates)
    final_source_text = "\n".join(
        _stringify(
            {
                "source": candidate.get("source"),
                "header_path": candidate.get("header_path"),
                "page": candidate.get("page"),
                "chunk_id": candidate.get("chunk_id"),
            }
        )
        for candidate in final_candidates
    )

    evidence_missing = _missing_keywords(final_text, expected_evidence_keywords)
    evidence_rank = _first_matching_rank(final_candidates, expected_evidence_keywords)
    if unsupported and not expected_evidence_keywords:
        evidence_pass = True
    elif not expected_evidence_keywords:
        evidence_pass = None
    else:
        evidence_pass = not evidence_missing

    source_missing = _missing_keywords(final_source_text, expected_source_keywords)
    source_pass = None if not expected_source_keywords else not source_missing
    selected_methods = sorted(
        {
            method
            for candidate in final_candidates
            for method in (candidate.get("retrieval", {}) or {}).get("retrieval_methods", [])
        }
    )

    trace_pass = all(
        value is not False for value in (evidence_pass, source_pass)
    )
    return {
        "trace_pass": trace_pass,
        "evidence_pass": evidence_pass,
        "source_pass": source_pass,
        "evidence_rank": evidence_rank,
        "missing_evidence_keywords": evidence_missing,
        "missing_source_keywords": source_missing,
        "final_candidate_count": len(final_candidates),
        "selected_retrieval_methods": selected_methods,
        "query_analysis": trace.get("query_analysis", {}),
        "timing": trace.get("timing", {}),
    }


def _evaluate_answer(case: dict, query_response: dict | None) -> dict:
    if query_response is None:
        return {
            "answer_pass": None,
            "answer_evaluation": "skipped",
        }

    answer = str(query_response.get("answer", ""))
    unsupported = bool(case.get("unsupported", False))
    expected_answer_keywords = case.get("expected_answer_keywords", [])
    forbidden_answer_keywords = case.get("forbidden_answer_keywords", [])
    unsupported_answer_keywords = case.get(
        "unsupported_answer_keywords",
        DEFAULT_UNSUPPORTED_KEYWORDS,
    )

    forbidden_hits = _matched_keywords(answer, forbidden_answer_keywords)
    if unsupported:
        expected_pass = _contains_any_keyword(answer, unsupported_answer_keywords)
        answer_evaluation = "unsupported_guard"
    elif expected_answer_keywords:
        missing_answer_keywords = _missing_keywords(answer, expected_answer_keywords)
        expected_pass = not missing_answer_keywords
        answer_evaluation = "expected_keywords"
    else:
        missing_answer_keywords = []
        expected_pass = None
        answer_evaluation = "no_expected_answer_keywords"

    answer_pass = expected_pass is not False and not forbidden_hits
    if expected_pass is None and not forbidden_hits:
        answer_pass = None

    return {
        "answer_pass": answer_pass,
        "answer_evaluation": answer_evaluation,
        "answer": answer,
        "missing_answer_keywords": missing_answer_keywords if not unsupported else [],
        "forbidden_answer_hits": forbidden_hits,
        "source_count": len(query_response.get("sources", [])),
    }


def _question_variants(case: dict) -> list[tuple[str, str]]:
    variants = [("primary", case["question"])]
    for index, variant in enumerate(case.get("variants", []), start=1):
        variants.append((f"variant_{index}", str(variant)))
    return variants


def _load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list):
        raise ValueError("질문 파일은 JSON 배열이어야 합니다.")
    return cases


def _select_cases(cases: list[dict], case_ids: set[str], limit: int | None) -> list[dict]:
    selected = [case for case in cases if not case_ids or str(case.get("id")) in case_ids]
    if limit is not None:
        return selected[:limit]
    return selected


def _run_single_question(args: argparse.Namespace, case: dict, variant_name: str, question: str) -> dict:
    top_k = int(args.top_k or case.get("top_k", 5))
    payload = {"question": question, "top_k": top_k}
    if args.system_prompt:
        payload["system_prompt"] = args.system_prompt

    started = time.perf_counter()
    trace = _post_json(args.base_url, "/debug/rag-trace", payload, args.timeout)
    trace_elapsed = time.perf_counter() - started
    trace_result = _evaluate_trace(case, trace)

    query_response = None
    query_elapsed = None
    if args.include_query:
        query_started = time.perf_counter()
        query_response = _post_json(args.base_url, "/query", payload, args.query_timeout)
        query_elapsed = time.perf_counter() - query_started
    answer_result = _evaluate_answer(case, query_response)

    answer_pass = answer_result["answer_pass"]
    overall_pass = trace_result["trace_pass"] and (answer_pass is not False)
    return {
        "id": case.get("id"),
        "variant": variant_name,
        "category": case.get("category", "uncategorized"),
        "question": question,
        "top_k": top_k,
        "overall_pass": overall_pass,
        "trace_elapsed": round(trace_elapsed, 4),
        "query_elapsed": round(query_elapsed, 4) if query_elapsed is not None else None,
        **trace_result,
        **answer_result,
    }


def _run_evaluation(args: argparse.Namespace) -> dict:
    cases = _select_cases(_load_cases(args.questions), set(args.case_id), args.limit)
    results = []
    for case in cases:
        for variant_name, question in _question_variants(case):
            try:
                results.append(_run_single_question(args, case, variant_name, question))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                results.append(
                    {
                        "id": case.get("id"),
                        "variant": variant_name,
                        "category": case.get("category", "uncategorized"),
                        "question": question,
                        "overall_pass": False,
                        "trace_pass": False,
                        "answer_pass": None,
                        "error": str(error),
                    }
                )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "questions_path": str(args.questions),
        "include_query": args.include_query,
        "case_count": len(cases),
        "question_count": len(results),
        "summary": _build_summary(results),
        "results": results,
    }


def _build_summary(results: list[dict]) -> dict:
    total = len(results)
    overall_passes = sum(1 for result in results if result.get("overall_pass") is True)
    trace_passes = sum(1 for result in results if result.get("trace_pass") is True)
    answer_evaluated = [
        result for result in results if result.get("answer_pass") is not None
    ]
    answer_passes = sum(1 for result in answer_evaluated if result.get("answer_pass") is True)
    by_category: dict[str, dict] = {}
    for result in results:
        category = str(result.get("category") or "uncategorized")
        item = by_category.setdefault(category, {"total": 0, "overall_pass": 0, "trace_pass": 0})
        item["total"] += 1
        item["overall_pass"] += 1 if result.get("overall_pass") is True else 0
        item["trace_pass"] += 1 if result.get("trace_pass") is True else 0

    return {
        "total": total,
        "overall_pass": overall_passes,
        "overall_pass_rate": round(overall_passes / total, 4) if total else 0,
        "trace_pass": trace_passes,
        "trace_pass_rate": round(trace_passes / total, 4) if total else 0,
        "answer_evaluated": len(answer_evaluated),
        "answer_pass": answer_passes,
        "answer_pass_rate": round(answer_passes / len(answer_evaluated), 4) if answer_evaluated else None,
        "by_category": by_category,
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _write_csv(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "variant",
        "category",
        "overall_pass",
        "trace_pass",
        "answer_pass",
        "evidence_rank",
        "final_candidate_count",
        "selected_retrieval_methods",
        "missing_evidence_keywords",
        "missing_answer_keywords",
        "forbidden_answer_hits",
        "trace_elapsed",
        "query_elapsed",
        "question",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for result in data["results"]:
            row = dict(result)
            for key in ("selected_retrieval_methods", "missing_evidence_keywords", "missing_answer_keywords", "forbidden_answer_hits"):
                row[key] = "|".join(str(item) for item in row.get(key, []))
            writer.writerow(row)


def _print_summary(data: dict) -> None:
    summary = data["summary"]
    print(
        f"RAG evaluation: overall {summary['overall_pass']}/{summary['total']} "
        f"({summary['overall_pass_rate']:.2%}), trace {summary['trace_pass']}/{summary['total']} "
        f"({summary['trace_pass_rate']:.2%})"
    )
    if summary["answer_evaluated"]:
        print(
            f"Answer checks: {summary['answer_pass']}/{summary['answer_evaluated']} "
            f"({summary['answer_pass_rate']:.2%})"
        )
    failed = [result for result in data["results"] if result.get("overall_pass") is not True]
    if failed:
        print("Failed cases:")
        for result in failed[:20]:
            reason = result.get("error") or ", ".join(result.get("missing_evidence_keywords", [])) or "answer/citation check failed"
            print(f"- {result.get('id')} [{result.get('variant')}]: {reason}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate DocuMind RAG trace/query quality cases.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-query", action="store_true")
    parser.add_argument("--system-prompt")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--query-timeout", type=float, default=180.0)
    parser.add_argument("--fail-on-miss", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    data = _run_evaluation(args)
    if args.output:
        _write_json(args.output, data)
    if args.csv_output:
        _write_csv(args.csv_output, data)
    _print_summary(data)
    if args.fail_on_miss and data["summary"]["overall_pass"] != data["summary"]["total"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
