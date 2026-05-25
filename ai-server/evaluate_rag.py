#!/usr/bin/env python3
"""Run deterministic DocuMind RAG trace/query evaluation cases."""

from __future__ import annotations

import argparse
import csv
import json
import re
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
ROMAN_NUMERAL_TRANSLATION = str.maketrans({
    "Ⅰ": "I",
    "Ⅱ": "II",
    "Ⅲ": "III",
    "Ⅳ": "IV",
    "Ⅴ": "V",
})
NUMERIC_VALUE_SUFFIXES = ("명", "점", "원", "등급", "일", "쪽", "페이지", "%")


def _translated_text(value: Any) -> str:
    return str(value or "").translate(ROMAN_NUMERAL_TRANSLATION).lower()


def _normalize_text(value: Any) -> str:
    return "".join(_translated_text(value).split())


def _numeric_search_text(value: Any) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", _translated_text(value))


def _numeric_keyword_text(value: Any) -> str:
    return "".join(_numeric_search_text(value).split())


def _numeric_run_pattern(value: str) -> str:
    return rf"(?<![\d.,]){re.escape(value)}(?![\d.,])"


def _bare_numeric_keyword_pattern(keyword: str) -> str:
    suffix_pattern = "|".join(re.escape(suffix) for suffix in NUMERIC_VALUE_SUFFIXES)
    escaped_keyword = re.escape(keyword)
    return (
        rf"(?:(?<![\d.,]){escaped_keyword}(?:{suffix_pattern})"
        rf"|(?<![0-9A-Za-z가-힣_.]){escaped_keyword}(?![0-9A-Za-z가-힣_.]))"
    )


def _numeric_keyword_pattern(keyword: str) -> str | None:
    compact_keyword = _numeric_keyword_text(keyword)
    if not re.search(r"\d", compact_keyword):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", compact_keyword):
        return _bare_numeric_keyword_pattern(compact_keyword)

    parts = []
    index = 0
    while index < len(compact_keyword):
        decimal_match = re.match(r"\d+(?:\.\d+)?", compact_keyword[index:])
        if decimal_match:
            number = decimal_match.group(0)
            parts.append(_numeric_run_pattern(number))
            index += len(number)
            continue
        parts.append(re.escape(compact_keyword[index]))
        index += 1
    return r"\s*".join(parts)


def _contains_keyword(text: str, keyword: str) -> bool:
    numeric_pattern = _numeric_keyword_pattern(keyword)
    if numeric_pattern:
        return re.search(numeric_pattern, _numeric_search_text(text)) is not None
    return _normalize_text(keyword) in _normalize_text(text)


def _missing_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if not _contains_keyword(text, keyword)]


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if _contains_keyword(text, keyword)]


def _contains_any_keyword(text: str, keywords: list[str]) -> bool:
    return any(_contains_keyword(text, keyword) for keyword in keywords)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _keyword_list(case: dict, key: str) -> list[str]:
    return [str(item) for item in _as_list(case.get(key)) if str(item).strip()]


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


def _parse_expected_pages(value: Any) -> list[int]:
    pages = []
    for item in _as_list(value):
        try:
            pages.append(int(item))
        except (TypeError, ValueError):
            continue
    return pages


def _candidate_pages(candidate: dict) -> set[int]:
    pages = set()
    for key in ("page", "page_start", "page_end"):
        value = candidate.get(key)
        try:
            if value is not None and str(value).strip():
                pages.add(int(value))
        except (TypeError, ValueError):
            continue

    page_start = candidate.get("page_start")
    page_end = candidate.get("page_end")
    try:
        start = int(page_start)
        end = int(page_end)
        if start <= end and end - start <= 20:
            pages.update(range(start, end + 1))
    except (TypeError, ValueError):
        pass
    return pages


def _missing_pages(candidates: list[dict], expected_pages: list[int]) -> list[int]:
    if not expected_pages:
        return []
    found_pages = set()
    for candidate in candidates:
        found_pages.update(_candidate_pages(candidate))
    return [page for page in expected_pages if page not in found_pages]


def _page_evidence_missing_keywords(
    candidates: list[dict],
    expected_pages: list[int],
    keywords: list[str],
) -> list[str]:
    if not expected_pages or not keywords:
        return []
    for candidate in candidates:
        if not (_candidate_pages(candidate) & set(expected_pages)):
            continue
        if not _missing_keywords(_stringify(candidate), keywords):
            return []
    return keywords


def _candidate_role_hits(candidates: list[dict], forbidden_roles: list[str], mode: str) -> list[str]:
    hits = []
    forbidden = {str(role) for role in forbidden_roles}
    if not forbidden:
        return hits
    selected_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("selected_for_prompt") is not False
    ]
    if mode == "only_without_raw":
        has_selected_raw = any(
            str(candidate.get("chunk_role") or "raw") == "raw"
            for candidate in selected_candidates
        )
        if has_selected_raw:
            return []
    for candidate in selected_candidates:
        roles = [
            candidate.get("chunk_role"),
            candidate.get("matched_chunk_role"),
            candidate.get("vector_hit_chunk_role"),
        ]
        for role in roles:
            role_text = str(role or "")
            if role_text in forbidden:
                rank = candidate.get("rank", "?")
                chunk_id = candidate.get("chunk_id", "")
                hits.append(f"rank={rank} chunk={chunk_id} role={role_text}")
    return hits


def _evidence_facts_text(candidates: list[dict]) -> str:
    facts = []
    for candidate in candidates:
        facts.extend(str(fact) for fact in _as_list(candidate.get("query_evidence_facts")))
    return "\n".join(facts)


def _trace_source_content_text(trace: dict, candidates: list[dict]) -> str:
    final_context = str(trace.get("final_context") or "")
    if final_context.strip():
        return final_context

    content_parts = []
    for candidate in candidates:
        for key in ("content", "page_content", "text"):
            value = candidate.get(key)
            if value:
                content_parts.append(str(value))
                break
    return "\n".join(content_parts)


def _evaluate_trace(case: dict, trace: dict) -> dict:
    expected_evidence_keywords = _keyword_list(case, "expected_evidence_keywords")
    forbidden_evidence_keywords = _keyword_list(case, "forbidden_evidence_keywords")
    expected_source_keywords = _keyword_list(case, "expected_source_keywords")
    expected_source_content_keywords = _keyword_list(case, "expected_source_content_keywords")
    forbidden_source_content_keywords = _keyword_list(case, "forbidden_source_content_keywords")
    expected_pages = _parse_expected_pages(case.get("expected_pages"))
    forbidden_candidate_roles = _keyword_list(case, "forbidden_candidate_roles")
    forbidden_candidate_roles_mode = str(case.get("forbidden_candidate_roles_mode") or "any_selected")
    require_page_evidence = bool(
        case.get(
            "require_evidence_on_expected_page",
            bool(expected_pages and expected_evidence_keywords),
        )
    )
    unsupported = bool(case.get("unsupported", False))
    stages = trace.get("stages", {})
    final_candidates = stages.get("final_candidates", [])
    final_context = trace.get("final_context", "")
    final_text = final_context + "\n" + _stringify(final_candidates)
    evidence_facts_text = _evidence_facts_text(final_candidates)
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
    final_source_content_text = _trace_source_content_text(trace, final_candidates)

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
    trace_source_content_missing = _missing_keywords(final_source_content_text, expected_source_content_keywords)
    trace_source_content_pass = (
        None if not expected_source_content_keywords else not trace_source_content_missing
    )
    forbidden_trace_source_content_hits = _matched_keywords(
        final_source_content_text,
        forbidden_source_content_keywords,
    )
    trace_source_content_contamination_pass = (
        None if not forbidden_source_content_keywords else not forbidden_trace_source_content_hits
    )
    forbidden_evidence_hits = _matched_keywords(evidence_facts_text, forbidden_evidence_keywords)
    evidence_contamination_pass = None if not forbidden_evidence_keywords else not forbidden_evidence_hits
    page_missing = _missing_pages(final_candidates, expected_pages)
    page_pass = None if not expected_pages else not page_missing
    missing_page_evidence_keywords = (
        _page_evidence_missing_keywords(final_candidates, expected_pages, expected_evidence_keywords)
        if require_page_evidence
        else []
    )
    page_evidence_pass = None if not require_page_evidence else not missing_page_evidence_keywords
    forbidden_candidate_role_hits = _candidate_role_hits(
        final_candidates,
        forbidden_candidate_roles,
        forbidden_candidate_roles_mode,
    )
    candidate_role_pass = None if not forbidden_candidate_roles else not forbidden_candidate_role_hits
    selected_methods = sorted(
        {
            method
            for candidate in final_candidates
            for method in (candidate.get("retrieval", {}) or {}).get("retrieval_methods", [])
        }
    )

    trace_pass = all(
        value is not False
        for value in (
            evidence_pass,
            source_pass,
            trace_source_content_pass,
            trace_source_content_contamination_pass,
            evidence_contamination_pass,
            page_pass,
            page_evidence_pass,
            candidate_role_pass,
        )
    )
    return {
        "trace_pass": trace_pass,
        "evidence_pass": evidence_pass,
        "source_pass": source_pass,
        "evidence_contamination_pass": evidence_contamination_pass,
        "trace_source_content_pass": trace_source_content_pass,
        "trace_source_content_contamination_pass": trace_source_content_contamination_pass,
        "page_pass": page_pass,
        "page_evidence_pass": page_evidence_pass,
        "candidate_role_pass": candidate_role_pass,
        "evidence_rank": evidence_rank,
        "missing_evidence_keywords": evidence_missing,
        "missing_source_keywords": source_missing,
        "missing_trace_source_content_keywords": trace_source_content_missing,
        "forbidden_trace_source_content_hits": forbidden_trace_source_content_hits,
        "forbidden_evidence_hits": forbidden_evidence_hits,
        "missing_expected_pages": page_missing,
        "missing_page_evidence_keywords": missing_page_evidence_keywords,
        "forbidden_candidate_role_hits": forbidden_candidate_role_hits,
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
    expected_answer_keywords = _keyword_list(case, "expected_answer_keywords")
    forbidden_answer_keywords = _keyword_list(case, "forbidden_answer_keywords")
    unsupported_answer_keywords = _keyword_list(case, "unsupported_answer_keywords") or DEFAULT_UNSUPPORTED_KEYWORDS
    expected_source_content_keywords = _keyword_list(case, "expected_source_content_keywords")
    forbidden_source_content_keywords = _keyword_list(case, "forbidden_source_content_keywords")
    source_content = "\n".join(str(source.get("content", "")) for source in query_response.get("sources", []))

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

    missing_source_content_keywords = _missing_keywords(source_content, expected_source_content_keywords)
    source_content_pass = None if not expected_source_content_keywords else not missing_source_content_keywords
    forbidden_source_content_hits = _matched_keywords(source_content, forbidden_source_content_keywords)
    source_content_contamination_pass = (
        None if not forbidden_source_content_keywords else not forbidden_source_content_hits
    )

    answer_pass = (
        expected_pass is not False
        and not forbidden_hits
        and source_content_pass is not False
        and source_content_contamination_pass is not False
    )
    if (
        expected_pass is None
        and not forbidden_hits
        and source_content_pass is not False
        and source_content_contamination_pass is not False
    ):
        answer_pass = None

    return {
        "answer_pass": answer_pass,
        "answer_evaluation": answer_evaluation,
        "answer": answer,
        "missing_answer_keywords": missing_answer_keywords if not unsupported else [],
        "forbidden_answer_hits": forbidden_hits,
        "source_content_pass": source_content_pass,
        "source_content_contamination_pass": source_content_contamination_pass,
        "missing_source_content_keywords": missing_source_content_keywords,
        "forbidden_source_content_hits": forbidden_source_content_hits,
        "source_count": len(query_response.get("sources", [])),
    }


def _question_variants(case: dict) -> list[tuple[str, dict, str]]:
    variants = [("primary", case, case["question"])]
    for index, variant in enumerate(case.get("variants", []), start=1):
        variants.append((f"variant_{index}", case, str(variant)))
    for index, scope_case in enumerate(case.get("scope_variant_cases", []), start=1):
        if not isinstance(scope_case, dict) or not scope_case.get("question"):
            continue
        variant_case = dict(case)
        variant_case.update(scope_case)
        variant_case["id"] = case.get("id")
        name = str(scope_case.get("name") or f"scope_variant_{index}")
        variants.append((name, variant_case, str(scope_case["question"])))
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
        "group": case.get("group"),
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
        for variant_name, variant_case, question in _question_variants(case):
            try:
                results.append(_run_single_question(args, variant_case, variant_name, question))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                results.append(
                    {
                        "id": variant_case.get("id"),
                        "variant": variant_name,
                        "category": variant_case.get("category", "uncategorized"),
                        "group": variant_case.get("group"),
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
    by_group: dict[str, dict] = {}
    for result in results:
        category = str(result.get("category") or "uncategorized")
        item = by_category.setdefault(category, {"total": 0, "overall_pass": 0, "trace_pass": 0})
        item["total"] += 1
        item["overall_pass"] += 1 if result.get("overall_pass") is True else 0
        item["trace_pass"] += 1 if result.get("trace_pass") is True else 0
        group = str(result.get("group") or "ungrouped")
        group_item = by_group.setdefault(group, {"total": 0, "overall_pass": 0, "trace_pass": 0})
        group_item["total"] += 1
        group_item["overall_pass"] += 1 if result.get("overall_pass") is True else 0
        group_item["trace_pass"] += 1 if result.get("trace_pass") is True else 0

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
        "by_group": by_group,
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
        "group",
        "overall_pass",
        "trace_pass",
        "answer_pass",
        "page_pass",
        "page_evidence_pass",
        "evidence_rank",
        "final_candidate_count",
        "selected_retrieval_methods",
        "missing_evidence_keywords",
        "forbidden_evidence_hits",
        "missing_trace_source_content_keywords",
        "forbidden_trace_source_content_hits",
        "missing_expected_pages",
        "missing_page_evidence_keywords",
        "forbidden_candidate_role_hits",
        "missing_answer_keywords",
        "forbidden_answer_hits",
        "missing_source_content_keywords",
        "forbidden_source_content_hits",
        "trace_elapsed",
        "query_elapsed",
        "question",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for result in data["results"]:
            row = dict(result)
            for key in (
                "selected_retrieval_methods",
                "missing_evidence_keywords",
                "forbidden_evidence_hits",
                "missing_trace_source_content_keywords",
                "forbidden_trace_source_content_hits",
                "missing_expected_pages",
                "missing_page_evidence_keywords",
                "forbidden_candidate_role_hits",
                "missing_answer_keywords",
                "forbidden_answer_hits",
                "missing_source_content_keywords",
                "forbidden_source_content_hits",
            ):
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
            reason = (
                result.get("error")
                or ", ".join(result.get("missing_evidence_keywords", []))
                or ", ".join(str(page) for page in result.get("missing_expected_pages", []))
                or ", ".join(result.get("missing_page_evidence_keywords", []))
                or ", ".join(result.get("forbidden_evidence_hits", []))
                or ", ".join(result.get("missing_trace_source_content_keywords", []))
                or ", ".join(result.get("forbidden_trace_source_content_hits", []))
                or ", ".join(result.get("forbidden_candidate_role_hits", []))
                or ", ".join(result.get("missing_answer_keywords", []))
                or ", ".join(result.get("forbidden_answer_hits", []))
                or ", ".join(result.get("missing_source_content_keywords", []))
                or ", ".join(result.get("forbidden_source_content_hits", []))
                or "answer/citation check failed"
            )
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
