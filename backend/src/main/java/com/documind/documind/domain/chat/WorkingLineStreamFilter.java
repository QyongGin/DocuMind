package com.documind.documind.domain.chat;

/**
 * 흐르는 답에서 결론 앞의 확인 줄을 화면에 보내지 않는다({@link WorkingLines}, ADR-0050 변경 메모 2026-11-28).
 *
 * <p>첫 줄이 확인 줄인지 가려질 때까지 붙잡는다. 토큰은 줄머리 중간에서 끊겨 올 수 있다('확인', '한 행:').
 * 확인 줄이 아니라고 가려지면 붙잡은 글부터 그대로 흘린다. 확인 줄이면 결론 줄머리가 나올 때까지 모두 붙잡고, 그 뒤의 글부터
 * 흘린다(줄머리 바로 뒤의 공백은 뺀다). 출처 번호 거르기({@link CitationStreamFilter})는 이 필터를 지난 글에 한다.
 * 스트림 하나에 하나씩 쓰며 스레드 안전하지 않다.</p>
 */
class WorkingLineStreamFilter {

    private enum State {
        // 첫 줄이 확인 줄인지 아직 모른다
        DECIDING,
        // 확인 줄이다. 결론 줄머리를 기다린다
        HOLDING,
        // 결론 줄머리를 지났다. 결론 첫 글자 전의 공백을 뺀다
        CONCLUSION_START,
        // 그대로 흘린다
        PASSING
    }

    private final StringBuilder held = new StringBuilder();
    private State state = State.DECIDING;

    /**
     * 토큰 하나를 받아 지금 화면에 보내도 되는 글을 돌려준다.
     *
     * @param token 모델이 낸 토큰
     * @return 보낼 글. 붙잡아 둔 글이 있으면 빈 문자열일 수 있다
     */
    String accept(String token) {
        return switch (state) {
            case PASSING -> token;
            case CONCLUSION_START -> conclusionText(token);
            case DECIDING -> decide(token);
            case HOLDING -> hold(token);
        };
    }

    /**
     * 답이 끝날 때 붙잡아 둔 글을 모두 돌려준다. 확인 줄로 시작했는데 결론 줄머리가 오지 않은 답이면 그 원문이다.
     *
     * @return 남은 글
     */
    String flush() {
        String rest = held.toString();
        held.setLength(0);
        state = State.PASSING;
        return rest;
    }

    // 첫 줄머리를 가린다. 확인 줄 머리의 앞부분일 수 있는 동안은 붙잡는다
    private String decide(String token) {
        held.append(token);
        if (WorkingLines.startsWithWorkingHeader(held)) {
            state = State.HOLDING;
            return hold("");
        }
        if (WorkingLines.mayBecomeWorkingHeader(held)) {
            return "";
        }
        state = State.PASSING;
        return flush();
    }

    // 결론 줄머리가 나올 때까지 붙잡고, 나오면 그 앞을 버리고 뒤의 글을 흘린다
    private String hold(String token) {
        held.append(token);
        int start = WorkingLines.conclusionStart(held);
        if (start < 0) {
            return "";
        }
        String rest = held.substring(start);
        held.setLength(0);
        state = State.CONCLUSION_START;
        return conclusionText(rest);
    }

    // 결론 줄머리 바로 뒤의 공백을 빼고, 첫 글자가 나오면 그대로 흘린다
    private String conclusionText(String text) {
        String visible = text.stripLeading();
        if (!visible.isEmpty()) {
            state = State.PASSING;
        }
        return visible;
    }
}
