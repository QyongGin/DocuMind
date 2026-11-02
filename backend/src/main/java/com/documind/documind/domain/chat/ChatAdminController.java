package com.documind.documind.domain.chat;

import com.documind.documind.global.common.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 관리자 개발자 모드 API(ADR-0050 결정 6, ADR-0052). 경로가 /api/admin 아래라 ADMIN만 부른다(SecurityConfig).
 */
@RestController
@RequestMapping("/api/admin/chat-messages")
@RequiredArgsConstructor
public class ChatAdminController {

    private final ChatService chatService;

    /**
     * GET /api/admin/chat-messages/{messageId}/dev-info — 답 하나의 원문 답, 화면 처리 내역, 근거 후보, 처리 기록.
     *
     * @param messageId 답(메시지) ID
     * @return 개발자 정보. 없는 답이면 404
     */
    @GetMapping("/{messageId}/dev-info")
    public ResponseEntity<ApiResponse<ChatDevInfoResponse>> devInfo(@PathVariable Long messageId) {
        return ResponseEntity.ok(ApiResponse.success(chatService.getDevInfo(messageId)));
    }
}
