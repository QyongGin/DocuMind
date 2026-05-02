package com.documind.documind.domain.chat;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

// 질의응답 API 엔드포인트. USER는 인증 불필요(SecurityConfig에서 permitAll)
// @RestController: @Controller + @ResponseBody 결합. JSON 응답 자동 직렬화
@RestController
// @RequestMapping: 이 컨트롤러의 모든 엔드포인트에 /api/chat 접두사 적용
@RequestMapping("/api/chat")
@RequiredArgsConstructor
// @Validated: @RequestParam에 붙은 @Min, @Max 등 제약 어노테이션 활성화
@Validated
public class ChatController {

    private final ChatService chatService;

    // 질의응답 요청. USER는 로그인 불필요이므로 인증 없이 호출 가능
    @PostMapping
    public ResponseEntity<ApiResponse<ChatResponse>> chat(@Valid @RequestBody ChatRequest request) {
        ChatResponse response = chatService.chat(request);
        return ResponseEntity.ok(ApiResponse.success(response));
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
        // 타임아웃 120초: LLM 추론이 길어지는 경우를 고려. 0L은 타임아웃 없음
        SseEmitter emitter = new SseEmitter(120_000L);
        chatService.streamChat(question, sessionKey, topK, emitter);
        return emitter;
    }
}
