package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.util.List;
import java.util.Map;

// POST /api/chat 응답 DTO
// @Builder: 서비스 레이어에서 필드를 명시적으로 지정해 객체를 생성
@Getter
@Builder
public class ChatResponse {

    // 생성되거나 재사용된 채팅 세션 ID
    private Long sessionId;

    // 저장된 메시지 ID
    private Long messageId;

    // LLM이 생성한 답변
    private String answer;

    // 답변 근거로 사용된 문서 청크 목록. 각 항목에 document_id, source, content, Header 경로 포함
    private List<Map<String, Object>> sources;
}
