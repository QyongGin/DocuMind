package com.documind.documind.domain.chat;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

// DB의 chat_feedback 테이블과 매핑되는 Entity 클래스임을 선언
@Entity
// 매핑할 테이블 이름 지정
@Table(name = "chat_feedback")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new ChatFeedback() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ChatFeedback {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // chat_messages 테이블과의 1:1 관계. 하나의 답변에 피드백은 하나만 존재
    @OneToOne(fetch = FetchType.LAZY)
    // FK 컬럼명 지정. nullable=false: 피드백은 반드시 특정 메시지에 대한 것이어야 함
    @JoinColumn(name = "message_id", nullable = false, unique = true)
    private ChatMessage chatMessage;

    // 피드백 점수. tinyint 타입으로 저장 (예: 1=좋아요, -1=싫어요)
    @Column(nullable = false)
    private Byte score;

    // NOT NULL, updatable=false: 최초 저장 후 변경 불가
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // chat_feedback은 updated_at 적용 대상. 피드백 점수 수정 시 갱신
    @Column(nullable = false)
    private LocalDateTime updatedAt;

    // DB에 INSERT 되기 직전에 자동 실행되는 메서드
    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        this.createdAt = now;
        this.updatedAt = now;
    }

    // DB에 UPDATE 되기 직전에 자동 실행되는 메서드
    @PreUpdate
    protected void onUpdate() {
        this.updatedAt = LocalDateTime.now();
    }
}