package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;
import java.util.List;

/**
 * GET /api/chat/sessions/{id} 상세 조회 응답에 포함되는 단일 메시지 DTO.
 * 검색 후보(청크 본문, 업로드 시각)는 넣지 않고 관리자 개발자 정보 API로만 준다(ADR-0052).
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

    // 참고한 문서(답이 쓴 근거, ADR-0050)
    private List<ReferenceDocument> references;

    // 거절 문장만 있는 답에 붙이는 정해 둔 안내. 그 밖에는 null
    private RefusalGuidance guidance;

    // 저장된 피드백 점수. 1=좋아요, -1=싫어요, null=미등록
    private Byte feedbackScore;

    // 메시지 생성 시각
    private LocalDateTime createdAt;
}
