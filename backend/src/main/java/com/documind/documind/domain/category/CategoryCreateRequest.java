package com.documind.documind.domain.category;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 카테고리 생성 요청 DTO.
 */
// @NoArgsConstructor: Jackson 역직렬화에 기본 생성자가 필요하다
@Getter
@NoArgsConstructor
// @AllArgsConstructor: 테스트에서 직접 인스턴스 생성에 사용한다
@AllArgsConstructor
public class CategoryCreateRequest {

    // @NotBlank: null, 빈 문자열, 공백 문자열 모두 거부
    @NotBlank(message = "카테고리 이름은 필수입니다.")
    private String name;
}
