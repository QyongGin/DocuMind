package com.documind.documind.domain.auth;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;

import org.springframework.web.bind.annotation.*;

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

    /**
     * POST /api/auth/login — 로그인.
     * @return Access Token과 Refresh Token을 포함한 응답
     */
    // @Valid: @NotBlank 등 DTO 유효성 검사를 활성화
    @PostMapping("/login")
    public ResponseEntity<ApiResponse<LoginResponse>> login(@Valid @RequestBody LoginRequest request) {
        LoginResponse response = authService.login(request.getUsername(), request.getPassword());
        return ResponseEntity.ok(ApiResponse.success(response));
    }

    /**
     * POST /api/auth/logout — 로그아웃.
     * DB의 Refresh Token을 NULL로 초기화해 재사용을 차단한다.
     */
    // @AuthenticationPrincipal: SecurityContext에 저장된 principal을 주입. 필터에서 String(username)으로 저장했으므로 String으로 받는다
    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout(@AuthenticationPrincipal String username) {
        authService.logout(username);
        return ResponseEntity.ok(ApiResponse.success("로그아웃 되었습니다."));
    }

    /**
     * POST /api/auth/reissue — Access Token 재발급.
     * Refresh-Token 헤더로 유효한 Refresh Token을 전달해야 한다.
     */
    @PostMapping("/reissue")
    public ResponseEntity<ApiResponse<String>> reissue(@RequestHeader("Refresh-Token") String refreshToken) {
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
        return ResponseEntity.ok(ApiResponse.success("비밀번호가 변경되었습니다."));
    }
}
