package com.documind.documind.domain.chat;

import lombok.Builder;
import lombok.Getter;

import java.util.List;

// POST /api/chat 응답 DTO. 검색 후보(청크 본문, 업로드 시각)는 넣지 않고 관리자 개발자 정보 API로만 준다(ADR-0052)
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

    // 참고한 문서(답이 쓴 근거, ADR-0050)
    private List<ReferenceDocument> references;

    // 거절 문장만 있는 답에 붙이는 정해 둔 안내. 그 밖에는 null
    private RefusalGuidance guidance;
}
