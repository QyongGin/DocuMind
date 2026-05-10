package com.documind.documind.domain.document;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

/**
 * 문서 목록 조회 시 각 문서의 요약 정보를 담는 DTO.
 * summary는 고도화 단계에서 사용하므로 현재는 포함하지 않는다.
 */
@Getter
@Builder
public class DocumentListResponse {

    private Long id;
    private String originalName;
    private String mimeType;
    private Long fileSize;
    private int chunkCount;
    /** 카테고리 미분류 문서는 null */
    private Long categoryId;
    /** 카테고리 미분류 문서는 null */
    private String categoryName;
    /** 문서 처리 완료까지 걸린 시간(ms). 기존 데이터나 처리 전 문서는 null */
    private Long processingDurationMs;
    /** 문서 색인 처리 상태. 기존 데이터는 READY로 보정한다. */
    private DocumentProcessingStatus processingStatus;
    private LocalDateTime createdAt;

    /** Document Entity를 DTO로 변환한다. */
    public static DocumentListResponse from(Document document) {
        return DocumentListResponse.builder()
                .id(document.getId())
                .originalName(document.getOriginalName())
                .mimeType(document.getMimeType())
                .fileSize(document.getFileSize())
                .chunkCount(document.getChunkCount())
                .categoryId(document.getCategory() != null ? document.getCategory().getId() : null)
                .categoryName(document.getCategory() != null ? document.getCategory().getName() : null)
                .processingDurationMs(document.getProcessingDurationMs())
                .processingStatus(resolveProcessingStatus(document))
                .createdAt(document.getCreatedAt())
                .build();
    }

    private static DocumentProcessingStatus resolveProcessingStatus(Document document) {
        return document.getProcessingStatus() != null ? document.getProcessingStatus() : DocumentProcessingStatus.READY;
    }
}
