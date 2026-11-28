package com.documind.documind.domain.chat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 흐르는 답의 확인 줄 떼기 단위 테스트(ADR-0050 변경 메모 2026-11-28). 예시는 지어낸 가나대학이다.
 */
class WorkingLineStreamFilterTest {

    @Test
    @DisplayName("줄머리가 토큰 사이에서 잘려 와도 확인 줄을 붙잡고, 결론 줄머리 뒤의 글부터 흘린다")
    void holdsWorkingLinesSplitAcrossTokens() {
        WorkingLineStreamFilter filter = new WorkingLineStreamFilter();

        assertEquals("", filter.accept("확인"));
        assertEquals("", filter.accept("한 행"));
        assertEquals("", filter.accept(":\n- 가나"));
        assertEquals("", filter.accept("학과: 40명 [출처 2]\n- 다라학과: 35명\n결"));
        assertEquals("", filter.accept("론:"));
        assertEquals("", filter.accept(" "));
        assertEquals("정원이 30명을", filter.accept("정원이 30명을"));
        assertEquals(" 넘는 학과는 가나학과와 다라학과입니다.\n\n[출처 2]",
                filter.accept(" 넘는 학과는 가나학과와 다라학과입니다.\n\n[출처 2]"));
        assertEquals("", filter.flush());
    }

    @Test
    @DisplayName("근거 글과 고른 표 머리도 같은 약속으로 떼고, 결론 줄머리와 결론이 한 토큰에 와도 결론부터 흘린다")
    void removesOtherWorkingHeaders() {
        assertEquals("휴학 중에는 신청할 수 없습니다.", streamed(
                List.of("근거", " 글: 휴학 중인 학생은 신청할 수 없다.", "\n결론: 휴학 중에는 신청할 수 없습니다.")));
        assertEquals("2026학년도 수강신청은 2월 10일부터입니다.", streamed(
                List.of("\n고른 표: 2026학년도 → [학사일정] 수강신청 일정 [출처 3]\n", "결론:\n2026학년도 수강신청은 2월 10일부터입니다.")));
    }

    @Test
    @DisplayName("확인 줄 머리가 아니라고 가려지면 붙잡은 글부터 그대로 흘려, 이어 붙인 글이 원문과 같다")
    void passesAnswersWithoutWorkingHeader() {
        WorkingLineStreamFilter filter = new WorkingLineStreamFilter();
        assertEquals("", filter.accept("확인"));
        assertEquals("확인 결과 가나학과는", filter.accept(" 결과 가나학과는"));
        assertEquals("\n결론: 40명입니다.", filter.accept("\n결론: 40명입니다."));

        for (List<String> tokens : List.of(
                List.of("2026학년도 2학기 휴학 신청은 ", "8월 29일까지입니다.\n\n[출처 1]"),
                List.of("\n", "근", "거로 보면 휴학은 8월까지입니다."),
                List.of("결론: 휴학은 8월까지입니다."))) {
            assertEquals(String.join("", tokens), streamed(tokens));
        }
    }

    @Test
    @DisplayName("확인 줄로 시작했는데 결론 줄머리가 오지 않으면 아무것도 흘리지 않고, 끝날 때 붙잡은 원문을 내보낸다")
    void flushesWorkingLinesWithoutConclusion() {
        WorkingLineStreamFilter filter = new WorkingLineStreamFilter();

        assertEquals("", filter.accept("확인한 행:\n- 가나학과: 40명\n"));
        assertEquals("", filter.accept("- 다라학과: 35명"));
        assertEquals("확인한 행:\n- 가나학과: 40명\n- 다라학과: 35명", filter.flush());
    }

    @Test
    @DisplayName("답 머리가 아직 가려지지 않은 채 끝나면 붙잡은 글을 내보낸다")
    void flushesUndecidedHead() {
        WorkingLineStreamFilter filter = new WorkingLineStreamFilter();

        assertEquals("", filter.accept("고른"));
        assertEquals("고른", filter.flush());
    }

    private static String streamed(List<String> tokens) {
        WorkingLineStreamFilter filter = new WorkingLineStreamFilter();
        StringBuilder out = new StringBuilder();
        tokens.forEach(token -> out.append(filter.accept(token)));
        return out.append(filter.flush()).toString();
    }
}
