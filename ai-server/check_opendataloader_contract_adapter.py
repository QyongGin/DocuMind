"""Smoke checks for the OpenDataLoader JSON contract adapter."""

from __future__ import annotations

from opendataloader_contract_adapter import (
    adapt_opendataloader_json_page,
    render_table_facts_as_evidence_text,
)
from rag_contracts import contract_to_dict


def build_adapter_sample() -> dict:
    """Build contract previews from a synthetic OpenDataLoader JSON page."""
    page_json = {
        "page number": 1,
        "kids": [
            {
                "type": "heading",
                "heading level": 1,
                "level": "Doctitle",
                "page number": 1,
                "bounding box": [10, 700, 200, 730],
                "content": "문서 제목",
            },
            {
                "type": "heading",
                "heading level": 2,
                "level": "Subtitle",
                "page number": 1,
                "bounding box": [10, 660, 180, 690],
                "content": "표 영역",
            },
            {
                "type": "header",
                "page number": 1,
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "반복 머리말",
                    }
                ],
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [10, 620, 280, 650],
                "content": "본문 문장입니다.",
            },
            {
                "type": "table",
                "id": 10,
                "page number": 1,
                "bounding box": [10, 460, 500, 610],
                "number of rows": 6,
                "number of columns": 4,
                "rows": [
                    {
                        "type": "table row",
                        "row number": 1,
                        "cells": [
                            _cell("구분", row=1, column=1, row_span=2),
                            _cell("지원", row=1, column=2, column_span=2),
                            _cell("설명", row=1, column=4),
                        ],
                    },
                    {
                        "type": "table row",
                        "row number": 2,
                        "cells": [
                            _cell("수시", row=2, column=2),
                            _cell("정시", row=2, column=3),
                            _cell("비고", row=2, column=4),
                        ],
                    },
                    {
                        "type": "table row",
                        "row number": 3,
                        "cells": [
                            _cell("금액", row=3, column=1),
                            _cell("", row=3, column=2),
                            _cell("", row=3, column=3),
                            _cell("", row=3, column=4),
                        ],
                    },
                    {
                        "type": "table row",
                        "row number": 4,
                        "cells": [
                            _cell("항목 A", row=4, column=1),
                            _cell("10,000원", row=4, column=2),
                            _cell("20,000원", row=4, column=3),
                            _cell(
                                "신청 이후 담당 부서 검토와 별도 확인 절차가 필요하므로 "
                                "개별 안내를 반드시 확인해야 하는 긴 설명 문장입니다. "
                                "이 내용은 하나의 행/열/값 사실로 쓰기보다 원문 SourceBlock에서 "
                                "확인해야 하는 안내 문장입니다.",
                                row=4,
                                column=4,
                            ),
                        ],
                    },
                    {
                        "type": "table row",
                        "row number": 5,
                        "cells": [
                            _cell("항목 B", row=5, column=1),
                            _cell("-", row=5, column=2),
                            _cell("30,000원", row=5, column=3),
                            _cell("검토", row=5, column=4),
                        ],
                    },
                    {
                        "type": "table row",
                        "row number": 6,
                        "cells": [
                            _cell("항목 C", row=6, column=1),
                            _cell("40,000원", row=6, column=3),
                            _cell("완료", row=6, column=4),
                        ],
                    },
                ],
            },
            {
                "type": "list",
                "page number": 1,
                "bounding box": [10, 360, 500, 450],
                "numbering style": "unordered",
                "number of list items": 2,
                "list items": [
                    {
                        "type": "list item",
                        "page number": 1,
                        "content": "첫 번째 항목",
                        "kids": [
                            {
                                "type": "paragraph",
                                "page number": 1,
                                "content": "보조 설명",
                            }
                        ],
                    },
                    {
                        "type": "list item",
                        "page number": 1,
                        "content": "두 번째 항목",
                        "kids": [],
                    },
                ],
            },
            {
                "type": "footer",
                "page number": 1,
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "반복 꼬리말",
                    }
                ],
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [10, 300, 500, 340],
                "content": "반복 라벨 반복 라벨",
            },
            {
                "type": "caption",
                "page number": 1,
                "bounding box": [10, 260, 500, 285],
                "content": "그림 1. 구조 보존 adapter 처리 흐름",
            },
            {
                "type": "formula",
                "page number": 1,
                "bounding box": [10, 235, 500, 255],
                "content": "정확도 = 정답 수 / 전체 질문 수",
            },
            {
                "type": "text_block",
                "page number": 1,
                "bounding box": [10, 220, 500, 290],
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "컨테이너 첫 문장",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "컨테이너 둘째 문장",
                    },
                ],
            },
        ],
    }
    result = adapt_opendataloader_json_page(
        page_json,
        document_id="adapter-smoke",
        source="sample.pdf",
    )
    return {
        "parsed_blocks": [contract_to_dict(block) for block in result.parsed_blocks],
        "section_nodes": [contract_to_dict(section) for section in result.section_nodes],
        "source_blocks": [contract_to_dict(block) for block in result.source_blocks],
        "table_facts": [contract_to_dict(fact) for fact in result.table_facts],
        "evidence_text": render_table_facts_as_evidence_text(result.table_facts),
        "diagnostics": [diagnostic.__dict__ for diagnostic in result.diagnostics],
    }


def main() -> None:
    """Verify adapter output without running the DocuMind runtime."""
    sample = build_adapter_sample()

    parsed_blocks = sample["parsed_blocks"]
    section_nodes = sample["section_nodes"]
    source_blocks = sample["source_blocks"]
    table_facts = sample["table_facts"]
    evidence_text = sample["evidence_text"]
    diagnostics = sample["diagnostics"]

    assert [block["block_type"] for block in parsed_blocks] == [
        "heading",
        "heading",
        "paragraph",
        "table",
        "list",
        "paragraph",
        "caption",
        "formula",
        "paragraph",
        "paragraph",
    ]
    block_texts = [block["text"] for block in parsed_blocks]
    section_by_path = {tuple(section["path"]): section for section in section_nodes}
    assert parsed_blocks[2]["metadata"]["Header 1"] == "문서 제목"
    assert parsed_blocks[2]["metadata"]["Header 2"] == "표 영역"
    assert parsed_blocks[3]["text"].splitlines()[0] == "구분 | 지원 | 지원 | 설명"
    assert parsed_blocks[3]["text"].splitlines()[1] == "구분 | 수시 | 정시 | 비고"
    assert block_texts.count("그림 1. 구조 보존 adapter 처리 흐름") == 1
    assert block_texts.count("정확도 = 정답 수 / 전체 질문 수") == 1
    assert parsed_blocks[6]["block_type"] == "caption"
    assert parsed_blocks[7]["block_type"] == "formula"
    assert source_blocks[6]["raw_text"] == "그림 1. 구조 보존 adapter 처리 흐름"
    assert source_blocks[7]["raw_text"] == "정확도 = 정답 수 / 전체 질문 수"
    assert "반복 머리말" not in block_texts
    assert "반복 꼬리말" not in block_texts
    assert "컨테이너 첫 문장\n컨테이너 둘째 문장" not in block_texts
    assert block_texts.count("컨테이너 첫 문장") == 1
    assert block_texts.count("컨테이너 둘째 문장") == 1
    assert "첫 번째 항목 보조 설명" in parsed_blocks[4]["text"]
    assert "두 번째 항목" in parsed_blocks[4]["text"]
    assert parsed_blocks[0]["page"] == 1
    assert parsed_blocks[0]["bbox"] == [10.0, 700.0, 200.0, 730.0]
    assert source_blocks[0]["raw_text"] == "문서 제목"
    assert source_blocks[0]["page_span"] == {"start": 1, "end": 1}
    assert source_blocks[0]["bbox_span"] == [[10.0, 700.0, 200.0, 730.0]]

    root_section = section_by_path[("문서 제목",)]
    table_section = section_by_path[("문서 제목", "표 영역")]
    assert root_section["block_ids"] == [parsed_blocks[0]["block_id"]]
    assert table_section["block_ids"] == [
        block["block_id"] for block in parsed_blocks[1:]
    ]
    assert table_section["page_span"] == {"start": 1, "end": 1}

    money_fact = next(fact for fact in table_facts if fact["value"] == "10,000원")
    assert money_fact["row_label"] == "항목 A"
    assert money_fact["column_label"] == "지원 > 수시"
    assert money_fact["row_header_path"] == ["금액", "항목 A"]
    assert money_fact["column_path"] == ["지원", "수시"]
    assert money_fact["value_type"] == "money"
    assert money_fact["source_block_id"] == source_blocks[3]["source_block_id"]
    assert money_fact["header_path"] == ["문서 제목", "표 영역"]

    shifted_fact = next(fact for fact in table_facts if fact["value"] == "40,000원")
    assert shifted_fact["row_label"] == "항목 C"
    assert shifted_fact["column_label"] == "지원 > 정시"
    assert shifted_fact["row_header_path"] == ["금액", "항목 C"]
    assert shifted_fact["column_path"] == ["지원", "정시"]
    assert shifted_fact["column_index"] == 2

    assert all(fact["value"] != "-" for fact in table_facts)
    assert all("긴 설명 문장" not in fact["value"] for fact in table_facts)
    assert evidence_text.startswith("[표 근거]\n표 제목: 표 영역")
    assert "행: 금액 > 항목 A / 열: 지원 > 수시 / 값: 10,000원" in evidence_text
    assert "row_label" not in evidence_text
    assert "column_label" not in evidence_text
    assert "source_block_id" not in evidence_text
    assert "긴 설명 문장" not in evidence_text

    group_diagnostics = [
        item for item in diagnostics if item["code"] == "table_group_row_detected"
    ]
    assert group_diagnostics
    assert group_diagnostics[0]["metadata"]["label"] == "금액"

    skipped_values = [
        item for item in diagnostics if item["code"] == "table_fact_value_skipped"
    ]
    assert skipped_values
    assert skipped_values[0]["metadata"]["reason"] == "overlong_text_value"

    fallback = [item for item in diagnostics if item["code"] == "fallback_required"]
    assert fallback
    fallback_reasons = {
        reason
        for item in fallback
        for reason in item["metadata"].get("reasons", [])
    }
    assert "possible_parallel_content_merge" in fallback_reasons

    print("opendataloader contract adapter smoke ok")


def _cell(
    content: str,
    *,
    row: int,
    column: int,
    row_span: int = 1,
    column_span: int = 1,
) -> dict:
    cell = {
        "type": "table cell",
        "page number": 1,
        "row number": row,
        "column number": column,
        "kids": [
            {
                "type": "paragraph",
                "page number": 1,
                "content": content,
            }
        ],
    }
    if row_span > 1:
        cell["row span"] = row_span
    if column_span > 1:
        cell["column span"] = column_span
    return cell


if __name__ == "__main__":
    main()
