package com.documind.documind.domain.chat;

import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.startsWith;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 일반 사용자가 받는 채팅 응답에는 검색 후보(청크 본문, 업로드 시각)가 없다(ADR-0052 결정 4).
 * 검색 후보는 관리자 개발자 정보 API로만 준다. 데이터는 지어낸 학교(가나대학)다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ChatResponseContractTest {

    private static final String SESSION_KEY = "contract-session-key";
    private static final String QUESTION = "가나대학 휴학 신청은 언제까지예요?";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private ChatMessageTraceRepository chatMessageTraceRepository;

    @MockitoBean
    private FastApiClient fastApiClient;

    @AfterEach
    void tearDown() {
        chatMessageTraceRepository.deleteAll();
        chatMessageRepository.deleteAll();
        chatSessionRepository.deleteAll();
    }

    @Test
    @DisplayName("바로 받는 답과 대화 기록 응답에 검색 후보가 없고 답 속 링크가 있다")
    void chatAndHistoryResponses_haveNoSources() throws Exception {
        FastApiQueryResponse aiResponse = new FastApiQueryResponse();
        ReflectionTestUtils.setField(aiResponse, "answer", "휴학 신청은 8월 29일까지입니다. 신청은 https://www.ganada.ac.kr/form에서 합니다.");
        ReflectionTestUtils.setField(aiResponse, "sources",
                List.of(Map.of("source", "휴학 안내.pdf", "content", "가나대학 휴학 청크 본문")));
        when(fastApiClient.query(eq(QUESTION), anyInt(), anyString())).thenReturn(aiResponse);

        mockMvc.perform(post("/api/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"question\": \"" + QUESTION + "\", \"sessionKey\": \"" + SESSION_KEY + "\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.answer", startsWith("휴학 신청은 8월 29일까지입니다.")))
                .andExpect(jsonPath("$.data.links[0].url", is("https://www.ganada.ac.kr/form")))
                .andExpect(jsonPath("$.data.references").isArray())
                .andExpect(jsonPath("$.data.sources").doesNotExist());

        Long sessionId = chatSessionRepository.findBySessionKey(SESSION_KEY).orElseThrow().getId();
        mockMvc.perform(get("/api/chat/sessions/{id}", sessionId).header("X-Session-Key", SESSION_KEY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.messages[0].answer", startsWith("휴학 신청은 8월 29일까지입니다.")))
                .andExpect(jsonPath("$.data.messages[0].links[0].url", is("https://www.ganada.ac.kr/form")))
                .andExpect(jsonPath("$.data.messages[0].sources").doesNotExist());
    }
}
