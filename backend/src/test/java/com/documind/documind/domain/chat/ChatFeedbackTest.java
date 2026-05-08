package com.documind.documind.domain.chat;

import com.documind.documind.domain.auth.User;
import com.documind.documind.domain.auth.UserRepository;
import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import com.documind.documind.global.infra.fastapi.FastApiClient;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 채팅 답변 피드백 서비스 통합 테스트.
 * 등록, 수정, 소유권 검증, 세션 삭제 시 FK 정리를 검증한다.
 */
@SpringBootTest
@ActiveProfiles("test")
class ChatFeedbackTest {

    @Autowired
    private ChatService chatService;

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private ChatFeedbackRepository chatFeedbackRepository;

    @Autowired
    private UserRepository userRepository;

    // @MockitoBean: ChatService 의존성인 FastApiClient를 외부 호출 없이 컨텍스트에 주입한다.
    @MockitoBean
    private FastApiClient fastApiClient;

    private static final String SESSION_KEY = "feedback-session-key";

    private ChatSession session;
    private ChatMessage message;
    private User user;
    private ChatSession userSession;
    private ChatMessage userMessage;

    // 각 테스트마다 비로그인 세션과 로그인 사용자 세션을 준비한다.
    @BeforeEach
    void setUp() {
        session = chatSessionRepository.save(ChatSession.create(null, SESSION_KEY, "피드백 질문"));
        message = ChatMessage.create(session, "피드백 질문");
        message.complete("피드백 답변", "[]");
        chatMessageRepository.save(message);

        user = userRepository.save(User.create("feedback-admin", "hashed_password", User.Role.ADMIN));
        userSession = chatSessionRepository.save(ChatSession.create(user, null, "로그인 피드백 질문"));
        userMessage = ChatMessage.create(userSession, "로그인 피드백 질문");
        userMessage.complete("로그인 피드백 답변", "[]");
        chatMessageRepository.save(userMessage);
    }

    // FK 순서에 맞춰 피드백, 메시지, 세션, 사용자를 정리한다.
    @AfterEach
    void tearDown() {
        chatFeedbackRepository.deleteAll();
        chatMessageRepository.deleteAll();
        chatSessionRepository.deleteAll();
        userRepository.deleteAll();
    }

    @Test
    @DisplayName("비로그인 sessionKey로 답변 피드백을 등록한다")
    void updateFeedback_withSessionKey_createsFeedback() {
        ChatFeedbackResponse response = chatService.updateFeedback(
                message.getId(),
                null,
                SESSION_KEY,
                feedbackRequest(1)
        );

        assertEquals(message.getId(), response.getMessageId());
        assertEquals((byte) 1, response.getScore());
        assertTrue(chatFeedbackRepository.findByChatMessageId(message.getId()).isPresent());
    }

    @Test
    @DisplayName("같은 메시지에 다시 피드백하면 기존 점수를 수정한다")
    void updateFeedback_withExistingFeedback_updatesScore() {
        chatService.updateFeedback(message.getId(), null, SESSION_KEY, feedbackRequest(1));

        ChatFeedbackResponse response = chatService.updateFeedback(
                message.getId(),
                null,
                SESSION_KEY,
                feedbackRequest(-1)
        );

        assertEquals((byte) -1, response.getScore());
        assertEquals(1, chatFeedbackRepository.findAll().size());
    }

    @Test
    @DisplayName("로그인 사용자는 userId 소유 메시지에 피드백할 수 있다")
    void updateFeedback_withUserId_createsFeedback() {
        ChatFeedbackResponse response = chatService.updateFeedback(
                userMessage.getId(),
                user.getId(),
                null,
                feedbackRequest(1)
        );

        assertEquals(userMessage.getId(), response.getMessageId());
        assertEquals((byte) 1, response.getScore());
    }

    @Test
    @DisplayName("소유하지 않은 메시지에 피드백하면 404를 반환한다")
    void updateFeedback_withWrongOwner_throwsNotFound() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.updateFeedback(message.getId(), null, "wrong-key", feedbackRequest(1)));

        assertEquals(ErrorCode.CHAT_MESSAGE_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    @DisplayName("0점 피드백은 거부한다")
    void updateFeedback_withZeroScore_throwsBadRequest() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.updateFeedback(message.getId(), null, SESSION_KEY, feedbackRequest(0)));

        assertEquals(ErrorCode.INVALID_FEEDBACK_SCORE, ex.getErrorCode());
    }

    @Test
    @DisplayName("세션 상세 조회 응답에 저장된 피드백 점수를 포함한다")
    void getSessionDetail_withFeedback_includesFeedbackScore() {
        chatService.updateFeedback(message.getId(), null, SESSION_KEY, feedbackRequest(-1));

        ChatSessionDetailResponse detail = chatService.getSessionDetail(session.getId(), null, SESSION_KEY);

        assertEquals((byte) -1, detail.getMessages().get(0).getFeedbackScore());
    }

    @Test
    @DisplayName("세션 삭제 시 피드백을 먼저 삭제해 FK 오류가 발생하지 않는다")
    void deleteSession_withFeedback_deletesFeedbackAndSession() {
        chatService.updateFeedback(message.getId(), null, SESSION_KEY, feedbackRequest(1));

        chatService.deleteSession(session.getId(), null, SESSION_KEY);

        assertTrue(chatFeedbackRepository.findAll().isEmpty());
        assertTrue(chatMessageRepository.findByChatSessionIdOrderByCreatedAtAsc(session.getId()).isEmpty());
    }

    private ChatFeedbackRequest feedbackRequest(int score) {
        ChatFeedbackRequest request = new ChatFeedbackRequest();
        ReflectionTestUtils.setField(request, "score", score);
        return request;
    }
}
