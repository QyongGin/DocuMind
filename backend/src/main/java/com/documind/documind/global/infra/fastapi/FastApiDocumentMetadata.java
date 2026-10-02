package com.documind.documind.global.infra.fastapi;

import java.time.LocalDate;

/**
 * 업로드 때 AI 서버에 함께 넘기는 문서 단위 메타데이터. AI 서버는 이 값을 청크마다 넣는다(#126 결정 1).
 * 값이 없는 칸은 보내지 않는다.
 *
 * @param ledgerId     문서 대장 ID
 * @param sourceUrl    원래 주소
 * @param postedAt     원래 게시일
 * @param academicYear 학년도
 * @param categoryId   카테고리 PK(M2 검색 범위 좁히기는 번호로 한다)
 * @param categoryName 카테고리 이름(확인·표시용)
 */
public record FastApiDocumentMetadata(
        String ledgerId,
        String sourceUrl,
        LocalDate postedAt,
        Integer academicYear,
        Long categoryId,
        String categoryName
) {

    /** 메타데이터 없이 올릴 때. */
    public static final FastApiDocumentMetadata EMPTY = new FastApiDocumentMetadata(null, null, null, null, null, null);
}
