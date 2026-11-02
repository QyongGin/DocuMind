package com.documind.documind.domain.document;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 문서 게시 정보(사이트·게시판·제목·첨부의 게시글) 검사 단위 테스트(ADR-0051).
 */
class DocumentOriginTest {

    @Test
    @DisplayName("올바른 값은 앞뒤 공백을 빼고, 빈 문자열은 null로 받는다")
    void validValuesAndBlanks() {
        DocumentOrigin origin = new DocumentOrigin(" cs ", "가나학과", "학사(11)", " 2학기 수강신청 안내 ",
                "수강신청 공지", "https://www.ganada.ac.kr/bbs/11/1");
        assertEquals(new DocumentOrigin("cs", "가나학과", "학사(11)", "2학기 수강신청 안내", "수강신청 공지",
                "https://www.ganada.ac.kr/bbs/11/1"), origin);
        assertEquals(DocumentOrigin.EMPTY, new DocumentOrigin("", " ", null, "", null, " "));
    }

    @Test
    @DisplayName("틀린 칸은 INVALID_DOCUMENT_SOURCE와 어느 칸인지 알려 주는 메시지로 막는다")
    void invalidValues() {
        assertInvalid(() -> new DocumentOrigin("www bbs", null, null, null, null, null), "사이트 코드");
        assertInvalid(() -> new DocumentOrigin(null, "가".repeat(101), null, null, null, null), "사이트 이름");
        assertInvalid(() -> new DocumentOrigin(null, null, "가".repeat(101), null, null, null), "게시판 이름");
        assertInvalid(() -> new DocumentOrigin(null, null, null, "가".repeat(501), null, null), "제목");
        assertInvalid(() -> new DocumentOrigin(null, null, null, null, "가".repeat(501), null), "게시글 제목");
        assertInvalid(() -> new DocumentOrigin(null, null, null, null, null, "ftp://ganada.ac.kr/a"), "게시글 주소");
    }

    @Test
    @DisplayName("게시 정보 채우기 요청은 대장 ID가 없거나 형식이 틀리면 막는다")
    void updateRequestNeedsLedgerId() {
        assertInvalid(() -> new DocumentOriginUpdateRequest(" ", "www", null, null, null, null, null).requiredLedgerId(), "대장 ID");
        assertInvalid(() -> new DocumentOriginUpdateRequest("www bbs", "www", null, null, null, null, null).requiredLedgerId(), "대장 ID");
        assertEquals("www/bbs/11/1", new DocumentOriginUpdateRequest(" www/bbs/11/1 ", null, null, null, null, null, null).requiredLedgerId());
    }

    private void assertInvalid(Runnable action, String field) {
        CustomException exception = assertThrows(CustomException.class, action::run);
        assertEquals(ErrorCode.INVALID_DOCUMENT_SOURCE, exception.getErrorCode());
        assertTrue(exception.getMessage().contains(field), exception.getMessage());
    }
}
