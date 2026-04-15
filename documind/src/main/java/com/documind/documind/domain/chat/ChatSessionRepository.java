package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

// chat_sessions 테이블 CRUD를 담당하는 JPA Repository
public interface ChatSessionRepository extends JpaRepository<ChatSession, Long> {

    // 비로그인 사용자의 sessionKey로 기존 세션을 조회
    Optional<ChatSession> findBySessionKey(String sessionKey);
}
