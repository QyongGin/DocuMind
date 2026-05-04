package com.documind.documind.domain.chat;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * SSE 스트리밍 콜백에서 발생하는 채팅 메시지 저장을 명시적 트랜잭션으로 처리한다.
 */
@Service
@RequiredArgsConstructor
public class ChatStreamPersistenceService {

    private final ChatMessageRepository chatMessageRepository;
    private final ChatSessionRepository chatSessionRepository;

    /**
     * 스트리밍 정상 완료 시 답변과 출처를 저장하고 세션의 마지막 활동 시각을 갱신한다.
     *
     * @param messageId 저장할 메시지 ID
     * @param sessionId 마지막 활동 시각을 갱신할 세션 ID
     * @param answer 완성된 LLM 답변
     * @param sourcesJson 답변 출처 JSON 문자열
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void completeMessage(Long messageId, Long sessionId, String answer, String sourcesJson) {
        chatMessageRepository.findById(messageId).ifPresent(message -> message.complete(answer, sourcesJson));
        chatSessionRepository.updateUpdatedAt(sessionId, LocalDateTime.now());
    }

    /**
     * 스트리밍이 비정상 종료됐을 때 현재까지 누적된 부분 답변을 저장한다.
     *
     * @param messageId 저장할 메시지 ID
     * @param partialAnswer 클라이언트 중단 전까지 수신한 답변 조각
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void savePartialAnswer(Long messageId, String partialAnswer) {
        chatMessageRepository.findById(messageId)
                .ifPresent(message -> message.complete(partialAnswer, "[]"));
    }
}
