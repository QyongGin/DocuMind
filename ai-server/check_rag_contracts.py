"""Smoke check for the RAG data contract skeleton."""

from __future__ import annotations

import json

from rag_contract_builders import (
    build_parsed_block,
    build_query_intent,
    build_retrieval_chunk,
    build_section_node,
    build_source_citation,
    build_source_reference,
    build_source_block,
    build_table_cell_fact,
    infer_table_value_type,
    section_path_component_is_suspect,
    section_path_quality,
    section_path_warnings,
)
from rag_contracts import (
    Candidate,
    SelectedContext,
    SelectedContextItem,
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
    table_fact = build_table_cell_fact(
        document_id="sample",
        table_index=1,
        row_index=1,
        column_index=1,
        row_label="Item A",
        column_label="Value",
        value="10만 원",
        source_block_id=source_block.source_block_id,
        caption="Table Section",
        header_path=("Table Section",),
        confidence=0.95,
    )
    query_intent = build_query_intent(
        query="원서 접수 비용은 얼마인가요?",
        intent="cost",
        subject_terms=("원서", "접수"),
        primary_terms=("원서접수",),
        context_terms=("원서", "접수", "비용", "얼마"),
        intent_terms=("비용", "얼마"),
        notes=("temporary rule-based bridge before QueryIntent runtime",),
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
        future_metadata_keys=("source_block_id", "source_lookup_id"),
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
        "query_intent": contract_to_dict(query_intent),
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
    assert decoded["source_reference"]["metadata_keys"] == []
    assert decoded["source_reference"]["future_metadata_keys"] == [
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
    assert decoded["table_fact"]["row_label"] == "Item A"
    assert decoded["table_fact"]["column_label"] == "Value"
    assert decoded["table_fact"]["value"] == "10만 원"
    assert decoded["table_fact"]["value_type"] == "money"
    assert decoded["table_fact"]["unit"] == "만원"
    assert decoded["table_fact"]["caption"] == "Table Section"
    assert decoded["query_intent"]["intent"] == "cost"
    assert decoded["query_intent"]["subject_terms"] == ["원서", "접수"]
    assert decoded["query_intent"]["primary_terms"] == ["원서접수"]
    assert decoded["query_intent"]["intent_terms"] == ["비용", "얼마"]
    assert decoded["query_intent"]["runtime_connection"] == "trace_only"
    assert infer_table_value_type("30,000원") == ("money", "원")
    assert infer_table_value_type("5천 원") == ("money", "천원")
    assert infer_table_value_type("12명") == ("count", "명")
    assert infer_table_value_type("2026.05.27") == ("date", None)
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
