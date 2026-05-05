package com.documind.documind.domain.chat;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

/** POST /api/chat/stream/session 요청 DTO. 질문 내용을 body로 전달해 URL 노출을 방지한다. */
public record StreamSessionRequest(
        @NotBlank(message = "질문을 입력해 주세요.") String question,
        String sessionKey,
        @Min(value = 1, message = "topK는 1 이상이어야 합니다.")
        @Max(value = 20, message = "topK는 20 이하이어야 합니다.")
        Integer topK
) {}
