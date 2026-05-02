package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

// chat_messages 테이블 CRUD를 담당하는 JPA Repository
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {

    // 특정 세션에 속한 메시지를 시간순으로 조회. 세션 상세 조회 시 대화 흐름 재현에 사용
    List<ChatMessage> findByChatSessionIdOrderByCreatedAtAsc(Long sessionId);

    // 세션 삭제 전 해당 세션의 메시지를 일괄 삭제. derived delete는 N+1 DELETE가 발생하므로 JPQL 사용
    // @Modifying: DELETE 쿼리 실행을 허용
    @Modifying
    @Transactional
    @Query("DELETE FROM ChatMessage m WHERE m.chatSession.id = :sessionId")
    void deleteByChatSessionId(@Param("sessionId") Long sessionId);
}
