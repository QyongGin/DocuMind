package com.documind.documind.domain.chat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 흐르는 답의 출처 번호 거르기 단위 테스트(ADR-0051 결정 4).
 */
class CitationStreamFilterTest {

    @Test
    @DisplayName("출처 번호가 토큰 여러 개로 끊겨 와도 붙잡았다가 버린다")
    void dropsCitationSplitAcrossTokens() {
        CitationStreamFilter filter = new CitationStreamFilter();

        assertEquals("휴학은 8월까지입니다.\n\n", filter.accept("휴학은 8월까지입니다.\n\n["));
        assertEquals("", filter.accept("출처"));
        assertEquals("", filter.accept(" 1"));
        assertEquals(" 문의는 학사지원팀입니다.", filter.accept("] 문의는 학사지원팀입니다."));
        assertEquals("", filter.flush());
    }

    @Test
    @DisplayName("출처 번호가 아니라고 판가름 나면 붙잡은 글을 그대로 보낸다")
    void releasesBracketsThatAreNotCitations() {
        CitationStreamFilter filter = new CitationStreamFilter();

        assertEquals("[참고] 신청서", filter.accept("[참고] 신청서"));
        assertEquals("가격은 ", filter.accept("가격은 ["));
        assertEquals("[10만 원]", filter.accept("10만 원]"));
        assertEquals("요금 입니다", filter.accept("요금 [출처 1, 3]입니다"));
    }

    @Test
    @DisplayName("끝나지 않은 출처 번호는 끝에 내보내고, 너무 길게 붙잡지 않는다")
    void flushesHeldTextAndCapsHolding() {
        CitationStreamFilter filter = new CitationStreamFilter();
        assertEquals("끝 ", filter.accept("끝 [출처"));
        assertEquals("[출처", filter.flush());

        String longList = "[출처 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13";
        assertEquals(longList, filter.accept(longList));
    }
}
