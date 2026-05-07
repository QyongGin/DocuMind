package com.documind.documind.domain.chat;

import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * SSE 스트리밍 질의응답 시작에 필요한 입력값 묶음.
 * 메서드 인자 수를 줄이고 로그인 사용자와 비로그인 세션 식별 정보를 함께 전달한다.
 */
record ChatStreamCommand(
        String question,
        Long userId,
        String sessionKey,
        Integer topK,
        SseEmitter emitter
) {
}
