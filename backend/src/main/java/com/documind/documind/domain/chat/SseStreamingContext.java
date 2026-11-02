package com.documind.documind.domain.chat;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 단일 SSE 스트림의 상태와 FastAPI 이벤트 처리 로직을 캡슐화한다.
 */
@Slf4j
class SseStreamingContext {

    static final String STREAM_ERROR_CODE = "STREAM_ERROR";
    static final String STREAM_ERROR_MESSAGE = "스트리밍 처리 중 오류가 발생했습니다.";
    static final String UPSTREAM_ERROR_CODE = "UPSTREAM_ERROR";
    static final String UPSTREAM_ERROR_MESSAGE = "요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.";

    private final SseEmitter emitter;
    private final Long messageId;
    private final Long sessionId;
    private final ObjectMapper objectMapper;
    private final ChatStreamPersistenceService persistenceService;
    private final ScreenAnswerMaker screenAnswerMaker;
    private final SourceDocumentMetadataEnricher sourceDocumentMetadataEnricher;
    private final StringBuffer answerBuffer = new StringBuffer();
    // 흐르는 답에서 출처 번호를 거른다(ADR-0051 결정 4). answerBuffer에는 모델 원문을 그대로 쌓는다
    private final CitationStreamFilter citationFilter = new CitationStreamFilter();
    private final Object persistenceLock = new Object();
    private boolean normallyCompleted;
    private boolean answerStored;
    private volatile Disposable subscription;

    SseStreamingContext(
            SseEmitter emitter,
            Long messageId,
            Long sessionId,
            ObjectMapper objectMapper,
            ChatStreamPersistenceService persistenceService,
            SourceDocumentMetadataEnricher sourceDocumentMetadataEnricher,
            ScreenAnswerMaker screenAnswerMaker
    ) {
        this.emitter = emitter;
        this.messageId = messageId;
        this.sessionId = sessionId;
        this.objectMapper = objectMapper;
        this.persistenceService = persistenceService;
        this.sourceDocumentMetadataEnricher = sourceDocumentMetadataEnricher;
        this.screenAnswerMaker = screenAnswerMaker;
    }

    /**
     * subscribe() 이후 반환되는 Disposable을 지연 주입해 클라이언트 중단 시 upstream 구독을 취소한다.
     *
     * @param subscription FastAPI SSE 스트림 구독 핸들
     */
    void attachSubscription(Disposable subscription) {
        this.subscription = subscription;
    }

    /**
     * FastAPI SSE data JSON 한 건을 파싱해 token/done/error 이벤트별로 처리한다.
     *
     * @param jsonData FastAPI가 보낸 SSE data JSON 문자열
     */
    void onToken(String jsonData) {
        JsonNode node;
        try {
            node = objectMapper.readTree(jsonData);
        } catch (JsonProcessingException e) {
            log.error("SSE 토큰 JSON 파싱 오류", e);
            sendSafeErrorAndComplete(STREAM_ERROR_CODE, STREAM_ERROR_MESSAGE);
            return;
        }

        try {
            if (node.has("token")) {
                handleTokenEvent(node);
            } else if (node.has("done") && node.get("done").asBoolean()) {
                handleDoneEvent(node);
            } else if (node.has("error")) {
                handleErrorEvent(jsonData, node);
            }
        } catch (JsonProcessingException e) {
            log.error("SSE 토큰 JSON 직렬화 오류", e);
            sendSafeErrorAndComplete(STREAM_ERROR_CODE, STREAM_ERROR_MESSAGE);
        } catch (IOException e) {
            handleEmitterSendFailure(e);
        } catch (Exception e) {
            log.error("SSE 토큰 처리 오류", e);
            sendSafeErrorAndComplete(STREAM_ERROR_CODE, STREAM_ERROR_MESSAGE);
        }
    }

    /**
     * 클라이언트 연결 종료 시 FastAPI 구독을 취소하고 정상 완료 전이면 부분 답변을 저장한다.
     */
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

    /**
     * Spring MVC SseEmitter timeout 시 FastAPI 구독을 취소한다.
     */
    void onTimeout() {
        disposeSubscription();
    }

    /**
     * Spring MVC SseEmitter error 시 FastAPI 구독을 취소한다.
     *
     * @param error emitter에서 발생한 오류
     */
    void onEmitterError(Throwable error) {
        disposeSubscription();
    }

    /**
     * FastAPI 스트림 자체에서 오류가 발생하면 안전한 오류 이벤트를 전송하고 스트림을 종료한다.
     *
     * @param error upstream 스트림 오류
     */
    void onUpstreamError(Throwable error) {
        log.error("FastAPI 스트리밍 오류", error);
        sendSafeErrorAndComplete(UPSTREAM_ERROR_CODE, UPSTREAM_ERROR_MESSAGE);
    }

    private void handleTokenEvent(JsonNode node) throws IOException {
        String token = node.get("token").asText();
        answerBuffer.append(token);
        String visible = citationFilter.accept(token);
        if (!visible.isEmpty()) {
            emitter.send(SseEmitter.event().data(objectMapper.writeValueAsString(Map.of("token", visible))));
        }
    }

    private void handleDoneEvent(JsonNode node) throws IOException {
        List<Map<String, Object>> enrichedSources = enrichDoneSources(node);
        String sourcesJson = objectMapper.writeValueAsString(enrichedSources);
        String rawAnswer = node.has("answer")
                ? node.get("answer").asText()
                : currentAnswer();
        // 화면용 답(ADR-0051): 출처 번호를 지우고 참고한 문서·안내를 만들어 done 이벤트에 담는다. 화면은 흐른 글을 이 답으로 바꾼다
        ScreenAnswer screenAnswer = screenAnswerMaker.make(rawAnswer, enrichedSources);
        String outboundJson = outboundDone(enrichedSources, screenAnswer);

        synchronized (persistenceLock) {
            if (answerStored) {
                return;
            }
            persistenceService.completeMessage(messageId, sessionId, screenAnswer.text(), rawAnswer, sourcesJson);
            answerStored = true;
            normallyCompleted = true;
        }
        saveTrace(node.get("trace"));
        emitter.send(SseEmitter.event().data(outboundJson));
        emitter.complete();
    }

    // 처리 기록(ADR-0052)은 답을 저장한 뒤 따로 저장한다. 실패해도 사용자에게 가는 답에는 영향을 주지 않는다
    private void saveTrace(JsonNode trace) {
        if (trace == null || !trace.isObject()) {
            return;
        }
        try {
            persistenceService.saveTrace(messageId, objectMapper.writeValueAsString(trace));
        } catch (Exception e) {
            log.warn("처리 기록 저장 실패. messageId={}", messageId, e);
        }
    }

    private List<Map<String, Object>> enrichDoneSources(JsonNode node) {
        if (!node.has("sources")) {
            return List.of();
        }
        List<Map<String, Object>> sources = objectMapper.convertValue(node.get("sources"), new TypeReference<>() {});
        return sourceDocumentMetadataEnricher.enrich(sources);
    }

    // 화면에 보낼 칸만 고른다. AI 서버가 보낸 처리 기록(trace) 같은 내부 정보는 브라우저로 보내지 않는다(ADR-0052)
    private String outboundDone(List<Map<String, Object>> sources, ScreenAnswer screenAnswer)
            throws JsonProcessingException {
        Map<String, Object> outbound = new LinkedHashMap<>();
        outbound.put("done", true);
        outbound.put("messageId", messageId);
        outbound.put("answer", screenAnswer.text());
        outbound.put("sources", sources);
        outbound.put("references", screenAnswer.references());
        outbound.put("guidance", screenAnswer.guidance());
        return objectMapper.writeValueAsString(outbound);
    }

    private void handleErrorEvent(String jsonData, JsonNode node) {
        log.error("FastAPI 오류 이벤트: {}", node.get("error").asText());
        sendSafeErrorAndComplete(UPSTREAM_ERROR_CODE, UPSTREAM_ERROR_MESSAGE);
    }

    private void handleEmitterSendFailure(IOException error) {
        log.warn("SSE 이벤트 전송 실패. 클라이언트 연결 종료로 보고 부분 답변 저장을 시도합니다.", error);
        onClientDisconnect();
        emitter.complete();
    }

    private void sendSafeErrorAndComplete(String code, String message) {
        disposeSubscription();
        persistSafeErrorAnswer(message);
        try {
            String payload = objectMapper.writeValueAsString(Map.of(
                    "type", "error",
                    "error", message,
                    "code", code,
                    "message", message
            ));
            emitter.send(SseEmitter.event().data(payload));
        } catch (Exception sendError) {
            log.error("SSE 안전 오류 이벤트 전송 실패", sendError);
        } finally {
            emitter.complete();
        }
    }

    private void persistSafeErrorAnswer(String message) {
        synchronized (persistenceLock) {
            if (!answerStored) {
                // 안전 오류 문장은 모델 원문이 아니지만 원문 칸도 같은 글로 둔다(기록을 다시 열 때 그대로 보인다)
                persistenceService.completeMessage(messageId, sessionId, message, message, "[]");
                answerStored = true;
            }
        }
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
