package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

/** chat_feedback 테이블 CRUD를 담당하는 JPA Repository */
public interface ChatFeedbackRepository extends JpaRepository<ChatFeedback, Long> {

    /** 메시지 ID로 기존 피드백을 조회한다. 피드백 수정 시 upsert 판단에 사용한다. */
    Optional<ChatFeedback> findByChatMessageId(Long messageId);

    /** 여러 메시지 ID에 대한 피드백을 한 번에 조회한다. 세션 상세 응답 생성에 사용한다. */
    List<ChatFeedback> findByChatMessageIdIn(Collection<Long> messageIds);

    /**
     * 세션 삭제 전 해당 세션 메시지에 연결된 피드백을 먼저 삭제한다.
     * chat_feedback.message_id FK가 chat_messages.id를 참조하므로 메시지 bulk delete 전에 필요하다.
     */
    @Modifying(clearAutomatically = true)
    @Transactional
    @Query("DELETE FROM ChatFeedback f WHERE f.chatMessage.chatSession.id = :sessionId")
    void deleteByChatSessionId(@Param("sessionId") Long sessionId);
}
