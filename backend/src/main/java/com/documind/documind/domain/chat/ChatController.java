package com.documind.documind.domain.chat;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.time.Duration;
import java.util.List;

// 질의응답 API 엔드포인트. USER는 인증 불필요(SecurityConfig에서 permitAll)
// @RestController: @Controller + @ResponseBody 결합. JSON 응답 자동 직렬화
@RestController
// @RequestMapping: 이 컨트롤러의 모든 엔드포인트에 /api/chat 접두사 적용
@RequestMapping("/api/chat")
// @Validated: @RequestParam에 붙은 @Min, @Max 등 제약 어노테이션 활성화
@Validated
public class ChatController {

    private final ChatService chatService;
    private final Duration sseEmitterTimeout;

    public ChatController(
            ChatService chatService,
            @Value("${chat.sse-emitter-timeout:0s}") Duration sseEmitterTimeout
    ) {
        this.chatService = chatService;
        this.sseEmitterTimeout = sseEmitterTimeout;
    }

    // 질의응답 요청. USER는 로그인 불필요이므로 인증 없이 호출 가능
    @PostMapping
    public ResponseEntity<ApiResponse<ChatResponse>> chat(@Valid @RequestBody ChatRequest request) {
        ChatResponse response = chatService.chat(request);
        return ResponseEntity.ok(ApiResponse.success(response));
    }

    // 채팅 세션 목록 조회. 로그인: JWT로 사용자 전체 세션 반환, 비로그인: X-Session-Key 헤더로 단일 세션 반환
    @GetMapping("/sessions")
    public ResponseEntity<ApiResponse<List<ChatSessionSummaryResponse>>> getSessions(
            Authentication authentication,
            @RequestHeader(value = "X-Session-Key", required = false) String sessionKey
    ) {
        Long userId = extractUserId(authentication);
        return ResponseEntity.ok(ApiResponse.success(chatService.getSessions(userId, sessionKey)));
    }

    // 채팅 세션 상세 조회. 세션 정보와 시간순 메시지 목록을 반환. 소유권 검증 실패 시 404
    @GetMapping("/sessions/{id}")
    public ResponseEntity<ApiResponse<ChatSessionDetailResponse>> getSessionDetail(
            @PathVariable Long id,
            Authentication authentication,
            @RequestHeader(value = "X-Session-Key", required = false) String sessionKey
    ) {
        Long userId = extractUserId(authentication);
        return ResponseEntity.ok(ApiResponse.success(chatService.getSessionDetail(id, userId, sessionKey)));
    }

    // 채팅 세션 삭제. 메시지 포함 물리삭제. 소유권 검증 실패 시 404
    @DeleteMapping("/sessions/{id}")
    public ResponseEntity<ApiResponse<Void>> deleteSession(
            @PathVariable Long id,
            Authentication authentication,
            @RequestHeader(value = "X-Session-Key", required = false) String sessionKey
    ) {
        Long userId = extractUserId(authentication);
        chatService.deleteSession(id, userId, sessionKey);
        return ResponseEntity.ok(ApiResponse.success("채팅 세션이 삭제되었습니다."));
    }

    // AnonymousAuthenticationToken.isAuthenticated()는 true를 반환하므로 instanceof로 로그인 여부를 구분.
    // 로그인 사용자이면 details에서 userId를 꺼내고, 비로그인이면 null을 반환해 sessionKey 분기로 처리
    private Long extractUserId(Authentication authentication) {
        if (authentication == null
                || authentication instanceof AnonymousAuthenticationToken
                || !authentication.isAuthenticated()) {
            return null;
        }
        Object details = authentication.getDetails();
        return details instanceof Long ? (Long) details : null;
    }

    // SSE 스트리밍 질의응답. EventSource는 GET만 지원하므로 question을 query param으로 전달
    // produces: 브라우저가 text/event-stream으로 수신 시 연결을 유지하는 SSE 프로토콜
    @GetMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(
            @RequestParam String question,
            @RequestParam(required = false) String sessionKey,
            // defaultValue로 미전달 시 5를 기본값으로 사용. @Min/@Max는 @Validated 활성화 시 적용
            @RequestParam(defaultValue = "5") @Min(value = 1, message = "topK는 1 이상이어야 합니다.") @Max(value = 20, message = "topK는 20 이하이어야 합니다.") int topK
    ) {
        // SseEmitter timeout 0L: 서버가 정상 스트리밍 중인 연결을 임의로 끊지 않음
        SseEmitter emitter = new SseEmitter(sseEmitterTimeout.toMillis());
        chatService.streamChat(question, sessionKey, topK, emitter);
        return emitter;
    }
}
