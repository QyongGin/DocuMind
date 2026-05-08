package com.documind.documind.domain.admin;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 관리자 프롬프트 설정 엔드포인트를 처리하는 컨트롤러이다.
 * 모든 API는 SecurityConfig의 /api/admin/** 규칙으로 ADMIN 권한을 요구한다.
 */
@RestController
@RequestMapping("/api/admin/prompt")
@RequiredArgsConstructor
public class PromptConfigController {

    private final PromptConfigService promptConfigService;

    /**
     * GET /api/admin/prompt — 현재 프롬프트 설정을 조회한다.
     *
     * @return 현재 적용할 시스템 프롬프트 설정
     */
    @GetMapping
    public ResponseEntity<ApiResponse<PromptConfigResponse>> getCurrent() {
        return ResponseEntity.ok(ApiResponse.success(promptConfigService.getCurrent()));
    }

    /**
     * PUT /api/admin/prompt — 시스템 프롬프트를 저장한다.
     *
     * @param request  저장할 시스템 프롬프트 요청 DTO
     * @param username JWT 인증 주체인 관리자 계정명
     * @return 저장된 시스템 프롬프트 설정
     */
    @PutMapping
    public ResponseEntity<ApiResponse<PromptConfigResponse>> update(
            @Valid @RequestBody PromptConfigRequest request,
            @AuthenticationPrincipal String username
    ) {
        return ResponseEntity.ok(ApiResponse.success(promptConfigService.update(request, username)));
    }
}
