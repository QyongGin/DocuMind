package com.documind.documind.domain.chat;

import com.documind.documind.domain.auth.User;
import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

// DB의 chat_sessions 테이블과 매핑되는 Entity 클래스임을 선언
@Entity
// 매핑할 테이블 이름 지정
@Table(name = "chat_sessions")
// 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
// 기본 생성자 자동 생성, PROTECTED로 설정해 외부에서 직접 new ChatSession() 못하게 막음
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ChatSession {

    // PK 지정
    @Id
    // AUTO_INCREMENT (DB가 값을 자동 증가시킴)
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // users 테이블과의 N:1 관계. LAZY: 실제 접근 시점에만 SELECT 쿼리 실행
    @ManyToOne(fetch = FetchType.LAZY)
    // FK 컬럼명 지정. nullable=true: 비로그인 USER는 user_id=NULL로 저장
    @JoinColumn(name = "user_id", nullable = true)
    private User user;

    // 비로그인 사용자를 식별하는 세션 키. 쿠키나 로컬스토리지로 관리. NULL 허용
    @Column(unique = true, length = 100)
    private String sessionKey;

    // 채팅 세션 제목. 첫 질문 앞부분을 잘라 자동 생성. NULL 허용
    @Column(length = 255)
    private String title;

    // NOT NULL, updatable=false: 최초 저장 후 변경 불가
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // chat_sessions은 updated_at 적용 대상. 세션 제목 수정 또는 마지막 활동 시각 갱신에 사용
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

    // 세션 생성 팩토리 메서드. title은 첫 질문 앞 50자를 잘라 전달
    public static ChatSession create(User user, String sessionKey, String title) {
        ChatSession session = new ChatSession();
        session.user = user;
        session.sessionKey = sessionKey;
        session.title = title;
        return session;
    }
}