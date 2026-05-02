package com.documind.documind.domain.auth;

import lombok.Builder;
import lombok.Getter;

// 로그인 성공 시 프론트엔드에 전달하는 DTO
// @Builder: 빌더 패턴으로 객체를 생성할 수 있도록 지원 (Lombok)
@Getter
@Builder
public class LoginResponse {

    private String accessToken;
    private String refreshToken;
}
