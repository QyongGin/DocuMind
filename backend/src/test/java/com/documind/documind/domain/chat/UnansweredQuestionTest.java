package com.documind.documind.domain.chat;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.auth.JwtProvider;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
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

import java.util.List;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 못 답한 질문(ADR-0052 결정 5): 거절 문장만 나간 답을 표시하고, 관리자가 최근 것부터 한 쪽씩 본다.
 * 일부만 없는 답과 답한 질문은 넣지 않는다. 데이터는 지어낸 학교(가나대학)다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class UnansweredQuestionTest {

    private static final String SESSION_KEY = "unanswered-session-key";
    private static final String REFUSAL = "학교 홈페이지 안내에서 찾지 못했습니다.";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ChatService chatService;

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private JwtProvider jwtProvider;

    @MockitoBean
    private FastApiClient fastApiClient;

    private User admin;

    @BeforeEach
    void setUp() {
        admin = userRepository.save(User.create("unanswered-admin", "encoded-password", User.Role.ADMIN));
        ask("가나대학 기숙사 비용은요?", REFUSAL);
        ask("가나대학 휴학 신청은 언제까지예요?", "휴학 신청은 8월 29일까지입니다.");
        ask("가나대학 통학버스 시간과 요금은요?", "통학버스는 20분 앞당겨 운행됩니다. 요금은 " + REFUSAL);
        ask("가나대학 졸업 유예 비용은요?", REFUSAL);
    }

    @AfterEach
    void tearDown() {
        chatMessageRepository.deleteAll();
        chatSessionRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("못 답한 질문 - 거절 문장만 나간 질문만 최근 것부터 한 쪽씩 돌려준다")
    void unanswered_listsRefusalOnlyQuestionsNewestFirst() throws Exception {
        mockMvc.perform(get("/api/admin/chat-messages/unanswered").param("page", "0").param("size", "1")
                        .header("Authorization", adminBearer()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total", is(2)))
                .andExpect(jsonPath("$.data.items", hasSize(1)))
                .andExpect(jsonPath("$.data.items[0].question", is("가나대학 졸업 유예 비용은요?")));
        mockMvc.perform(get("/api/admin/chat-messages/unanswered").param("page", "1").param("size", "1")
                        .header("Authorization", adminBearer()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].question", is("가나대학 기숙사 비용은요?")));
    }

    @Test
    @DisplayName("못 답한 질문 - USER 권한은 403, 쪽 크기가 범위 밖이면 400을 반환한다")
    void unanswered_rejectsUserRoleAndInvalidSize() throws Exception {
        mockMvc.perform(get("/api/admin/chat-messages/unanswered")
                        .header("Authorization", "Bearer " + jwtProvider.generateToken("user", "USER", 999L)))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/admin/chat-messages/unanswered").param("size", "101")
                        .header("Authorization", adminBearer()))
                .andExpect(status().isBadRequest());
    }

    private void ask(String question, String answer) {
        FastApiQueryResponse aiResponse = new FastApiQueryResponse();
        ReflectionTestUtils.setField(aiResponse, "answer", answer);
        ReflectionTestUtils.setField(aiResponse, "sources", List.of());
        when(fastApiClient.query(eq(question), anyInt(), anyString())).thenReturn(aiResponse);
        ChatRequest request = new ChatRequest();
        ReflectionTestUtils.setField(request, "question", question);
        ReflectionTestUtils.setField(request, "sessionKey", SESSION_KEY);
        chatService.chat(request, null);
    }

    private String adminBearer() {
        return "Bearer " + jwtProvider.generateToken(admin.getUsername(), User.Role.ADMIN.name(), admin.getId());
    }
}
