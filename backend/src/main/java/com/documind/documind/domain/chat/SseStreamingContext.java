package com.documind.documind.domain.chat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;

/**
 * 단일 SSE 스트림의 상태와 FastAPI 이벤트 처리 로직을 캡슐화한다.
 */
@Slf4j
class SseStreamingContext {

    private final SseEmitter emitter;
    private final Long messageId;
    private final Long sessionId;
    private final ObjectMapper objectMapper;
    private final ChatStreamPersistenceService persistenceService;
    private final StringBuffer answerBuffer = new StringBuffer();
    private final Object persistenceLock = new Object();
    private boolean normallyCompleted;
    private boolean answerStored;
    private volatile Disposable subscription;

    SseStreamingContext(
            SseEmitter emitter,
            Long messageId,
            Long sessionId,
            ObjectMapper objectMapper,
            ChatStreamPersistenceService persistenceService
    ) {
        this.emitter = emitter;
        this.messageId = messageId;
        this.sessionId = sessionId;
        this.objectMapper = objectMapper;
        this.persistenceService = persistenceService;
    }

    // subscribe() 이후 반환되는 Disposable을 지연 주입해 클라이언트 중단 시 upstream 구독을 취소한다.
    void attachSubscription(Disposable subscription) {
        this.subscription = subscription;
    }

    // FastAPI SSE data JSON 한 건을 파싱해 token/done/error 이벤트별로 처리한다.
    void onToken(String jsonData) {
        try {
            JsonNode node = objectMapper.readTree(jsonData);
            if (node.has("token")) {
                handleTokenEvent(jsonData, node);
            } else if (node.has("done") && node.get("done").asBoolean()) {
                handleDoneEvent(jsonData, node);
            } else if (node.has("error")) {
                handleErrorEvent(jsonData, node);
            }
        } catch (Exception e) {
            log.error("SSE 토큰 처리 오류", e);
            emitter.completeWithError(e);
        }
    }

    // 클라이언트 연결 종료 시 FastAPI 구독을 취소하고 정상 완료 전이면 부분 답변을 저장한다.
    void onClientDisconnect() {
        disposeSubscription();
        synchronized (persistenceLock) {
            String partialAnswer = currentAnswer();
            if (!normallyCompleted && !answerStored && !partialAnswer.isEmpty()) {
                persistenceService.savePartialAnswer(messageId, partialAnswer);
                answerStored = true;
            }
        }
    }

    // Spring MVC SseEmitter timeout 시 FastAPI 구독을 취소한다.
    void onTimeout() {
        disposeSubscription();
    }

    // Spring MVC SseEmitter error 시 FastAPI 구독을 취소한다.
    void onEmitterError(Throwable error) {
        disposeSubscription();
    }

    // FastAPI 스트림 자체에서 오류가 발생하면 브라우저 SSE 연결도 오류로 종료한다.
    void onUpstreamError(Throwable error) {
        log.error("FastAPI 스트리밍 오류", error);
        emitter.completeWithError(error);
    }

    private void handleTokenEvent(String jsonData, JsonNode node) throws IOException {
        answerBuffer.append(node.get("token").asText());
        emitter.send(SseEmitter.event().data(jsonData));
    }

    private void handleDoneEvent(String jsonData, JsonNode node) throws IOException {
        String sourcesJson = node.has("sources")
                ? objectMapper.writeValueAsString(node.get("sources"))
                : "[]";
        String finalAnswer = node.has("answer")
                ? node.get("answer").asText()
                : currentAnswer();

        synchronized (persistenceLock) {
            if (answerStored) {
                return;
            }
            persistenceService.completeMessage(messageId, sessionId, finalAnswer, sourcesJson);
            answerStored = true;
            normallyCompleted = true;
        }
        emitter.send(SseEmitter.event().data(jsonData));
        emitter.complete();
    }

    private void handleErrorEvent(String jsonData, JsonNode node) throws IOException {
        log.error("FastAPI 오류 이벤트: {}", node.get("error").asText());
        emitter.send(SseEmitter.event().data(jsonData));
        emitter.complete();
    }

    private void disposeSubscription() {
        Disposable currentSubscription = subscription;
        if (currentSubscription != null && !currentSubscription.isDisposed()) {
            currentSubscription.dispose();
        }
    }

    private String currentAnswer() {
        synchronized (answerBuffer) {
            return answerBuffer.toString();
        }
    }
}
