package com.documind.documind.domain.chat;

import com.documind.documind.global.common.ApiResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

// 질의응답 API 엔드포인트. USER는 인증 불필요(SecurityConfig에서 permitAll)
// @RestController: @Controller + @ResponseBody 결합. JSON 응답 자동 직렬화
@RestController
// @RequestMapping: 이 컨트롤러의 모든 엔드포인트에 /api/chat 접두사 적용
@RequestMapping("/api/chat")
@RequiredArgsConstructor
public class ChatController {

    private final ChatService chatService;

    // 질의응답 요청. USER는 로그인 불필요이므로 인증 없이 호출 가능
    @PostMapping
    public ResponseEntity<ApiResponse<ChatResponse>> chat(@Valid @RequestBody ChatRequest request) {
        ChatResponse response = chatService.chat(request);
        return ResponseEntity.ok(ApiResponse.success(response));
    }
}
