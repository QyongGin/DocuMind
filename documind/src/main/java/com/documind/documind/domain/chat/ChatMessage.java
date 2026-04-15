package com.documind.documind.domain.chat;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

// DB의 chat_messages 테이블과 매핑되는 Entity 클래스임을 선언
@Entity
// 매핑할 테이블 이름 지정
@Table(name = "chat_messages")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new ChatMessage() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ChatMessage {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // chat_sessions 테이블과의 N:1 관계. LAZY: 실제 접근 시점에만 SELECT 쿼리 실행
    @ManyToOne(fetch = FetchType.LAZY)
    // FK 컬럼명 지정. nullable=false: 메시지는 반드시 세션에 속해야 함
    @JoinColumn(name = "session_id", nullable = false)
    private ChatSession chatSession;

    // 사용자 질문 내용. NOT NULL, TEXT 타입으로 길이 제한 없음
    @Column(nullable = false, columnDefinition = "TEXT")
    private String question;

    // LLM 답변 내용. NULL 허용: 스트리밍 중단 시 미완성 상태로 저장될 수 있음
    @Column(columnDefinition = "TEXT")
    private String answer;

    // 답변 생성에 사용된 출처 문서 목록. JSON 타입으로 저장
    @Column(columnDefinition = "JSON")
    private String sourceDocs;

    // NOT NULL, updatable=false: 최초 저장 후 변경 불가
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // DB에 INSERT 되기 직전에 자동 실행되는 메서드
    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }

    // 메시지 생성 팩토리 메서드. answer/sourceDocs는 LLM 응답 후 complete()로 채운다
    public static ChatMessage create(ChatSession chatSession, String question) {
        ChatMessage message = new ChatMessage();
        message.chatSession = chatSession;
        message.question = question;
        return message;
    }

    // LLM 응답 수신 후 answer와 sourceDocs를 저장. sourceDocs는 JSON 직렬화 문자열
    public void complete(String answer, String sourceDocs) {
        this.answer = answer;
        this.sourceDocs = sourceDocs;
    }
}