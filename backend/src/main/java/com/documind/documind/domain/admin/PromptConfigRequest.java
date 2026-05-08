package com.documind.documind.domain.admin;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 관리자 프롬프트 설정 저장 요청 DTO이다.
 */
@Getter
// @NoArgsConstructor: Jackson 역직렬화에 기본 생성자가 필요하다
@NoArgsConstructor
// @AllArgsConstructor: 테스트에서 직접 인스턴스 생성에 사용한다
@AllArgsConstructor
public class PromptConfigRequest {

    // @NotBlank: null, 빈 문자열, 공백 문자열 모두 거부
    @NotBlank(message = "시스템 프롬프트는 필수입니다.")
    @Size(max = 10000, message = "시스템 프롬프트는 10000자 이하로 입력해 주세요.")
    private String systemPrompt;
}
