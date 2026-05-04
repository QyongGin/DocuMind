package com.documind.documind.domain.chat;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * SSE 스트림 상태 객체의 완료·중단 저장 흐름을 검증하는 단위 테스트.
 */
class SseStreamingContextTest {

    private static final Long MESSAGE_ID = 1L;
    private static final Long SESSION_ID = 10L;

    private final SseEmitter emitter = mock(SseEmitter.class);
    private final ChatStreamPersistenceService persistenceService = mock(ChatStreamPersistenceService.class);
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    @DisplayName("done 이벤트 수신 시 완성 답변을 저장하고 이후 연결 종료에서는 부분 답변을 저장하지 않음")
    void onToken_withDoneEvent_savesFinalAnswerOnly() {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"안녕\"}");
        context.onToken("{\"token\":\"하세요\"}");
        context.onToken("{\"done\":true,\"sources\":[{\"source\":\"guide.pdf\"}]}");
        context.onClientDisconnect();

        verify(persistenceService).completeMessage(
                eq(MESSAGE_ID),
                eq(SESSION_ID),
                eq("안녕하세요"),
                eq("[{\"source\":\"guide.pdf\"}]")
        );
        verify(persistenceService, never()).savePartialAnswer(any(), any());
    }

    @Test
    @DisplayName("클라이언트 연결 종료 시 FastAPI 구독을 취소하고 누적된 부분 답변을 저장함")
    void onClientDisconnect_savesPartialAnswerAndDisposesSubscription() {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);

        context.onToken("{\"token\":\"부분\"}");
        context.onToken("{\"token\":\"답변\"}");
        context.onClientDisconnect();

        verify(subscription).dispose();
        verify(persistenceService).savePartialAnswer(MESSAGE_ID, "부분답변");
        verify(persistenceService, never()).completeMessage(any(), any(), any(), any());
    }

    @Test
    @DisplayName("done 이벤트에 answer가 포함되면 누적 버퍼보다 answer 값을 우선 저장함")
    void onToken_withDoneAnswer_usesAnswerField() {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"검색\"}");
        context.onToken("{\"done\":true,\"answer\":\"검색 결과가 없습니다.\",\"sources\":[]}");

        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                "검색 결과가 없습니다.",
                "[]"
        );
    }

    @Test
    @DisplayName("upstream 오류 발생 시 안전 오류 답변을 저장하고 스트림을 종료함")
    void onUpstreamError_savesSafeErrorAnswerAndDisposesSubscription() throws Exception {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);

        context.onUpstreamError(new RuntimeException("boom"));

        verify(subscription).dispose();
        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                SseStreamingContext.UPSTREAM_ERROR_MESSAGE,
                "[]"
        );
        verify(persistenceService, never()).savePartialAnswer(any(), any());
        verify(emitter).send(any(SseEmitter.SseEventBuilder.class));
        verify(emitter).complete();
    }

    @Test
    @DisplayName("깨진 JSON 수신 시 안전 오류 답변을 저장하고 스트림을 종료함")
    void onToken_withMalformedJson_savesSafeErrorAnswerAndDisposesSubscription() throws Exception {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);

        context.onToken("{bad json");

        verify(subscription).dispose();
        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                SseStreamingContext.STREAM_ERROR_MESSAGE,
                "[]"
        );
        verify(persistenceService, never()).savePartialAnswer(any(), any());
        verify(emitter).send(any(SseEmitter.SseEventBuilder.class));
        verify(emitter).complete();
    }

    private SseStreamingContext createContext() {
        return new SseStreamingContext(
                emitter,
                MESSAGE_ID,
                SESSION_ID,
                objectMapper,
                persistenceService
        );
    }
}
