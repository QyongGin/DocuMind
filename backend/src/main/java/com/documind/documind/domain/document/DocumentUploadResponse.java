package com.documind.documind.domain.document;

import lombok.Builder;
import lombok.Getter;

// 문서 업로드 성공 시 클라이언트에 반환하는 DTO
@Getter
@Builder
public class DocumentUploadResponse {

    private Long documentId;
    private String originalName;
    private Long fileSize;
    private int chunkCount;
    private Long processingDurationMs;
}
