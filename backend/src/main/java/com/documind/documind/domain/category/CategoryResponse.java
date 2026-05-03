package com.documind.documind.domain.category;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

/**
 * 카테고리 조회 응답 DTO.
 */
@Getter
@Builder
public class CategoryResponse {

    private Long id;
    private String name;
    private LocalDateTime createdAt;

    /** Category Entity를 DTO로 변환한다. */
    public static CategoryResponse from(Category category) {
        return CategoryResponse.builder()
                .id(category.getId())
                .name(category.getName())
                .createdAt(category.getCreatedAt())
                .build();
    }
}
