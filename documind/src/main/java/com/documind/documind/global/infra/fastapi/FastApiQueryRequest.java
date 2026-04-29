package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

// FastAPI POST /query 요청 DTO. JSON body로 전송
@Getter
@Builder
public class FastApiQueryRequest {

    // 사용자 질문 텍스트
    private String question;

    // 검색할 유사 청크 수. FastAPI 필드명이 snake_case이므로 명시
    @JsonProperty("top_k")
    private int topK;
}
