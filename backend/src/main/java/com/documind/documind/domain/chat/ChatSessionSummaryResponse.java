package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

// GET /api/chat/sessions 목록 응답 DTO. 세션 기본 정보만 포함해 네트워크 비용을 줄임
// @Builder: 서비스 레이어에서 필드를 명시적으로 지정해 객체를 생성
@Getter
@Builder
public class ChatSessionSummaryResponse {

    // 채팅 세션 식별자
    private Long sessionId;

    // 첫 질문 앞 50자를 자른 자동 생성 제목. 사이드바 목록 표시에 사용
    private String title;

    // 세션 생성 시각
    private LocalDateTime createdAt;

    // 마지막 메시지 저장 시각. 사이드바 정렬 기준 (최신 활동 순)
    private LocalDateTime updatedAt;
}
