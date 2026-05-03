package com.documind.documind.global.auth;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.web.authentication.WebAuthenticationDetails;

/**
 * JWT 인증에서 추출한 userId와 Spring의 WebAuthenticationDetails(remoteAddress, sessionId)를 함께 보관하는 인증 세부 정보 클래스.
 * authentication.setDetails(Long)으로 직접 저장하면 WebAuthenticationDetails를 기대하는
 * Spring Security 내부 컴포넌트에서 ClassCastException이 발생할 수 있으므로 래핑 클래스를 사용한다.
 */
public class JwtAuthenticationDetails extends WebAuthenticationDetails {

    private final Long userId;

    /**
     * @param request HTTP 요청. 부모 클래스가 remoteAddress와 sessionId를 캡처한다.
     * @param userId  JWT에서 추출한 사용자 PK
     */
    public JwtAuthenticationDetails(HttpServletRequest request, Long userId) {
        super(request);
        this.userId = userId;
    }

    /** JWT에서 추출한 사용자 PK를 반환한다. */
    public Long getUserId() {
        return userId;
    }
}
