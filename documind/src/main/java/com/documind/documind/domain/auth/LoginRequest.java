package com.documind.documind.domain.auth;

import jakarta.validation.constraints.NotBlank;
import lombok.Getter;

// 로그인 요청 바디를 받는 DTO
// @Getter: 모든 필드의 getter 메서드 자동 생성 (Lombok)
@Getter
public class LoginRequest {

    // @NotBlank: null, 빈 문자열, 공백 문자열 모두 거부
    @NotBlank
    private String username;

    @NotBlank
    private String password;
}
