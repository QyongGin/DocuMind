package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/** chat_message_traces 테이블(처리 기록, ADR-0052)을 다루는 JPA Repository */
public interface ChatMessageTraceRepository extends JpaRepository<ChatMessageTrace, Long> {

    /**
     * 저장 시각이 기준보다 앞선 처리 기록을 JPQL로 일괄 삭제한다. 보관 기간이 지난 기록을 지우는 데 쓴다.
     *
     * @return 지운 기록 수
     */
    @Modifying(clearAutomatically = true)
    @Transactional
    @Query("DELETE FROM ChatMessageTrace t WHERE t.createdAt < :cutoff")
    int deleteCreatedBefore(@Param("cutoff") LocalDateTime cutoff);

    /**
     * 세션 삭제 전 그 세션 답들의 처리 기록을 먼저 삭제한다.
     * chat_message_traces.message_id FK가 chat_messages.id를 참조하므로 메시지 bulk delete 전에 필요하다.
     */
    @Modifying(clearAutomatically = true)
    @Transactional
    @Query("DELETE FROM ChatMessageTrace t WHERE t.messageId IN "
            + "(SELECT m.id FROM ChatMessage m WHERE m.chatSession.id = :sessionId)")
    void deleteByChatSessionId(@Param("sessionId") Long sessionId);
}
