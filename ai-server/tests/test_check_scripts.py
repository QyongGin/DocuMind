"""R0-1: 기존 check_*.py 검증 로직을 pytest 로 묶는 얇은 래퍼.

설계 원칙
---------
- 원본 check_*.py 는 한 줄도 바꾸지 않는다. import 해서 호출만 한다(로직 복제 금지).
- assertion 기반 스크립트 7종은 ``main()`` 을 그대로 호출한다. 실패 시
  ``AssertionError`` 가 올라오므로 pytest 가 자연히 잡는다.
- 나머지 2종은 assertion 기반 단위 테스트가 아니라 라이브 ChromaDB 진단 도구다.
  ``check_section_paths`` 는 순수 집계 함수 ``summarize_section_paths`` 를
  합성 입력으로 검증한다(스크립트가 실제로 쓰는 바로 그 로직).
  ``check_chunks`` 는 자체 assertion 이 없고 import 시점에 ChromaDB 에 붙는
  순수 출력 도구라, 라이브 DB 가 있을 때만 실행하고 평소엔 skip 한다.

총 9개 check_*.py 가 ``pytest tests/`` 한 명령으로 커버된다.
"""

from __future__ import annotations

import importlib
import os

import pytest

# ``main()`` 안에서 assert 로 스스로를 검증하는 스크립트들.
ASSERTION_CHECK_MODULES = [
    "check_opendataloader_contract_adapter",
    "check_opendataloader_json_indexing",
    "check_query_evidence_priority",
    "check_rag_contracts",
    "check_table_fact_evidence",
    "check_table_fact_runtime_extraction",
    "check_table_fact_selector",
]


@pytest.mark.parametrize("module_name", ASSERTION_CHECK_MODULES)
def test_assertion_check_script_main(module_name):
    """assertion 기반 check 스크립트의 main() 을 그대로 호출해 통과를 확인한다."""
    module = importlib.import_module(module_name)
    # main() 은 내부 assert 로 검증하며 실패 시 AssertionError 를 던진다.
    module.main()


def test_section_path_summary_classifies_quality():
    """check_section_paths 의 순수 집계 로직을 합성 metadata 로 검증한다.

    라이브 ChromaDB 없이도 스크립트가 실제로 쓰는 ``summarize_section_paths``
    분류 로직(ok / suspect / missing)을 그대로 통과시킨다.
    """
    from check_section_paths import summarize_section_paths

    ids = ["chunk-ok", "chunk-suspect", "chunk-missing"]
    metadatas = [
        # 정상 섹션 경로: Header 1/2 가 문서 제목처럼 보인다 -> ok
        {
            "document_id": "synthetic",
            "source": "synthetic.pdf",
            "chunk_role": "raw",
            "Header 1": "문서 제목",
            "Header 2": "표 영역",
        },
        # 표 값이 섹션 경로로 새어든 경우: "569명" -> suspect
        {
            "document_id": "synthetic",
            "source": "synthetic.pdf",
            "chunk_role": "raw",
            "Header 1": "569명",
        },
        # 섹션 경로가 아예 없는 경우 -> missing
        {
            "document_id": "synthetic",
            "source": "synthetic.pdf",
            "chunk_role": "raw",
        },
    ]

    summary = summarize_section_paths(ids, metadatas)

    assert summary["total_entries"] == 3
    assert summary["quality_counts"].get("ok") == 1
    assert summary["quality_counts"].get("suspect") == 1
    assert summary["quality_counts"].get("missing") == 1
    # suspect 한 건만 샘플로 잡혀야 한다.
    assert len(summary["suspect_samples"]) == 1
    assert summary["suspect_samples"][0]["chunk_id"] == "chunk-suspect"


def test_check_chunks_live_diagnostic():
    """check_chunks 는 라이브 ChromaDB 진단 도구다 (자체 assertion 없음).

    import 시점에 ChromaDB 에 붙어 document_id 목록을 출력하는 순수 도구라,
    결정론적 단위 테스트로 만들 자체 검증 로직이 없다. 실제 DB 가 준비된
    환경에서만 ``DOCUMIND_TEST_LIVE_CHROMA=1`` 로 import 가 깨지지 않는지
    확인하고, 평소에는 명시적 사유와 함께 skip 한다.
    """
    if os.getenv("DOCUMIND_TEST_LIVE_CHROMA") != "1":
        pytest.skip(
            "check_chunks.py 는 라이브 ChromaDB 진단 도구다(자체 assertion 없음). "
            "DOCUMIND_TEST_LIVE_CHROMA=1 로 실제 DB 가 있을 때만 실행한다."
        )

    # 라이브 DB 가 있다고 선언된 경우: import 가 연결/조회까지 깨지지 않는지 확인.
    importlib.import_module("check_chunks")
