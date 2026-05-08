package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * GET /api/chat/sessions/{id} 상세 조회 응답에 포함되는 단일 메시지 DTO.
 * sources는 DB의 JSON 문자열을 역직렬화한 결과이며, 역직렬화 실패 시 빈 리스트로 폴백한다.
 */
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

    // 저장된 피드백 점수. 1=좋아요, -1=싫어요, null=미등록
    private Byte feedbackScore;

    // 메시지 생성 시각
    private LocalDateTime createdAt;
}
