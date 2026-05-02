package com.documind.documind.domain.chat;

import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;

// POST /api/chat 요청 DTO
@Getter
@NoArgsConstructor
public class ChatRequest {

    // 사용자가 입력한 질문. 빈 문자열·공백·null 모두 거부
    @NotBlank(message = "질문은 필수입니다.")
    private String question;

    // 비로그인 사용자 세션 식별 키. 프론트엔드가 UUID를 생성해 전달. NULL 허용(비로그인 신규 세션)
    private String sessionKey;

    // 검색할 유사 청크 수. NULL이면 FastAPI 기본값(5) 사용
    private Integer topK;
}
