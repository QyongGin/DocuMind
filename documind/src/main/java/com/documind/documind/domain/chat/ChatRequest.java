package com.documind.documind.domain.chat;

import lombok.Getter;
import lombok.NoArgsConstructor;

// POST /api/chat 요청 DTO
@Getter
@NoArgsConstructor
public class ChatRequest {

    // 사용자가 입력한 질문
    private String question;

    // 비로그인 사용자 세션 식별 키. 프론트엔드가 UUID를 생성해 전달. NULL 허용(비로그인 신규 세션)
    private String sessionKey;

    // 검색할 유사 청크 수. NULL이면 FastAPI 기본값(5) 사용
    private Integer topK;
}
