package com.documind.documind.domain.admin;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

/**
 * 관리자 프롬프트 설정 조회 응답 DTO이다.
 */
@Getter
@Builder
public class PromptConfigResponse {

    private Long id;
    private String systemPrompt;
    private String updatedByUsername;
    private LocalDateTime updatedAt;

    /**
     * PromptConfig Entity를 응답 DTO로 변환한다.
     *
     * @param config 프롬프트 설정 Entity
     * @return 프롬프트 설정 응답 DTO
     */
    public static PromptConfigResponse from(PromptConfig config) {
        return PromptConfigResponse.builder()
                .id(config.getId())
                .systemPrompt(config.getSystemPrompt())
                .updatedByUsername(config.getUpdatedBy().getUsername())
                .updatedAt(config.getUpdatedAt())
                .build();
    }
}
