package com.documind.documind.domain.chat;

import com.documind.documind.domain.auth.User;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 질의응답 비즈니스 로직.
 * 세션 관리, FastAPI 호출, 메시지 저장, 채팅 이력 조회와 삭제를 담당한다.
 */
// @RequiredArgsConstructor: final 필드를 인자로 받는 생성자를 자동 생성 (Lombok)
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatService {

    private final ChatSessionRepository chatSessionRepository;
    private final ChatMessageRepository chatMessageRepository;
    private final ChatStreamPersistenceService chatStreamPersistenceService;
    private final FastApiClient fastApiClient;
    private final EntityManager entityManager;
    // Spring Boot가 자동 설정한 ObjectMapper 빈을 주입해 Jackson 전역 설정을 공유
    private final ObjectMapper objectMapper;

    // 기본 Top-K 값. FastAPI 기본값과 동기화
    private static final int DEFAULT_TOP_K = 5;

    /**
     * 일반 질의응답을 처리하고 질문·답변·출처를 채팅 이력에 저장한다.
     *
     * @param request 질문, 비로그인 세션 키, 검색 Top-K를 포함한 요청
     * @param userId 로그인 사용자 ID. null이면 sessionKey 기반 비로그인 세션으로 저장한다.
     * @return FastAPI 답변과 출처를 포함한 채팅 응답
     */
    @Transactional
    public ChatResponse chat(ChatRequest request, Long userId) {
        // 1. 세션 조회 또는 신규 생성
        // 로그인 사용자는 userId 소유 세션을 새로 만들고, 비로그인은 sessionKey 기준 세션을 재사용한다.
        ChatSession session = getOrCreateSession(request.getQuestion(), userId, request.getSessionKey());

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

        // 6. 세션의 마지막 활동 시각 갱신. 사이드바 목록의 최신 활동 순 정렬에 사용
        chatSessionRepository.updateUpdatedAt(session.getId(), LocalDateTime.now());

        return ChatResponse.builder()
                .sessionId(session.getId())
                .messageId(message.getId())
                .answer(fastApiResponse.getAnswer())
                .sources(fastApiResponse.getSources())
                .build();
    }

    /**
     * 세션 목록을 조회한다.
     * 로그인 사용자는 userId 기반 전체 목록, 비로그인은 sessionKey 기반 단일 세션을 반환한다.
     */
    @Transactional(readOnly = true)
    public List<ChatSessionSummaryResponse> getSessions(Long userId, String sessionKey) {
        List<ChatSession> sessions;
        if (userId != null) {
            sessions = chatSessionRepository.findByUserIdOrderByUpdatedAtDesc(userId);
        } else if (sessionKey != null) {
            // 비로그인은 sessionKey가 unique이므로 최대 1개. List 형식으로 통일해 클라이언트 처리 단순화
            sessions = chatSessionRepository.findBySessionKey(sessionKey)
                    .map(List::of)
                    .orElse(List.of());
        } else {
            return List.of();
        }
        return sessions.stream()
                .map(s -> ChatSessionSummaryResponse.builder()
                        .sessionId(s.getId())
                        .title(s.getTitle())
                        .createdAt(s.getCreatedAt())
                        .updatedAt(s.getUpdatedAt())
                        .build())
                .toList();
    }

    /**
     * 세션 상세 정보와 시간순 메시지 목록을 조회한다.
     * 소유권 검증 실패 시 세션 존재 여부를 노출하지 않도록 404로 처리한다.
     */
    @Transactional(readOnly = true)
    public ChatSessionDetailResponse getSessionDetail(Long sessionId, Long userId, String sessionKey) {
        ChatSession session = resolveSession(sessionId, userId, sessionKey);

        List<ChatMessageResponse> messageResponses = chatMessageRepository
                .findByChatSessionIdOrderByCreatedAtAsc(sessionId)
                .stream()
                .map(m -> ChatMessageResponse.builder()
                        .messageId(m.getId())
                        .question(m.getQuestion())
                        .answer(m.getAnswer())
                        .sources(deserializeSources(m.getSourceDocs()))
                        .createdAt(m.getCreatedAt())
                        .build())
                .toList();

        return ChatSessionDetailResponse.builder()
                .sessionId(session.getId())
                .title(session.getTitle())
                .createdAt(session.getCreatedAt())
                .messages(messageResponses)
                .build();
    }

    /**
     * 세션과 소속 메시지를 삭제한다.
     * FK 위반을 피하기 위해 메시지를 먼저 지우고 세션을 지운다.
     */
    @Transactional
    public void deleteSession(Long sessionId, Long userId, String sessionKey) {
        resolveSession(sessionId, userId, sessionKey);
        chatMessageRepository.deleteByChatSessionId(sessionId);
        chatSessionRepository.deleteById(sessionId);
    }

    // sessionId + (userId 또는 sessionKey)로 소유권을 검증하고 세션을 반환.
    // 세션 존재 여부 노출을 막기 위해 소유권 불일치도 CHAT_SESSION_NOT_FOUND로 처리한다.
    private ChatSession resolveSession(Long sessionId, Long userId, String sessionKey) {
        if (userId != null) {
            return chatSessionRepository.findByIdAndUserId(sessionId, userId)
                    .orElseThrow(() -> new CustomException(ErrorCode.CHAT_SESSION_NOT_FOUND));
        }
        if (sessionKey != null) {
            return chatSessionRepository.findByIdAndSessionKey(sessionId, sessionKey)
                    .orElseThrow(() -> new CustomException(ErrorCode.CHAT_SESSION_NOT_FOUND));
        }
        throw new CustomException(ErrorCode.CHAT_SESSION_NOT_FOUND);
    }

    // sourceDocs JSON 문자열을 역직렬화. null이거나 파싱 실패 시 빈 리스트로 폴백
    private List<Map<String, Object>> deserializeSources(String sourceDocs) {
        if (sourceDocs == null || sourceDocs.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(sourceDocs, new TypeReference<>() {});
        } catch (JsonProcessingException e) {
            log.error("sourceDocs 역직렬화 실패. 빈 리스트로 폴백합니다.", e);
            return List.of();
        }
    }

    // 로그인 사용자는 질문마다 새 세션을 만든다. 현재 프론트는 기존 세션에 후속 질문을 붙이는 sessionId를 보내지 않는다.
    // 비로그인 사용자는 sessionKey로 기존 세션을 찾거나, 없으면 새 세션을 생성해 반환한다.
    // 동일 sessionKey 동시 요청 시 unique 충돌이 발생할 수 있으므로
    // DataIntegrityViolationException을 잡아 먼저 저장된 세션을 재조회한다.
    private ChatSession getOrCreateSession(String question, Long userId, String sessionKey) {
        if (userId != null) {
            String title = question.length() > 50 ? question.substring(0, 50) : question;
            User user = entityManager.getReference(User.class, userId);
            return chatSessionRepository.save(ChatSession.create(user, null, title));
        }

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

    /**
     * SSE 스트리밍 질의응답을 시작한다.
     *
     * @param command 사용자 질문, 소유자 식별 정보, 검색 개수, SSE emitter를 담은 요청 객체
     */
    public void streamChat(ChatStreamCommand command) {
        int resolvedTopK = command.topK() != null ? command.topK() : DEFAULT_TOP_K;

        ChatSession session = getOrCreateSession(command.question(), command.userId(), command.sessionKey());
        ChatMessage message = ChatMessage.create(session, command.question());
        chatMessageRepository.save(message);

        SseStreamingContext context = new SseStreamingContext(
                command.emitter(),
                message.getId(),
                session.getId(),
                objectMapper,
                chatStreamPersistenceService
        );

        command.emitter().onCompletion(context::onClientDisconnect);
        command.emitter().onTimeout(context::onTimeout);
        command.emitter().onError(context::onEmitterError);

        try {
            Disposable subscription = fastApiClient.streamQuery(command.question(), resolvedTopK)
                    .subscribe(context::onToken, context::onUpstreamError);
            context.attachSubscription(subscription);
        } catch (Exception e) {
            context.onUpstreamError(e);
        }
    }
}
