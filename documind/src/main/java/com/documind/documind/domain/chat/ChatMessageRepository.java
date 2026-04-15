package com.documind.documind.domain.chat;

import org.springframework.data.jpa.repository.JpaRepository;

// chat_messages 테이블 CRUD를 담당하는 JPA Repository
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
}
