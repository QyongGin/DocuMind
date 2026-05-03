package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;
import java.util.List;

/**
 * GET /api/chat/sessions/{id} 상세 조회 응답 DTO.
 * 세션 정보와 시간순 정렬된 전체 메시지 목록을 포함한다.
 */
@Getter
@Builder
public class ChatSessionDetailResponse {

    // 채팅 세션 식별자
    private Long sessionId;

    // 첫 질문 앞 50자를 자른 자동 생성 제목
    private String title;

    // 세션 생성 시각
    private LocalDateTime createdAt;

    // 해당 세션의 메시지 목록. 시간순 정렬 (오래된 순)으로 대화 흐름을 재현
    private List<ChatMessageResponse> messages;
}
