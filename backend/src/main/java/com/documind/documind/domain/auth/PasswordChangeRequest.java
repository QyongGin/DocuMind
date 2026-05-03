package com.documind.documind.domain.auth;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Getter;

/**
 * 비밀번호 변경 요청 바디를 받는 DTO.
 * currentPassword는 본인 의사 확인용이다. Access Token이 유효하더라도 현재 비밀번호를 재확인해
 * 세션 탈취 공격자가 비밀번호를 교체하는 것을 막는다.
 */
// @AllArgsConstructor: 테스트에서 리플렉션 없이 직접 생성할 수 있도록 추가
@Getter
@AllArgsConstructor
public class PasswordChangeRequest {

    // @NotBlank: null, 빈 문자열, 공백 문자열 모두 거부
    @NotBlank
    private String currentPassword;

    @NotBlank
    private String newPassword;
}
