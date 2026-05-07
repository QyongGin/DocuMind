package com.documind.documind.domain.chat;

import com.documind.documind.global.auth.JwtAuthenticationDetails;
import com.documind.documind.global.common.ApiResponse;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.time.Duration;
import java.util.List;

/**
 * 질의응답 API 엔드포인트.
 * 일반 채팅, 채팅 이력, SSE 스트리밍 요청을 처리하며 USER는 인증 없이 호출할 수 있다.
 */
// @RestController: @Controller + @ResponseBody 결합. JSON 응답 자동 직렬화
@RestController
// @RequestMapping: 이 컨트롤러의 모든 엔드포인트에 /api/chat 접두사 적용
@RequestMapping("/api/chat")
// @Validated: @RequestParam에 붙은 @Min, @Max 등 제약 어노테이션 활성화
@Validated
@Slf4j
public class ChatController {

    private final ChatService chatService;
    private final StreamSessionStore streamSessionStore;
    private final Duration sseEmitterTimeout;

    /**
     * ChatController 의존성과 SSE 타임아웃 설정을 주입한다.
     */
    public ChatController(
            ChatService chatService,
            StreamSessionStore streamSessionStore,
            @Value("${chat.sse-emitter-timeout:0s}") Duration sseEmitterTimeout
    ) {
        this.chatService = chatService;
        this.streamSessionStore = streamSessionStore;
        this.sseEmitterTimeout = sseEmitterTimeout;
    }

    /**
     * POST /api/chat — 일반 질의응답 요청.
     * USER는 로그인 불필요이므로 인증 없이 호출할 수 있다.
     */
    @PostMapping
    public ResponseEntity<ApiResponse<ChatResponse>> chat(
            @Valid @RequestBody ChatRequest request,
            Authentication authentication
    ) {
        ChatResponse response = chatService.chat(request, extractUserId(authentication));
        return ResponseEntity.ok(ApiResponse.success(response));
    }

    /**
     * 채팅 세션 목록을 조회한다.
     * 로그인 사용자(ADMIN)는 JWT userId 기반 전체 세션을 최신 활동 순으로 반환하고,
     * 비로그인 사용자는 X-Session-Key 헤더 기반 단일 세션을 반환한다.
     */
    @GetMapping("/sessions")
    public ResponseEntity<ApiResponse<List<ChatSessionSummaryResponse>>> getSessions(
            Authentication authentication,
            @RequestHeader(value = "X-Session-Key", required = false) String sessionKey
    ) {
        Long userId = extractUserId(authentication);
        return ResponseEntity.ok(ApiResponse.success(chatService.getSessions(userId, sessionKey)));
    }

    /**
     * 채팅 세션 상세 정보와 시간순 메시지 목록을 조회한다.
     * sessionId와 소유자(userId 또는 sessionKey)가 일치하지 않으면 404를 반환한다.
     */
    @GetMapping("/sessions/{id}")
    public ResponseEntity<ApiResponse<ChatSessionDetailResponse>> getSessionDetail(
            @PathVariable Long id,
            Authentication authentication,
            @RequestHeader(value = "X-Session-Key", required = false) String sessionKey
    ) {
        Long userId = extractUserId(authentication);
        return ResponseEntity.ok(ApiResponse.success(chatService.getSessionDetail(id, userId, sessionKey)));
    }

    /**
     * 채팅 세션과 소속 메시지를 물리삭제한다.
     * 소유권 검증 실패 시 404를 반환한다.
     */
    @DeleteMapping("/sessions/{id}")
    public ResponseEntity<ApiResponse<Void>> deleteSession(
            @PathVariable Long id,
            Authentication authentication,
            @RequestHeader(value = "X-Session-Key", required = false) String sessionKey
    ) {
        Long userId = extractUserId(authentication);
        chatService.deleteSession(id, userId, sessionKey);
        return ResponseEntity.ok(ApiResponse.successMessage("채팅 세션이 삭제되었습니다."));
    }

    /**
     * Authentication 객체에서 userId를 추출한다.
     * AnonymousAuthenticationToken.isAuthenticated()는 true를 반환하므로 instanceof로 명시적으로 구분한다.
     * 비로그인이거나 details가 JwtAuthenticationDetails가 아니면 null을 반환해 sessionKey 분기로 처리한다.
     */
    private Long extractUserId(Authentication authentication) {
        if (authentication == null
                || authentication instanceof AnonymousAuthenticationToken
                || !authentication.isAuthenticated()) {
            return null;
        }
        Object details = authentication.getDetails();
        return details instanceof JwtAuthenticationDetails jad ? jad.getUserId() : null;
    }

    /**
     * POST /api/chat/stream/session — SSE 스트리밍 세션 사전 등록.
     * 질문을 body로 받아 서버 메모리에 30초간 보관하고 단일 사용 streamId를 발급한다.
     * 이후 GET /api/chat/stream/{streamId}로 SSE 연결 시 질문이 URL에 노출되지 않는다.
     */
    @PostMapping("/stream/session")
    public ResponseEntity<ApiResponse<StreamSessionResponse>> createStreamSession(
            @Valid @RequestBody StreamSessionRequest request,
            Authentication authentication
    ) {
        int topK = request.topK() == null ? 5 : request.topK();
        Long userId = extractUserId(authentication);
        StreamSessionSaveCommand command = new StreamSessionSaveCommand(
                request.question(),
                userId,
                request.sessionKey(),
                topK
        );
        String streamId = streamSessionStore.save(command)
                .orElseThrow(() -> new CustomException(ErrorCode.STREAM_SESSION_LIMIT_EXCEEDED));
        return ResponseEntity.ok(ApiResponse.success(new StreamSessionResponse(streamId)));
    }

    /**
     * GET /api/chat/stream/{streamId} — streamId 기반 SSE 스트리밍 질의응답.
     * 서버에서 streamId에 해당하는 질문을 조회한 뒤 단일 소비(remove)하고 스트리밍을 시작한다.
     * streamId가 없거나 30초 TTL이 초과된 경우 404를 반환한다.
     */
    @GetMapping(value = "/stream/{streamId}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamById(@PathVariable String streamId) {
        SseEmitter emitter = new SseEmitter(sseEmitterTimeout.toMillis());
        try {
            StreamSessionData data = streamSessionStore.consumeById(streamId)
                    .orElseThrow(() -> new CustomException(ErrorCode.STREAM_SESSION_NOT_FOUND));
            chatService.streamChat(new ChatStreamCommand(
                    data.question(),
                    data.userId(),
                    data.sessionKey(),
                    data.topK(),
                    emitter
            ));
        } catch (CustomException e) {
            sendStreamErrorAndComplete(emitter, e.getErrorCode());
        } catch (Exception e) {
            log.error("streamId 기반 SSE 스트리밍 시작 오류", e);
            sendStreamErrorAndComplete(emitter, ErrorCode.INTERNAL_SERVER_ERROR);
        }
        return emitter;
    }

    /**
     * GET /api/chat/stream — 레거시 SSE 스트리밍 질의응답.
     * question이 URL에 노출되므로 신규 클라이언트는 /stream/session + /stream/{streamId} 패턴을 사용한다.
     */
    @GetMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(
            @RequestParam String question,
            @RequestParam(required = false) String sessionKey,
            // defaultValue로 미전달 시 5를 기본값으로 사용. @Min/@Max는 @Validated 활성화 시 적용
            @RequestParam(defaultValue = "5") @Min(value = 1, message = "topK는 1 이상이어야 합니다.") @Max(value = 20, message = "topK는 20 이하이어야 합니다.") int topK
    ) {
        // SseEmitter timeout 0L: 서버가 정상 스트리밍 중인 연결을 임의로 끊지 않음
        SseEmitter emitter = new SseEmitter(sseEmitterTimeout.toMillis());
        chatService.streamChat(new ChatStreamCommand(question, null, sessionKey, topK, emitter));
        return emitter;
    }

    private void sendStreamErrorAndComplete(SseEmitter emitter, ErrorCode errorCode) {
        String message = errorCode.getMessage();
        String payload = """
                {"type":"error","error":"%s","code":"%s","message":"%s"}
                """.formatted(message, errorCode.name(), message);
        try {
            emitter.send(SseEmitter.event().name("error").data(payload));
        } catch (IOException e) {
            log.warn("SSE 오류 이벤트 전송 실패", e);
        } finally {
            emitter.complete();
        }
    }
}
