package com.documind.documind.domain.chat;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import com.documind.documind.global.infra.fastapi.FastApiQueryResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 채팅 이력 서비스 통합 테스트.
 * @SpringBootTest: 전체 애플리케이션 컨텍스트를 로드해 실제 DB(H2 인메모리) 기반으로 검증한다.
 * @ActiveProfiles: 테스트 전용 application-test.yaml 설정을 로드한다.
 * 테스트 공통 설정은 src/test/resources/application-test.yaml에서 관리한다.
 */
@SpringBootTest
@ActiveProfiles("test")
class ChatHistoryTest {

    @Autowired
    private ChatService chatService;

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private UserRepository userRepository;

    // @MockitoBean: 질의응답 저장 테스트에서 FastAPI 외부 호출을 Mock으로 대체한다.
    @MockitoBean
    private FastApiClient fastApiClient;

    // 비로그인 플로우용
    private ChatSession session;
    private static final String SESSION_KEY = "test-session-uuid-1234";

    // 로그인 플로우용
    private User testUser;
    private ChatSession userSession;

    // 각 테스트 실행 전 세션과 메시지를 생성해 독립적인 테스트 환경을 보장
    @BeforeEach
    void setUp() {
        // 비로그인 세션 + 메시지
        session = chatSessionRepository.save(ChatSession.create(null, SESSION_KEY, "테스트 질문"));
        ChatMessage message = ChatMessage.create(session, "테스트 질문");
        message.complete("테스트 답변", "[{\"source\":\"test.pdf\"}]");
        chatMessageRepository.save(message);

        // 로그인 사용자 세션 + 메시지. User.create()로 테스트 전용 사용자를 직접 생성한다
        testUser = userRepository.save(User.create("testadmin", "hashed_password", User.Role.ADMIN));
        userSession = chatSessionRepository.save(ChatSession.create(testUser, null, "로그인 테스트 질문"));
        ChatMessage userMessage = ChatMessage.create(userSession, "로그인 테스트 질문");
        userMessage.complete("로그인 테스트 답변", "[]");
        chatMessageRepository.save(userMessage);
    }

    // 각 테스트 실행 후 생성된 데이터를 정리해 테스트 간 간섭을 방지
    @AfterEach
    void tearDown() {
        chatMessageRepository.deleteAll();
        chatSessionRepository.deleteAll();
        userRepository.deleteAll();
    }

    // ── 비로그인(sessionKey 기반) 플로우 ──────────────────────────────────

    @Test
    @DisplayName("유효한 sessionKey로 목록 조회 시 단일 세션 반환")
    void getSessions_withValidSessionKey_returnsSingleSession() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(null, SESSION_KEY);

        assertEquals(1, result.size());
        assertEquals(session.getId(), result.get(0).getSessionId());
        assertEquals("테스트 질문", result.get(0).getTitle());
    }

    @Test
    @DisplayName("sessionKey가 null이면 빈 리스트 반환")
    void getSessions_withNullSessionKey_returnsEmptyList() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(null, null);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("존재하지 않는 sessionKey로 조회 시 빈 리스트 반환")
    void getSessions_withUnknownSessionKey_returnsEmptyList() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(null, "없는-키");

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("유효한 sessionKey로 상세 조회 시 세션과 메시지 반환")
    void getSessionDetail_withValidSessionKey_returnsSessionWithMessages() {
        ChatSessionDetailResponse result = chatService.getSessionDetail(session.getId(), null, SESSION_KEY);

        assertEquals(session.getId(), result.getSessionId());
        assertEquals("테스트 질문", result.getTitle());
        assertEquals(1, result.getMessages().size());

        ChatMessageResponse msg = result.getMessages().get(0);
        assertEquals("테스트 질문", msg.getQuestion());
        assertEquals("테스트 답변", msg.getAnswer());
        // H2 JSON 컬럼 타입과 JPA String 매핑의 호환성 차이로 sourceDocs가 null로 읽힐 수 있음.
        // deserializeSources()가 null 입력 시 빈 리스트로 폴백하는 것을 검증 (NPE 발생 않음)
        assertNotNull(msg.getSources());
    }

    @Test
    @DisplayName("잘못된 sessionKey로 상세 조회 시 404 반환")
    void getSessionDetail_withWrongSessionKey_throwsNotFound() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(session.getId(), null, "틀린-키"));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("존재하지 않는 sessionId로 상세 조회 시 404 반환")
    void getSessionDetail_withNonExistentSessionId_throwsNotFound() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(99999L, null, SESSION_KEY));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("sessionKey가 null이면 상세 조회 시 404 반환")
    void getSessionDetail_withNullSessionKey_throwsNotFound() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(session.getId(), null, null));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("유효한 sessionKey로 삭제 시 세션과 메시지가 함께 삭제됨")
    void deleteSession_withValidSessionKey_deletesSessionAndMessages() {
        chatService.deleteSession(session.getId(), null, SESSION_KEY);

        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(session.getId(), null, SESSION_KEY));
        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
        assertTrue(chatMessageRepository.findByChatSessionIdOrderByCreatedAtAsc(session.getId()).isEmpty());
    }

    @Test
    @DisplayName("잘못된 sessionKey로 삭제 시 404 반환 및 세션 유지")
    void deleteSession_withWrongSessionKey_throwsNotFoundAndKeepsSession() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.deleteSession(session.getId(), null, "틀린-키"));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
        assertTrue(chatSessionRepository.findById(session.getId()).isPresent());
    }

    @Test
    @DisplayName("존재하지 않는 sessionId로 삭제 시 404 반환")
    void deleteSession_withNonExistentSessionId_throwsNotFound() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.deleteSession(99999L, null, SESSION_KEY));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    // ── 로그인 사용자(userId 기반) 플로우 ──────────────────────────────────

    @Test
    @DisplayName("로그인 사용자의 userId로 목록 조회 시 전체 세션 반환")
    void getSessions_withUserId_returnsUserSessions() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(testUser.getId(), null);

        assertEquals(1, result.size());
        assertEquals(userSession.getId(), result.get(0).getSessionId());
        assertEquals("로그인 테스트 질문", result.get(0).getTitle());
    }

    @Test
    @DisplayName("로그인 사용자의 userId로 상세 조회 시 세션과 메시지 반환")
    void getSessionDetail_withUserId_returnsSessionWithMessages() {
        ChatSessionDetailResponse result = chatService.getSessionDetail(userSession.getId(), testUser.getId(), null);

        assertEquals(userSession.getId(), result.getSessionId());
        assertEquals(1, result.getMessages().size());
        assertEquals("로그인 테스트 질문", result.getMessages().get(0).getQuestion());
        assertNotNull(result.getMessages().get(0).getSources());
    }

    @Test
    @DisplayName("잘못된 userId로 상세 조회 시 404 반환")
    void getSessionDetail_withWrongUserId_throwsNotFound() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(userSession.getId(), 99999L, null));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("로그인 사용자의 userId로 삭제 시 세션과 메시지가 함께 삭제됨")
    void deleteSession_withUserId_deletesSessionAndMessages() {
        chatService.deleteSession(userSession.getId(), testUser.getId(), null);

        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(userSession.getId(), testUser.getId(), null));
        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
        assertTrue(chatMessageRepository.findByChatSessionIdOrderByCreatedAtAsc(userSession.getId()).isEmpty());
    }

    @Test
    @DisplayName("로그인 사용자 질문 저장 시 sessionKey가 아니라 userId 소유 세션으로 저장")
    void chat_withUserId_createsUserOwnedSession() {
        when(fastApiClient.query(eq("로그인 새 질문"), eq(3), anyString()))
                .thenReturn(queryResponse("로그인 새 답변"));

        ChatResponse response = chatService.chat(chatRequest("로그인 새 질문", "guest-key"), testUser.getId());

        ChatSessionDetailResponse userOwnedSession = chatService.getSessionDetail(
                response.getSessionId(),
                testUser.getId(),
                null
        );
        assertEquals("로그인 새 질문", userOwnedSession.getTitle());
        assertEquals("로그인 새 답변", userOwnedSession.getMessages().get(0).getAnswer());

        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(response.getSessionId(), null, "guest-key"));
        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    private ChatRequest chatRequest(String question, String sessionKey) {
        ChatRequest request = new ChatRequest();
        ReflectionTestUtils.setField(request, "question", question);
        ReflectionTestUtils.setField(request, "sessionKey", sessionKey);
        return request;
    }

    private FastApiQueryResponse queryResponse(String answer) {
        FastApiQueryResponse response = new FastApiQueryResponse();
        ReflectionTestUtils.setField(response, "answer", answer);
        ReflectionTestUtils.setField(response, "sources", List.of(Map.of("source", "test.pdf")));
        return response;
    }
}
