package com.documind.documind.global.exception;

import lombok.Getter;

/**
 * 같은 파일(같은 SHA-256)을 가진 문서가 이미 살아 있을 때 던진다.
 * 응답 data에 기존 문서 번호·이름을 담아, 대량 업로드 명령이 "이미 있음"으로 기록할 수 있게 한다.
 */
@Getter
public class DuplicateDocumentException extends CustomException {

    private final ExistingDocument existing;

    /**
     * @param documentId   이미 있는 문서 PK
     * @param originalName 이미 있는 문서의 원래 파일명
     */
    public DuplicateDocumentException(Long documentId, String originalName) {
        super(ErrorCode.DUPLICATE_DOCUMENT, "이미 올린 문서입니다: " + originalName);
        this.existing = new ExistingDocument(documentId, originalName);
    }

    /**
     * 409 응답 data.
     *
     * @param documentId   이미 있는 문서 PK
     * @param originalName 이미 있는 문서의 원래 파일명
     */
    public record ExistingDocument(Long documentId, String originalName) {
    }
}
