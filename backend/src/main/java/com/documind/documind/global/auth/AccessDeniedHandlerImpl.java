package com.documind.documind.global.auth;

import com.documind.documind.global.common.ApiResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;

// 인증은 됐지만 권한이 없는 요청(USER가 /api/admin 접근 등)이 발생할 때 403을 반환
// AccessDeniedHandler: Spring Security의 권한 부족 핸들러 인터페이스
// @RequiredArgsConstructor: final 필드(ObjectMapper)를 생성자 주입으로 받는다
@Component
@RequiredArgsConstructor
public class AccessDeniedHandlerImpl implements AccessDeniedHandler {

    private final ObjectMapper objectMapper;

    @Override
    public void handle(HttpServletRequest request,
                       HttpServletResponse response,
                       AccessDeniedException accessDeniedException) throws IOException {
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        // 수동 JSON 문자열 대신 ApiResponse 객체를 직렬화해 전역 응답 포맷과 일관성을 유지한다
        objectMapper.writeValue(response.getWriter(), ApiResponse.fail("접근 권한이 없습니다."));
    }
}
