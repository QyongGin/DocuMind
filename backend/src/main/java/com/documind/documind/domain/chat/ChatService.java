package com.documind.documind.domain.chat;

import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;

// 질의응답 비즈니스 로직. 세션 관리 → FastAPI 호출 → 메시지 저장을 담당
// @RequiredArgsConstructor: final 필드를 인자로 받는 생성자를 자동 생성 (Lombok)
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatService {

    private final ChatSessionRepository chatSessionRepository;
    private final ChatMessageRepository chatMessageRepository;
    private final FastApiClient fastApiClient;
    // Spring Boot가 자동 설정한 ObjectMapper 빈을 주입해 Jackson 전역 설정을 공유
    private final ObjectMapper objectMapper;

    // 기본 Top-K 값. FastAPI 기본값과 동기화
    private static final int DEFAULT_TOP_K = 5;

    @Transactional
    public ChatResponse chat(ChatRequest request) {
        // 1. 세션 조회 또는 신규 생성
        // sessionKey가 있으면 기존 세션 재사용, 없거나 DB에 없으면 새 세션 생성
        ChatSession session = getOrCreateSession(request.getQuestion(), request.getSessionKey());

        // 2. 메시지를 question만 먼저 저장 (answer는 LLM 응답 후 채움)
        ChatMessage message = ChatMessage.create(session, request.getQuestion());
        chatMessageRepository.save(message);

        // 3. FastAPI RAG 파이프라인 호출
        int topK = request.getTopK() != null ? request.getTopK() : DEFAULT_TOP_K;
        FastApiQueryResponse fastApiResponse = fastApiClient.query(request.getQuestion(), topK);

        // 4. sources 리스트를 JSON 문자열로 직렬화해 chat_messages.source_docs에 저장
        String sourceDocsJson = serializeSources(fastApiResponse);

        // 5. 메시지에 answer와 sourceDocs를 채움. @Transactional dirty checking으로 자동 UPDATE
        message.complete(fastApiResponse.getAnswer(), sourceDocsJson);

        return ChatResponse.builder()
                .sessionId(session.getId())
                .messageId(message.getId())
                .answer(fastApiResponse.getAnswer())
                .sources(fastApiResponse.getSources())
                .build();
    }

    // sessionKey로 기존 세션을 찾거나, 없으면 새 세션을 생성해 반환.
    // 동일 sessionKey 동시 요청 시 unique 충돌이 발생할 수 있으므로
    // DataIntegrityViolationException을 잡아 먼저 저장된 세션을 재조회한다.
    private ChatSession getOrCreateSession(String question, String sessionKey) {
        if (sessionKey != null) {
            Optional<ChatSession> existing = chatSessionRepository.findBySessionKey(sessionKey);
            if (existing.isPresent()) {
                return existing.get();
            }
        }
        String title = question.length() > 50 ? question.substring(0, 50) : question;
        try {
            return chatSessionRepository.save(ChatSession.create(null, sessionKey, title));
        } catch (DataIntegrityViolationException e) {
            // 동일 sessionKey로 동시 요청이 INSERT를 시도한 경우 먼저 저장된 세션을 반환
            return chatSessionRepository.findBySessionKey(sessionKey)
                    .orElseThrow(() -> e);
        }
    }

    // sources 리스트를 JSON 문자열로 변환. 직렬화 실패 시 빈 배열 문자열로 폴백
    private String serializeSources(FastApiQueryResponse response) {
        if (response.getSources() == null) {
            return "[]";
        }
        try {
            return objectMapper.writeValueAsString(response.getSources());
        } catch (JsonProcessingException e) {
            log.error("sources 직렬화 실패. 빈 배열로 폴백합니다.", e);
            return "[]";
        }
    }

    // SSE 스트리밍 질의응답.
    // 1) 세션 생성·조회 → 메시지(question만) DB 저장
    // 2) FastAPI /query/stream 구독 → 토큰마다 SseEmitter로 forwarding
    // 3) done 이벤트 수신 시 answer + sources를 DB에 저장 후 emitter 완료
    // 4) 클라이언트 연결 종료(EventSource.close()) 시 onCompletion 콜백으로 구독 취소
    public void streamChat(String question, String sessionKey, Integer topK, SseEmitter emitter) {
        int resolvedTopK = topK != null ? topK : DEFAULT_TOP_K;

        // 세션 조회 또는 생성
        ChatSession session = getOrCreateSession(question, sessionKey);

        // question만 먼저 저장. answer는 스트리밍 완료 후 채움
        ChatMessage message = ChatMessage.create(session, question);
        chatMessageRepository.save(message);
        Long messageId = message.getId();

        // StringBuffer: onCompletion(서블릿 스레드)과 forwardToken(Reactor 스레드)이 동시 접근 가능
        StringBuffer answerBuffer = new StringBuffer();
        // done 이벤트 수신 여부로 정상 완료와 중단을 구분. onCompletion은 두 케이스 모두에서 호출됨
        AtomicBoolean normallyCompleted = new AtomicBoolean(false);

        Disposable subscription = fastApiClient.streamQuery(question, resolvedTopK)
                .subscribe(
                        jsonData -> {
                            try {
                                forwardToken(jsonData, messageId, answerBuffer, emitter, normallyCompleted);
                            } catch (Exception e) {
                                log.error("SSE 토큰 전송 오류", e);
                                emitter.completeWithError(e);
                            }
                        },
                        error -> {
                            log.error("FastAPI 스트리밍 오류", error);
                            emitter.completeWithError(error);
                        }
                );

        // 클라이언트 연결 종료·타임아웃 시:
        // 1) FastAPI 구독 취소 (GPU 연산 중단)
        // 2) 정상 완료가 아닌 경우에만 answerBuffer의 부분 답변을 DB에 저장
        emitter.onCompletion(() -> {
            subscription.dispose();
            if (!normallyCompleted.get() && answerBuffer.length() > 0) {
                chatMessageRepository.findById(messageId).ifPresent(m -> {
                    m.complete(answerBuffer.toString(), "[]");
                    chatMessageRepository.save(m);
                });
            }
        });
        emitter.onTimeout(subscription::dispose);
        emitter.onError(t -> subscription.dispose());
    }

    // SSE data JSON을 파싱해 token이면 emitter에 forwarding, done이면 DB 저장 후 완료
    private void forwardToken(String jsonData, Long messageId, StringBuffer answerBuffer, SseEmitter emitter, AtomicBoolean normallyCompleted) throws IOException {
        JsonNode node = objectMapper.readTree(jsonData);

        if (node.has("token")) {
            answerBuffer.append(node.get("token").asText());
            // 원본 JSON을 그대로 전달해 React에서 추가 파싱 없이 사용 가능하도록 함
            emitter.send(SseEmitter.event().data(jsonData));
        } else if (node.has("done") && node.get("done").asBoolean()) {
            String sourcesJson = node.has("sources")
                    ? objectMapper.writeValueAsString(node.get("sources"))
                    : "[]";

            // done 이벤트에 answer가 직접 포함된 경우(빈 문서) answerBuffer 대신 사용
            String finalAnswer = node.has("answer")
                    ? node.get("answer").asText()
                    : answerBuffer.toString();

            // DB에 완성된 answer + sources 저장
            chatMessageRepository.findById(messageId).ifPresent(m -> {
                m.complete(finalAnswer, sourcesJson);
                chatMessageRepository.save(m);
            });

            emitter.send(SseEmitter.event().data(jsonData));
            // DB 저장과 SSE 전송이 모두 성공한 뒤에만 정상 완료로 표시.
            // 이전에 이 플래그를 먼저 올리면 그 사이 예외 발생 시 onCompletion 폴백이 건너뛰어진다.
            normallyCompleted.set(true);
            emitter.complete();
        } else if (node.has("error")) {
            log.error("FastAPI 오류 이벤트: {}", node.get("error").asText());
            emitter.send(SseEmitter.event().data(jsonData));
            emitter.complete();
        }
    }
}
