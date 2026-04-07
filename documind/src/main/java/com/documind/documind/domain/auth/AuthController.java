package com.documind.documind.domain.auth;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.web.bind.annotation.*;

// 인증 관련 엔드포인트를 처리하는 컨트롤러
// @RestController: @Controller + @ResponseBody. JSON 응답을 기본으로 반환
// @RequestMapping: 공통 URL 접두사를 지정
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    // POST /api/auth/login - 로그인
    // @Valid: @NotBlank 등 DTO 유효성 검사를 활성화
    @PostMapping("/login")
    public ResponseEntity<ApiResponse<LoginResponse>> login(@Valid @RequestBody LoginRequest request) {
        LoginResponse response = authService.login(request.getUsername(), request.getPassword());
        return ResponseEntity.ok(ApiResponse.success(response));
    }

    // POST /api/auth/logout - 로그아웃
    // @AuthenticationPrincipal: SecurityContext에서 현재 인증된 사용자 정보를 주입
    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout(@AuthenticationPrincipal UserDetails userDetails) {
        authService.logout(userDetails.getUsername());
        return ResponseEntity.ok(ApiResponse.success("로그아웃 되었습니다."));
    }

    // POST /api/auth/reissue - Access Token 재발급
    @PostMapping("/reissue")
    public ResponseEntity<ApiResponse<String>> reissue(@RequestHeader("Refresh-Token") String refreshToken) {
        String newAccessToken = authService.reissue(refreshToken);
        return ResponseEntity.ok(ApiResponse.success(newAccessToken));
    }
}
