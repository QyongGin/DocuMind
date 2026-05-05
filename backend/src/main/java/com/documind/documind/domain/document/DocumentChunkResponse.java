package com.documind.documind.domain.document;

import lombok.Builder;
import lombok.Getter;

import java.util.Map;

/**
 * 관리자 문서 상세에서 확인하는 ChromaDB 청크 응답 DTO.
 */
@Getter
@Builder
public class DocumentChunkResponse {

    private String id;
    private int chunkIndex;
    private String content;
    private Map<String, Object> metadata;
}
