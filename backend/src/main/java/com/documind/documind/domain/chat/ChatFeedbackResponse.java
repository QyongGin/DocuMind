package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

/**
 * 답변 피드백 등록·수정 응답 DTO.
 */
@Getter
@Builder
public class ChatFeedbackResponse {

    // 피드백 대상 메시지 ID
    private Long messageId;

    // 저장된 피드백 점수. 1=좋아요, -1=싫어요
    private Byte score;

    // 피드백 최종 수정 시각
    private LocalDateTime updatedAt;

    /**
     * ChatFeedback 엔티티를 클라이언트 응답 DTO로 변환한다.
     *
     * @param feedback 저장 또는 수정된 피드백 엔티티
     * @return 클라이언트에 반환할 피드백 응답
     */
    public static ChatFeedbackResponse from(ChatFeedback feedback) {
        return ChatFeedbackResponse.builder()
                .messageId(feedback.getChatMessage().getId())
                .score(feedback.getScore())
                .updatedAt(feedback.getUpdatedAt())
                .build();
    }
}
