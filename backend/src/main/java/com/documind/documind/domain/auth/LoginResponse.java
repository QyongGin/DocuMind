package com.documind.documind.domain.auth;

import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.Builder;
import lombok.Getter;

/**
 * 로그인 성공 시 HTTP 응답 body에 담기는 DTO.
 * refreshToken은 HttpOnly 쿠키로 전달하므로 JSON 직렬화에서 제외한다.
 */
// @Builder: 빌더 패턴으로 객체를 생성할 수 있도록 지원 (Lombok)
@Getter
@Builder
public class LoginResponse {

    private String accessToken;

    // HTTP 응답 body에 노출하지 않는다 — AuthController에서 HttpOnly 쿠키로 전송
    @JsonIgnore
    private String refreshToken;
}
