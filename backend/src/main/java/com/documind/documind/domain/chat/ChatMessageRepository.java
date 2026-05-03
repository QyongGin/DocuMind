package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/** chat_messages 테이블 CRUD를 담당하는 JPA Repository */
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {

    /** 특정 세션에 속한 메시지를 시간순으로 조회한다. 세션 상세 조회 시 대화 흐름 재현에 사용한다. */
    List<ChatMessage> findByChatSessionIdOrderByCreatedAtAsc(Long sessionId);

    /**
     * 세션의 메시지를 JPQL로 일괄 삭제한다.
     * derived delete는 SELECT 후 하나씩 remove()를 호출하는 N+1 DELETE가 발생하므로 JPQL을 직접 작성한다.
     * clearAutomatically: bulk DELETE 후 1차 캐시에 잔류하는 삭제된 엔티티를 제거해 이후 조회가 올바른 결과를 반환하도록 보장한다.
     */
    @Modifying(clearAutomatically = true)
    @Transactional
    @Query("DELETE FROM ChatMessage m WHERE m.chatSession.id = :sessionId")
    void deleteByChatSessionId(@Param("sessionId") Long sessionId);
}
