package com.documind.documind.domain.chat;

import java.util.List;
import java.util.Optional;

/**
 * 모델 원문 답의 확인 줄과 결론 줄 약속(docs/project/챗봇-답변-형식.md §2·§3, ADR-0050 변경 메모 2026-11-28).
 *
 * <p>표 읽기를 학습한 모델은 표에서 여러 행을 골라야 하는 질문에 답할 때 결론 앞에 확인 줄을 먼저 쓴다.
 * 답이 확인 줄 머리({@link #WORKING_HEADERS}) 중 하나로 시작하고 그 뒤 어떤 줄이 {@link #CONCLUSION_HEADER}로
 * 시작하면, 화면에는 그 줄머리 뒤의 글만 보인다. 완성된 답({@link ScreenAnswerMaker})과 흐르는 답
 * ({@link WorkingLineStreamFilter})이 같은 약속을 쓴다. 줄머리를 바꾸려면 학습 데이터와 채점의 결론 나누기도 함께 고친다.</p>
 */
final class WorkingLines {

    /** 결론 앞에 오는 확인 줄의 첫 줄머리. 답의 첫 줄(앞 공백 무시)이 이 중 하나로 시작해야 확인 줄로 본다. */
    static final List<String> WORKING_HEADERS = List.of("확인한 행:", "근거 글:", "고른 표:");
    /** 결론 줄의 줄머리. 확인 줄 뒤의 줄 맨 앞에 있어야 한다. */
    static final String CONCLUSION_HEADER = "결론:";

    // 결론 줄은 줄 맨 앞에 와야 한다. 첫 줄은 확인 줄 머리이므로 결론 줄은 늘 줄바꿈 뒤에 있다
    private static final String CONCLUSION_LINE = "\n" + CONCLUSION_HEADER;

    private WorkingLines() {
    }

    /**
     * 답(또는 지금까지 흐른 답)이 확인 줄 머리로 시작하는지 본다. 앞의 공백과 빈 줄은 무시한다.
     *
     * @param text 모델 원문 답
     * @return 확인 줄 머리로 시작하면 true
     */
    static boolean startsWithWorkingHeader(CharSequence text) {
        String head = text.toString().stripLeading();
        return WORKING_HEADERS.stream().anyMatch(head::startsWith);
    }

    /**
     * 지금까지 흐른 답의 머리가 확인 줄 머리의 앞부분일 수 있는지 본다(토큰이 '확인', '한 행:'처럼 잘려 올 때).
     * 앞의 공백만 왔으면 아직 가릴 수 없으므로 true다.
     *
     * @param text 지금까지 흐른 답
     * @return 확인 줄 머리가 될 수 있어 더 기다려야 하면 true
     */
    static boolean mayBecomeWorkingHeader(CharSequence text) {
        String head = text.toString().stripLeading();
        return WORKING_HEADERS.stream().anyMatch(header -> header.startsWith(head));
    }

    /**
     * 결론 줄머리 바로 뒤의 자리를 찾는다.
     *
     * @param text 확인 줄 머리로 시작하는 답
     * @return 결론 줄머리 뒤 첫 글자의 자리. 결론 줄이 없으면 -1
     */
    static int conclusionStart(CharSequence text) {
        int line = text.toString().indexOf(CONCLUSION_LINE);
        return line < 0 ? -1 : line + CONCLUSION_LINE.length();
    }

    /**
     * 확인 줄로 시작하고 결론 줄이 있는 답이면 결론 줄머리 뒤의 글을 돌려준다.
     *
     * @param rawAnswer 모델 원문 답
     * @return 결론 줄머리 뒤의 글(앞 공백을 지운 것). 확인 줄로 시작하지 않거나 결론 줄이 없으면 비어 있다
     */
    static Optional<String> conclusionOf(String rawAnswer) {
        if (!startsWithWorkingHeader(rawAnswer)) {
            return Optional.empty();
        }
        int start = conclusionStart(rawAnswer);
        return start < 0 ? Optional.empty() : Optional.of(rawAnswer.substring(start).stripLeading());
    }
}
