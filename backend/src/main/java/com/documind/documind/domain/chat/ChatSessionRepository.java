package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/** chat_sessions 테이블 CRUD를 담당하는 JPA Repository */
public interface ChatSessionRepository extends JpaRepository<ChatSession, Long> {

    /** 비로그인 사용자의 sessionKey로 기존 세션을 조회한다. */
    Optional<ChatSession> findBySessionKey(String sessionKey);

    /** 로그인 사용자의 모든 세션을 최신 활동 순으로 조회한다. 사이드바 목록에 사용한다. */
    @Query("SELECT s FROM ChatSession s WHERE s.user.id = :userId ORDER BY s.updatedAt DESC")
    List<ChatSession> findByUserIdOrderByUpdatedAtDesc(@Param("userId") Long userId);

    /** sessionId + userId로 소유권을 검증하며 세션을 조회한다. 로그인 사용자의 상세 조회·삭제에 사용한다. */
    @Query("SELECT s FROM ChatSession s WHERE s.id = :id AND s.user.id = :userId")
    Optional<ChatSession> findByIdAndUserId(@Param("id") Long id, @Param("userId") Long userId);

    /** sessionId + sessionKey로 소유권을 검증하며 세션을 조회한다. 비로그인 사용자의 상세 조회·삭제에 사용한다. */
    @Query("SELECT s FROM ChatSession s WHERE s.id = :id AND s.sessionKey = :sessionKey")
    Optional<ChatSession> findByIdAndSessionKey(@Param("id") Long id, @Param("sessionKey") String sessionKey);

    /**
     * 메시지 저장 완료 시 세션의 마지막 활동 시각을 갱신한다. 사이드바 최신 활동 순 정렬 기준으로 사용한다.
     * flushAutomatically: 쿼리 실행 전 영속성 컨텍스트의 미반영 변경사항을 먼저 DB에 반영한다.
     * clearAutomatically: UPDATE 후 1차 캐시를 초기화해 이후 조회가 DB에서 최신값을 읽도록 보장한다.
     */
    @Modifying(flushAutomatically = true, clearAutomatically = true)
    @Transactional
    @Query("UPDATE ChatSession s SET s.updatedAt = :now WHERE s.id = :id")
    void updateUpdatedAt(@Param("id") Long id, @Param("now") LocalDateTime now);
}
