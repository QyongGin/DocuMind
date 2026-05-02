package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

// 세션 상세 조회 응답에 포함되는 단일 메시지 DTO
// @Builder: 서비스 레이어에서 필드를 명시적으로 지정해 객체를 생성
@Getter
@Builder
public class ChatMessageResponse {

    // 메시지 식별자
    private Long messageId;

    // 사용자 질문
    private String question;

    // LLM 답변. 스트리밍 중단 시 null일 수 있음
    private String answer;

    // 답변 근거 문서 목록. DB의 JSON 문자열을 역직렬화한 결과
    private List<Map<String, Object>> sources;

    // 메시지 생성 시각
    private LocalDateTime createdAt;
}
