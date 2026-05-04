package com.documind.documind.global.auth;

import com.documind.documind.global.common.ApiResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.stereotype.Component;

import java.io.IOException;

// 인증되지 않은 요청(토큰 없음 또는 만료)이 보호된 경로에 접근할 때 401을 반환
// AuthenticationEntryPoint: Spring Security의 인증 실패 진입점 인터페이스
// @RequiredArgsConstructor: final 필드(ObjectMapper)를 생성자 주입으로 받는다
@Component
@RequiredArgsConstructor
public class AuthEntryPoint implements AuthenticationEntryPoint {

    private final ObjectMapper objectMapper;

    @Override
    public void commence(HttpServletRequest request,
                         HttpServletResponse response,
                         AuthenticationException authException) throws IOException {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        // 수동 JSON 문자열 대신 ApiResponse 객체를 직렬화해 전역 응답 포맷과 일관성을 유지한다
        objectMapper.writeValue(response.getWriter(), ApiResponse.fail("인증이 필요합니다."));
    }
}
