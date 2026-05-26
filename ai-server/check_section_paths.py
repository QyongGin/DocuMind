import argparse
import json
import os
from collections import Counter, defaultdict
from typing import Any

from rag_contract_builders import (
    header_path_from_metadata,
    section_path_quality,
    section_path_warnings,
)


def _create_client():
    import chromadb

    chroma_host = os.getenv("CHROMA_HOST")
    chroma_port = int(os.getenv("CHROMA_PORT", "8001"))
    chroma_path = os.getenv("CHROMA_PATH", "./chroma_db")
    if chroma_host:
        return chromadb.HttpClient(host=chroma_host, port=chroma_port)
    return chromadb.PersistentClient(path=chroma_path)


def _sample_entry(
    chunk_id: str,
    metadata: dict[str, Any],
    path: tuple[str, ...],
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "document_id": metadata.get("document_id", ""),
        "source": metadata.get("source", ""),
        "chunk_role": metadata.get("chunk_role", "raw"),
        "page": metadata.get("page"),
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end"),
        "chunk_index": metadata.get("chunk_index"),
        "header_path": list(path),
        "warnings": list(warnings),
    }


def summarize_section_paths(
    ids: list[str],
    metadatas: list[dict[str, Any] | None],
    *,
    sample_limit: int = 10,
) -> dict[str, Any]:
    quality_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    source_counts: dict[str, Counter[str]] = defaultdict(Counter)
    samples: list[dict[str, Any]] = []

    for chunk_id, metadata in zip(ids, metadatas):
        metadata = metadata or {}
        path = header_path_from_metadata(metadata)
        quality = section_path_quality(path)
        warnings = section_path_warnings(path)
        role = str(metadata.get("chunk_role") or "raw")
        source = str(metadata.get("source") or "")

        quality_counts[quality] += 1
        role_counts[role][quality] += 1
        source_counts[source][quality] += 1
        for warning in warnings:
            warning_counts[warning] += 1

        if quality == "suspect" and len(samples) < sample_limit:
            samples.append(_sample_entry(str(chunk_id), metadata, path, warnings))

    return {
        "total_entries": len(metadatas),
        "quality_counts": dict(sorted(quality_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
        "role_counts": {role: dict(sorted(counts.items())) for role, counts in sorted(role_counts.items())},
        "source_counts": {source: dict(sorted(counts.items())) for source, counts in sorted(source_counts.items())},
        "suspect_samples": samples,
    }


def _print_text(summary: dict[str, Any]) -> None:
    print(f"total_entries: {summary['total_entries']}")
    print("quality_counts:")
    for quality, count in summary["quality_counts"].items():
        print(f"  {quality}: {count}")

    print("warning_counts:")
    for warning, count in summary["warning_counts"].items():
        print(f"  {warning}: {count}")

    print("role_counts:")
    for role, counts in summary["role_counts"].items():
        joined = ", ".join(f"{quality}={count}" for quality, count in counts.items())
        print(f"  {role}: {joined}")

    print("suspect_samples:")
    for sample in summary["suspect_samples"]:
        path = " > ".join(str(item) for item in sample["header_path"])
        warnings = ", ".join(str(item) for item in sample["warnings"])
        print(
            "  - "
            f"chunk_id={sample['chunk_id']} "
            f"document_id={sample['document_id']} "
            f"role={sample['chunk_role']} "
            f"page={sample['page_start'] or sample['page']} "
            f"path={path} "
            f"warnings={warnings}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize Header 1..6 section path quality stored in ChromaDB."
    )
    parser.add_argument("--document-id", help="Limit the check to one document_id.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Maximum suspect samples to print.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    client = _create_client()
    collection = client.get_collection("documents")
    where = {"document_id": str(args.document_id)} if args.document_id else None
    results = (
        collection.get(where=where, include=["metadatas"])
        if where
        else collection.get(include=["metadatas"])
    )
    summary = summarize_section_paths(
        [str(chunk_id) for chunk_id in results.get("ids", [])],
        results.get("metadatas", []),
        sample_limit=max(0, args.sample_limit),
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(summary)


if __name__ == "__main__":
    main()
