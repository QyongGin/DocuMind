package com.documind.documind.domain.chat;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 흐르는 답에서 출처 번호({@code [출처 N]})를 걸러 화면에 보내지 않는다(ADR-0051 결정 4).
 *
 * <p>토큰은 출처 번호 중간에서 끊겨 올 수 있다('…입니다.\n\n[', '출처', ' 1]'). '['부터는 출처 번호가 될 수 있는 동안 붙잡아
 * 두고, 출처 번호로 끝나면 버리고, 아니라고 판가름 나면 그대로 보낸다. 출처 번호 앞의 빈 줄은 남지만 답이 끝날 때 화면용 답
 * ({@link ScreenAnswerMaker})으로 바뀐다. 스트림 하나에 하나씩 쓰며 스레드 안전하지 않다.</p>
 */
class CitationStreamFilter {

    private static final Pattern CITATION = Pattern.compile(ScreenAnswerMaker.CITATION_TEXT);
    // 출처 번호가 될 수 있어도 이보다 길게 붙잡지 않는다(끝나지 않는 '['로 글이 멈추지 않게)
    private static final int MAX_HELD = 40;

    private final StringBuilder held = new StringBuilder();

    /**
     * 토큰 하나를 받아 지금 화면에 보내도 되는 글을 돌려준다.
     *
     * @param token 모델이 낸 토큰
     * @return 보낼 글. 붙잡아 둔 글이 있으면 빈 문자열일 수 있다
     */
    String accept(String token) {
        held.append(token);
        StringBuilder out = new StringBuilder();
        while (!held.isEmpty()) {
            int open = held.indexOf("[");
            if (open < 0) {
                out.append(held);
                held.setLength(0);
                break;
            }
            out.append(held, 0, open);
            held.delete(0, open);
            Matcher matcher = CITATION.matcher(held);
            if (matcher.lookingAt()) {
                held.delete(0, matcher.end());
            } else if (matcher.hitEnd() && held.length() <= MAX_HELD) {
                break;
            } else {
                out.append('[');
                held.deleteCharAt(0);
            }
        }
        return out.toString();
    }

    /**
     * 붙잡아 둔 글을 모두 돌려준다(끝나지 않은 출처 번호처럼 보이던 글).
     *
     * @return 남은 글
     */
    String flush() {
        String rest = held.toString();
        held.setLength(0);
        return rest;
    }
}
