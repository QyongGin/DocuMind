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

    // 모델 원문 답(출처 번호 포함, ADR-0051 결정 3). answer는 화면용 답이다. 이 칸이 생기기 전 메시지는 null
    @Column(columnDefinition = "TEXT")
    private String rawAnswer;

    // 답변 생성에 사용된 출처 문서 목록. JSON 타입으로 저장
    @Column(columnDefinition = "JSON")
    private String sourceDocs;

    // 거절 문장만 나간 답(정해 둔 안내를 붙인 답)인지. 관리자 '못 답한 질문' 목록에 쓴다(ADR-0052 결정 5)
    @Column(nullable = false)
    private boolean refused;

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

    // LLM 응답 수신 후 answer와 sourceDocs를 저장. sourceDocs는 JSON 직렬화 문자열. 원문과 화면용이 같은 경우(부분 답변·오류)
    public void complete(String answer, String sourceDocs) {
        complete(answer, answer, sourceDocs);
    }

    /**
     * 화면용 답과 모델 원문 답, 출처 목록을 저장한다(ADR-0051 결정 3).
     *
     * @param answer     화면용 답(출처 번호를 지운 것)
     * @param rawAnswer  모델 원문 답
     * @param sourceDocs 출처 목록 JSON
     */
    public void complete(String answer, String rawAnswer, String sourceDocs) {
        this.answer = answer;
        this.rawAnswer = rawAnswer;
        this.sourceDocs = sourceDocs;
    }

    /**
     * 화면용 답과 모델 원문 답, 출처 목록에 더해 거절 문장만 나간 답인지를 저장한다(ADR-0052 결정 5).
     *
     * @param answer     화면용 답(출처 번호를 지운 것)
     * @param rawAnswer  모델 원문 답
     * @param sourceDocs 출처 목록 JSON
     * @param refused    거절 문장만 나간 답인지
     */
    public void complete(String answer, String rawAnswer, String sourceDocs, boolean refused) {
        complete(answer, rawAnswer, sourceDocs);
        this.refused = refused;
    }
}