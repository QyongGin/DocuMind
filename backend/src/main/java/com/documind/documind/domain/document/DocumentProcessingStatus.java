package com.documind.documind.domain.document;

/**
 * 문서가 RAG 검색에 사용 가능한 상태인지 나타내는 처리 상태이다.
 */
public enum DocumentProcessingStatus {
    PROCESSING,
    READY,
    FAILED
}
