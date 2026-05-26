"""Smoke check for the RAG data contract skeleton."""

from __future__ import annotations

import json

from rag_contract_builders import (
    build_parsed_block,
    build_retrieval_chunk,
    build_section_node,
    build_source_citation,
    build_source_reference,
    build_source_block,
    section_path_component_is_suspect,
    section_path_quality,
    section_path_warnings,
)
from rag_contracts import (
    Candidate,
    SelectedContext,
    SelectedContextItem,
    TableFact,
    contract_to_dict,
)


def build_contract_sample() -> dict:
    """Build a minimal end-to-end contract sample without touching runtime code."""
    metadata = {
        "page_start": "1",
        "page_end": "2",
        "Header 1": "Document",
        "Header 2": "Table Section",
        "block_type": "table",
        "bbox": [0, 0, 100, 50],
    }
    parsed_block = build_parsed_block(
        document_id="sample",
        document_format="pdf",
        text="| Item | Value |\n| Item A | 10 |",
        block_index=1,
        metadata=metadata,
        parser_confidence=0.95,
    )
    section = build_section_node(parsed_block)
    assert section is not None
    source_block = build_source_block(
        parsed_block,
        section_id=section.section_id,
    )
    retrieval_chunk = build_retrieval_chunk(
        parsed_block,
        source_block,
        section,
    )
    table_fact = TableFact(
        fact_id="doc-sample:fact-001",
        fact_type="row_cell",
        table_id="doc-sample:table-001",
        row_subject="Item A",
        column_path=("Value",),
        header_path=("Table Section",),
        value="10",
        source_block_id=source_block.source_block_id,
        confidence=0.95,
    )
    candidate = Candidate(
        candidate_id="doc-sample:candidate-001",
        retrieval_chunk_id=retrieval_chunk.retrieval_chunk_id,
        scores={"vector": 0.91, "bm25": 12.5},
        methods=("vector", "bm25", "table_fact"),
        fact_ids=(table_fact.fact_id,),
        source_block_ids=(source_block.source_block_id,),
        diagnostics={"failure_type_guard": "table_relation_loss"},
    )
    citation = build_source_citation(
        source_block,
        source="sample.pdf",
        excerpt_chars=18,
    )
    source_reference = build_source_reference(
        source_block,
        lookup_id="sample_1",
        metadata_keys=("source_block_id", "source_lookup_id"),
    )
    selected_context = SelectedContext(
        context_id="doc-sample:context-001",
        items=(
            SelectedContextItem(
                candidate_id=candidate.candidate_id,
                prompt_text="Item A has value 10.",
                fact_ids=(table_fact.fact_id,),
                source_block_ids=(source_block.source_block_id,),
            ),
        ),
        prompt_text="Item A has value 10.",
        supporting_fact_ids=(table_fact.fact_id,),
        citation_ids=(citation.citation_id,),
    )

    return {
        "parsed_block": contract_to_dict(parsed_block),
        "section": contract_to_dict(section),
        "source_block": contract_to_dict(source_block),
        "retrieval_chunk": contract_to_dict(retrieval_chunk),
        "table_fact": contract_to_dict(table_fact),
        "candidate": contract_to_dict(candidate),
        "citation": contract_to_dict(citation),
        "source_reference": contract_to_dict(source_reference),
        "selected_context": contract_to_dict(selected_context),
    }


def main() -> None:
    """Verify that the skeleton contracts can produce stable JSON."""
    sample = build_contract_sample()
    encoded = json.dumps(sample, ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["parsed_block"]["block_id"] == "doc-sample:block-000001"
    assert decoded["parsed_block"]["metadata"]["block_type"] == "table"
    assert decoded["section"]["path"] == ["Document", "Table Section"]
    assert decoded["section"]["title"] == "Table Section"
    assert decoded["section"]["level"] == 2
    assert decoded["section"]["page_span"] == {"start": 1, "end": 2}
    assert section_path_quality(("Document", "Table Section")) == "ok"
    assert section_path_quality(("569명",)) == "suspect"
    assert section_path_component_is_suspect("569명") is True
    assert section_path_component_is_suspect("30,000원") is True
    assert section_path_component_is_suspect("423만원") is True
    assert section_path_component_is_suspect("1조원") is True
    assert section_path_component_is_suspect("2. 정원외 전형 모집인원") is False
    assert section_path_component_is_suspect("2026학년도 입학전형") is False
    assert "numeric_value_section_component" in section_path_warnings(("569명",))
    assert "numeric_value_section_component" in section_path_warnings(("423만원",))
    assert decoded["source_block"]["raw_text"] == sample["parsed_block"]["text"]
    assert decoded["source_block"]["section_id"] == decoded["section"]["section_id"]
    assert decoded["source_block"]["page_span"] == {"start": 1, "end": 2}
    assert decoded["source_block"]["bbox_span"] == [[0.0, 0.0, 100.0, 50.0]]
    assert decoded["citation"]["source_block_id"] == decoded["source_block"]["source_block_id"]
    assert decoded["citation"]["page_label"] == "pages 1-2"
    assert decoded["citation"]["excerpt"] == "| Item | Value |\n|..."
    assert decoded["citation"]["span"] == {"start": 0, "end": 18}
    assert decoded["source_reference"]["source_block_id"] == decoded["source_block"]["source_block_id"]
    assert decoded["source_reference"]["source_collection"] == "documents"
    assert decoded["source_reference"]["lookup_id"] == "sample_1"
    assert decoded["source_reference"]["runtime_connection"] == "trace_only"
    assert decoded["source_reference"]["metadata_keys"] == [
        "source_block_id",
        "source_lookup_id",
    ]
    assert decoded["retrieval_chunk"]["strategy"] == "section_prefixed_raw"
    assert decoded["retrieval_chunk"]["retrieval_text"].startswith(
        "Document > Table Section\n"
    )
    assert decoded["retrieval_chunk"]["source_block_ids"] == [
        decoded["source_block"]["source_block_id"]
    ]
    assert decoded["retrieval_chunk"]["section_ids"] == [decoded["section"]["section_id"]]
    assert decoded["table_fact"]["source_block_id"] == decoded["source_block"]["source_block_id"]
    assert decoded["selected_context"]["citation_ids"] == [decoded["citation"]["citation_id"]]

    suspect_metadata = {"Header 1": "423만원"}
    suspect_parsed = build_parsed_block(
        document_id="sample",
        document_format="pdf",
        text="원서접수 비용 423만원",
        block_index=2,
        metadata=suspect_metadata,
    )
    suspect_section = build_section_node(suspect_parsed)
    assert suspect_section is not None
    suspect_source = build_source_block(
        suspect_parsed,
        section_id=suspect_section.section_id,
    )
    suspect_retrieval = build_retrieval_chunk(suspect_parsed, suspect_source, suspect_section)
    assert suspect_retrieval.strategy == "raw"
    assert suspect_retrieval.section_ids == ()
    assert suspect_retrieval.retrieval_text == suspect_source.raw_text
    print("rag_contracts smoke ok")


if __name__ == "__main__":
    main()
