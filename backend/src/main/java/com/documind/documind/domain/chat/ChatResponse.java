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

    // 참고한 문서(답이 쓴 근거, ADR-0050). 화면은 sources 대신 이것을 보인다
    private List<ReferenceDocument> references;

    // 거절 문장만 있는 답에 붙이는 정해 둔 안내. 그 밖에는 null
    private RefusalGuidance guidance;
}
