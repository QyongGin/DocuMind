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
    private final ChatMessageTraceRepository chatMessageTraceRepository;

    /**
     * 스트리밍 정상 완료 시 답변과 출처를 저장하고 세션의 마지막 활동 시각을 갱신한다.
     *
     * @param messageId 저장할 메시지 ID
     * @param sessionId 마지막 활동 시각을 갱신할 세션 ID
     * @param answer 화면용 답(출처 번호를 지운 것)
     * @param rawAnswer 모델 원문 답(출처 번호 포함)
     * @param sourcesJson 답변 출처 JSON 문자열
     * @param refused 거절 문장만 나간 답인지(관리자 '못 답한 질문')
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void completeMessage(Long messageId, Long sessionId, String answer, String rawAnswer, String sourcesJson,
                                boolean refused) {
        chatMessageRepository.findById(messageId)
                .ifPresent(message -> message.complete(answer, rawAnswer, sourcesJson, refused));
        chatSessionRepository.updateUpdatedAt(sessionId, LocalDateTime.now());
    }

    /**
     * 답의 처리 기록(ADR-0052)을 저장한다. 답 저장과 다른 트랜잭션이라 기록 저장이 실패해도 답은 남는다.
     *
     * @param messageId 기록이 속한 답. completeMessage로 먼저 저장(커밋)돼 있어야 한다
     * @param traceJson AI 서버가 보낸 처리 기록 JSON
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void saveTrace(Long messageId, String traceJson) {
        chatMessageTraceRepository.save(ChatMessageTrace.of(messageId, traceJson, LocalDateTime.now()));
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
