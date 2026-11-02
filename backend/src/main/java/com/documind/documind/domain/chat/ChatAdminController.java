package com.documind.documind.domain.chat;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 관리자 개발자 모드 API(ADR-0050 결정 6, ADR-0052). 경로가 /api/admin 아래라 ADMIN만 부른다(SecurityConfig).
 */
@RestController
@RequestMapping("/api/admin/chat-messages")
@RequiredArgsConstructor
@Validated
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

    /**
     * GET /api/admin/chat-messages/unanswered — 거절 문장만 나간 답의 질문(못 답한 질문)을 최근 것부터 한 쪽씩.
     *
     * @param page 쪽 번호(0부터)
     * @param size 쪽 크기(1~100)
     * @return 질문 목록과 전체 수
     */
    @GetMapping("/unanswered")
    public ResponseEntity<ApiResponse<UnansweredQuestionsResponse>> unanswered(
            @RequestParam(defaultValue = "0") @Min(value = 0, message = "page는 0 이상이어야 합니다.") int page,
            @RequestParam(defaultValue = "20") @Min(value = 1, message = "size는 1 이상이어야 합니다.")
            @Max(value = 100, message = "size는 100 이하여야 합니다.") int size) {
        return ResponseEntity.ok(ApiResponse.success(chatService.getUnansweredQuestions(page, size)));
    }
}
