package com.documind.documind.domain.chat;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;

/**
 * 답 하나의 처리 기록(ADR-0052): AI 서버가 답 끝에 보낸 프롬프트, 단계별 걸린 초, 근거 후보별 검색 점수, 모델 설정.
 * 관리자 개발자 모드에서 보고, 보관 기간(chat.trace.retention)이 지나면 지운다.
 */
@Entity
@Table(name = "chat_message_traces")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ChatMessageTrace {

    // chat_messages.id와 같은 값. 답 하나에 처리 기록 하나
    @Id
    private Long messageId;

    // AI 서버가 보낸 처리 기록 JSON 그대로. JSON 타입으로 바인딩해야 H2·MySQL 모두 문자열이 아닌 JSON 문서로 저장된다
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "JSON")
    private String trace;

    // 보관 기간을 재는 기준 시각
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    /**
     * 처리 기록을 만든다.
     *
     * @param messageId 기록이 속한 답(chat_messages.id)
     * @param trace     AI 서버가 보낸 처리 기록 JSON
     * @param createdAt 저장 시각. 보관 기간을 이 시각부터 잰다
     * @return 저장할 처리 기록
     */
    public static ChatMessageTrace of(Long messageId, String trace, LocalDateTime createdAt) {
        ChatMessageTrace messageTrace = new ChatMessageTrace();
        messageTrace.messageId = messageId;
        messageTrace.trace = trace;
        messageTrace.createdAt = createdAt;
        return messageTrace;
    }
}
