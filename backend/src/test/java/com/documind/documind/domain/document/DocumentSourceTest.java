package com.documind.documind.domain.document;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 문서 출처 정보(대장 ID·원래 주소·게시일·학년도) 검사 단위 테스트.
 */
class DocumentSourceTest {

    @Test
    @DisplayName("올바른 값은 그대로, 빈 문자열은 null로 받는다")
    void validValuesAndBlanks() {
        DocumentSource source = DocumentSource.of("www/bbs/11/110588/a162900", " https://www.example.ac.kr/a?b=1 ", "2026-08-01", 2026);
        assertEquals("www/bbs/11/110588/a162900", source.ledgerId());
        assertEquals("https://www.example.ac.kr/a?b=1", source.url());
        assertEquals(LocalDate.of(2026, 8, 1), source.postedAt());
        assertEquals(2026, source.academicYear());

        DocumentSource empty = DocumentSource.of(" ", "", null, null);
        assertNull(empty.ledgerId());
        assertNull(empty.url());
        assertNull(empty.postedAt());
    }

    @Test
    @DisplayName("한글이 든 주소도 http·https면 받는다")
    void koreanPathUrl() {
        assertEquals("https://www.example.ac.kr/공지/1", DocumentSource.of(null, "https://www.example.ac.kr/공지/1", null, null).url());
    }

    @Test
    @DisplayName("틀린 칸은 INVALID_DOCUMENT_SOURCE와 어느 칸인지 알려 주는 메시지로 막는다")
    void invalidValues() {
        assertInvalid(() -> DocumentSource.of("www bbs", null, null, null), "대장 ID");
        assertInvalid(() -> DocumentSource.of(null, "ftp://example.ac.kr/a", null, null), "원래 주소");
        assertInvalid(() -> DocumentSource.of(null, "local:2026 모집요강.pdf", null, null), "원래 주소");
        assertInvalid(() -> DocumentSource.of(null, "https://" + "a".repeat(1000), null, null), "원래 주소");
        assertInvalid(() -> DocumentSource.of(null, null, "2026/08/01", null), "게시일");
        assertInvalid(() -> DocumentSource.of(null, null, null, 1800), "학년도");
    }

    private void assertInvalid(Runnable action, String field) {
        CustomException exception = assertThrows(CustomException.class, action::run);
        assertEquals(ErrorCode.INVALID_DOCUMENT_SOURCE, exception.getErrorCode());
        assertTrue(exception.getMessage().contains(field), exception.getMessage());
    }
}
