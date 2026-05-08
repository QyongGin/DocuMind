package com.documind.documind.global.infra.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

/**
 * FastAPI POST /query, /query/stream 요청 DTO이다.
 * 관리자 프롬프트 설정을 함께 전달해 AI 서버가 최신 답변 정책을 반영한다.
 */
@Getter
@Builder
public class FastApiQueryRequest {

    // 사용자 질문 텍스트
    private String question;

    // 검색할 유사 청크 수. FastAPI 필드명이 snake_case이므로 명시
    @JsonProperty("top_k")
    private int topK;

    // 관리자가 설정한 시스템 프롬프트. FastAPI 필드명이 snake_case이므로 명시
    @JsonProperty("system_prompt")
    private String systemPrompt;
}
