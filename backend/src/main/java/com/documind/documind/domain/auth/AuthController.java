package com.documind.documind.domain.auth;

import com.documind.documind.global.common.ApiResponse;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;

/**
 * 인증 관련 엔드포인트를 처리하는 컨트롤러.
 * 로그인·로그아웃·토큰 재발급·비밀번호 변경을 담당한다.
 */
// @RestController: @Controller + @ResponseBody. JSON 응답을 기본으로 반환
// @RequestMapping: 공통 URL 접두사를 지정
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    // jwt.refresh-token-expiration 값으로 쿠키 Max-Age를 동기화한다
    @Value("${jwt.refresh-token-expiration}")
    private Duration refreshTokenExpiration;

    // 쿠키 이름을 한 곳에서 관리해 오타 위험을 제거한다
    private static final String REFRESH_COOKIE_NAME = "refresh-token";

    /**
     * POST /api/auth/login — 로그인.
     * Access Token은 응답 body에, Refresh Token은 HttpOnly 쿠키에 담아 반환한다.
     */
    // @Valid: @NotBlank 등 DTO 유효성 검사를 활성화
    @PostMapping("/login")
    public ResponseEntity<ApiResponse<LoginResponse>> login(
            @Valid @RequestBody LoginRequest request,
            HttpServletResponse response) {
        LoginResponse tokens = authService.login(request.getUsername(), request.getPassword());
        setRefreshTokenCookie(response, tokens.getRefreshToken());
        return ResponseEntity.ok(ApiResponse.success(tokens));
    }

    /**
     * POST /api/auth/logout — 로그아웃.
     * DB의 Refresh Token을 NULL로 초기화하고, 브라우저의 refresh-token 쿠키를 만료시킨다.
     */
    // @AuthenticationPrincipal: SecurityContext에 저장된 principal을 주입. 필터에서 String(username)으로 저장했으므로 String으로 받는다
    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout(
            @AuthenticationPrincipal String username,
            HttpServletResponse response) {
        authService.logout(username);
        expireRefreshTokenCookie(response);
        return ResponseEntity.ok(ApiResponse.successMessage("로그아웃 되었습니다."));
    }

    /**
     * POST /api/auth/reissue — Access Token 재발급.
     * Refresh Token은 HttpOnly 쿠키에서 자동으로 읽는다. 쿠키가 없거나 만료된 경우 401을 반환한다.
     */
    // @CookieValue(required = false): 쿠키가 없으면 null을 주입한다.
    //   null이 전달되면 AuthService.reissue()가 INVALID_TOKEN 예외를 던져 GlobalExceptionHandler가 401을 반환한다.
    @PostMapping("/reissue")
    public ResponseEntity<ApiResponse<String>> reissue(
            @CookieValue(name = REFRESH_COOKIE_NAME, required = false) String refreshToken) {
        String newAccessToken = authService.reissue(refreshToken);
        return ResponseEntity.ok(ApiResponse.success(newAccessToken));
    }

    /**
     * GET /api/auth/verify — Access Token 유효성 검증 (ADMIN 전용).
     * JwtAuthenticationFilter가 JWT 서명·만료를 검증하므로 여기까지 도달하면 토큰이 유효하다.
     * 프론트엔드 RequireAdmin이 마운트 시 이 API를 호출해 토큰의 서버 수준 유효성을 확인한다.
     */
    @GetMapping("/verify")
    public ResponseEntity<ApiResponse<Void>> verify() {
        return ResponseEntity.ok(ApiResponse.success(null));
    }

    /**
     * POST /api/auth/password — 비밀번호 변경 (ADMIN 전용).
     * currentPassword 재확인으로 세션 탈취 공격자가 비밀번호를 교체하는 것을 방지한다.
     */
    @PostMapping("/password")
    public ResponseEntity<ApiResponse<Void>> changePassword(
            @AuthenticationPrincipal String username,
            @Valid @RequestBody PasswordChangeRequest request) {
        authService.changePassword(username, request.getCurrentPassword(), request.getNewPassword());
        return ResponseEntity.ok(ApiResponse.successMessage("비밀번호가 변경되었습니다."));
    }

    /**
     * refresh-token HttpOnly 쿠키를 Set-Cookie 헤더에 추가한다.
     * Secure 속성은 HTTPS 도입 이후 true로 변경해야 한다.
     */
    private void setRefreshTokenCookie(HttpServletResponse response, String refreshToken) {
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE_NAME, refreshToken)
                .httpOnly(true)
                .secure(false) // HTTPS 환경으로 전환 시 true로 변경
                .sameSite("Strict")
                .path("/api/auth")
                .maxAge(refreshTokenExpiration)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    /** refresh-token 쿠키를 Max-Age=0으로 즉시 만료시킨다. */
    private void expireRefreshTokenCookie(HttpServletResponse response) {
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE_NAME, "")
                .httpOnly(true)
                .secure(false)
                .sameSite("Strict")
                .path("/api/auth")
                .maxAge(0)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }
}
