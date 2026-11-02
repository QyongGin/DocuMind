package com.documind.documind.domain.chat;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.auth.JwtProvider;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.nullValue;
import static org.hamcrest.Matchers.startsWith;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 처리 기록(ADR-0052)과 관리자 개발자 정보 API: 답마다 저장하고, 보관 기간이 지나면 지우고, 관리자만 읽는다.
 * 데이터는 지어낸 학교(가나대학)다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ChatMessageTraceTest {

    private static final String SESSION_KEY = "trace-session-key";
    private static final String TRACE = """
            {"prompt": "[검색 근거]\\n[출처 1]\\n가나대학 휴학 신청 기간", "seconds": {"total": 1.5},
             "candidates": [{"rank": 1, "chunk_id": "7_0", "rerank_score": 0.9}]}""";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ChatService chatService;

    @Autowired
    private ChatStreamPersistenceService chatStreamPersistenceService;

    @Autowired
    private ChatMessageTraceCleanup chatMessageTraceCleanup;

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private ChatMessageTraceRepository chatMessageTraceRepository;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private JwtProvider jwtProvider;

    @Autowired
    private ObjectMapper objectMapper;

    @MockitoBean
    private FastApiClient fastApiClient;

    private ChatSession session;
    private User admin;

    @BeforeEach
    void setUp() {
        session = chatSessionRepository.save(ChatSession.create(null, SESSION_KEY, "가나대학 휴학"));
        admin = userRepository.save(User.create("trace-admin", "encoded-password", User.Role.ADMIN));
    }

    @AfterEach
    void tearDown() {
        chatMessageTraceRepository.deleteAll();
        chatMessageRepository.deleteAll();
        chatSessionRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("개발자 정보 - 원문 답, 화면 처리 내역(지운 출처 번호), 근거 후보, 저장한 처리 기록을 돌려준다")
    void devInfo_returnsRawAnswerScreenProcessingSourcesAndTrace() throws Exception {
        ChatMessage message = saveMessage("가나대학 휴학 신청은 언제까지예요?", "휴학 신청은 8월 29일까지입니다.\n\n[출처 1]");
        chatStreamPersistenceService.saveTrace(message.getId(), TRACE);

        mockMvc.perform(get("/api/admin/chat-messages/{id}/dev-info", message.getId())
                        .header("Authorization", bearer(admin.getUsername(), User.Role.ADMIN, admin.getId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.question", is("가나대학 휴학 신청은 언제까지예요?")))
                .andExpect(jsonPath("$.data.rawAnswer", is("휴학 신청은 8월 29일까지입니다.\n\n[출처 1]")))
                .andExpect(jsonPath("$.data.answer", is("휴학 신청은 8월 29일까지입니다.")))
                .andExpect(jsonPath("$.data.citedSources", contains(1)))
                .andExpect(jsonPath("$.data.guidanceAttached", is(false)))
                // 근거 후보는 대화 기록의 source_docs에서 읽는다. H2는 이 JSON 칸을 문자열로 저장해 내용은 MySQL에서만 읽힌다
                .andExpect(jsonPath("$.data.sources").isArray())
                .andExpect(jsonPath("$.data.trace.prompt", startsWith("[검색 근거]")))
                .andExpect(jsonPath("$.data.trace.seconds.total", is(1.5)))
                .andExpect(jsonPath("$.data.trace.candidates[0].rerank_score", is(0.9)));
    }

    @Test
    @DisplayName("개발자 정보 - 거절 문장만 나간 답은 안내를 붙였다고 보이고, 처리 기록이 없으면 trace가 null이다")
    void devInfo_refusalOnlyAnswerWithoutTrace() throws Exception {
        ChatMessage message = saveMessage("가나대학 기숙사 비용은요?", "학교 홈페이지 안내에서 찾지 못했습니다.");

        mockMvc.perform(get("/api/admin/chat-messages/{id}/dev-info", message.getId())
                        .header("Authorization", bearer(admin.getUsername(), User.Role.ADMIN, admin.getId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.guidanceAttached", is(true)))
                .andExpect(jsonPath("$.data.trace").value(nullValue()));
    }

    @Test
    @DisplayName("개발자 정보 - USER 권한 요청은 403, 없는 답은 404를 반환한다")
    void devInfo_userRoleIsForbiddenAndUnknownMessageIsNotFound() throws Exception {
        ChatMessage message = saveMessage("가나대학 휴학 신청은 언제까지예요?", "휴학 신청은 8월 29일까지입니다.");

        mockMvc.perform(get("/api/admin/chat-messages/{id}/dev-info", message.getId())
                        .header("Authorization", bearer("user", User.Role.USER, 999L)))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/admin/chat-messages/{id}/dev-info", message.getId() + 1000)
                        .header("Authorization", bearer(admin.getUsername(), User.Role.ADMIN, admin.getId())))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("바로 받는 답 - AI 서버가 보낸 처리 기록을 그 답의 기록으로 저장한다")
    void chat_savesTraceFromAiServer() throws Exception {
        FastApiQueryResponse aiResponse = new FastApiQueryResponse();
        ReflectionTestUtils.setField(aiResponse, "answer", "휴학 신청은 8월 29일까지입니다.");
        ReflectionTestUtils.setField(aiResponse, "sources", List.of(Map.of("source", "휴학 안내.pdf")));
        ReflectionTestUtils.setField(aiResponse, "trace", Map.of("prompt", "가나대학 프롬프트"));
        when(fastApiClient.query(eq("가나대학 휴학 신청은 언제까지예요?"), anyInt(), anyString())).thenReturn(aiResponse);
        ChatRequest request = new ChatRequest();
        ReflectionTestUtils.setField(request, "question", "가나대학 휴학 신청은 언제까지예요?");
        ReflectionTestUtils.setField(request, "sessionKey", SESSION_KEY);

        ChatResponse response = chatService.chat(request, null);

        String trace = chatMessageTraceRepository.findById(response.getMessageId()).orElseThrow().getTrace();
        assertEquals("가나대학 프롬프트", objectMapper.readTree(trace).get("prompt").asText());
    }

    @Test
    @DisplayName("지우기 작업 - 보관 기간(30일)이 지난 처리 기록만 지운다")
    void cleanup_deletesOnlyExpiredTraces() {
        ChatMessage old = saveMessage("지난달 질문", "지난달 답");
        ChatMessage recent = saveMessage("어제 질문", "어제 답");
        chatMessageTraceRepository.save(ChatMessageTrace.of(old.getId(), "{}", LocalDateTime.now().minusDays(31)));
        chatMessageTraceRepository.save(ChatMessageTrace.of(recent.getId(), "{}", LocalDateTime.now().minusDays(29)));

        chatMessageTraceCleanup.deleteExpired();

        assertFalse(chatMessageTraceRepository.existsById(old.getId()));
        assertTrue(chatMessageTraceRepository.existsById(recent.getId()));
    }

    @Test
    @DisplayName("세션 삭제 - 그 세션 답들의 처리 기록도 지운다")
    void deleteSession_deletesTraces() {
        ChatMessage message = saveMessage("가나대학 휴학 신청은 언제까지예요?", "휴학 신청은 8월 29일까지입니다.");
        chatStreamPersistenceService.saveTrace(message.getId(), TRACE);

        chatService.deleteSession(session.getId(), null, SESSION_KEY);

        assertFalse(chatMessageTraceRepository.existsById(message.getId()));
    }

    private ChatMessage saveMessage(String question, String rawAnswer) {
        ChatMessage message = ChatMessage.create(session, question);
        message.complete(rawAnswer, rawAnswer, "[{\"document_id\":\"7\",\"source\":\"휴학 안내.pdf\",\"content\":\"휴학 신청 기간\"}]");
        return chatMessageRepository.save(message);
    }

    private String bearer(String username, User.Role role, Long id) {
        return "Bearer " + jwtProvider.generateToken(username, role.name(), id);
    }
}
