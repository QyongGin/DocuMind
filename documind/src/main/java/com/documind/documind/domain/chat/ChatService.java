package com.documind.documind.domain.chat;

import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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
        ChatSession session = resolveSession(request);

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

    // sessionKey로 기존 세션을 찾거나, 없으면 새 세션을 생성해 반환
    private ChatSession resolveSession(ChatRequest request) {
        if (request.getSessionKey() != null) {
            return chatSessionRepository.findBySessionKey(request.getSessionKey())
                    .orElseGet(() -> createSession(request));
        }
        return createSession(request);
    }

    // 새 채팅 세션 생성. 제목은 첫 질문 앞 50자로 설정
    private ChatSession createSession(ChatRequest request) {
        String title = request.getQuestion().length() > 50
                ? request.getQuestion().substring(0, 50)
                : request.getQuestion();
        ChatSession session = ChatSession.create(null, request.getSessionKey(), title);
        return chatSessionRepository.save(session);
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
}
