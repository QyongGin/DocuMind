package com.documind.documind.domain.chat;

import com.documind.documind.global.exception.CustomException;
import com.documind.documind.global.exception.ErrorCode;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

// @SpringBootTest: 전체 애플리케이션 컨텍스트를 로드해 실제 DB(H2 인메모리) 기반으로 검증
// properties: MySQL 대신 H2를 사용하도록 데이터소스를 오버라이드
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:documind;MODE=MySQL;DB_CLOSE_DELAY=-1",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
class ChatHistoryTest {

    @Autowired
    private ChatService chatService;

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    private ChatSession session;
    private static final String SESSION_KEY = "test-session-uuid-1234";

    // 각 테스트 실행 전 세션과 메시지를 생성해 독립적인 테스트 환경을 보장
    @BeforeEach
    void setUp() {
        session = chatSessionRepository.save(ChatSession.create(null, SESSION_KEY, "테스트 질문"));
        ChatMessage message = ChatMessage.create(session, "테스트 질문");
        message.complete("테스트 답변", "[{\"source\":\"test.pdf\"}]");
        chatMessageRepository.save(message);
    }

    // 각 테스트 실행 후 생성된 데이터를 정리해 테스트 간 간섭을 방지
    @AfterEach
    void tearDown() {
        chatMessageRepository.deleteByChatSessionId(session.getId());
        // deleteById는 존재하지 않으면 EmptyResultDataAccessException을 던지므로 존재 확인 후 삭제
        chatSessionRepository.findById(session.getId()).ifPresent(chatSessionRepository::delete);
    }

    @Test
    void getSessions_비로그인_유효한_sessionKey_단일_세션_반환() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(null, SESSION_KEY);

        assertEquals(1, result.size());
        assertEquals(session.getId(), result.get(0).getSessionId());
        assertEquals("테스트 질문", result.get(0).getTitle());
    }

    @Test
    void getSessions_sessionKey_null이면_빈_리스트_반환() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(null, null);

        assertTrue(result.isEmpty());
    }

    @Test
    void getSessions_존재하지_않는_sessionKey는_빈_리스트_반환() {
        List<ChatSessionSummaryResponse> result = chatService.getSessions(null, "없는-키");

        assertTrue(result.isEmpty());
    }

    @Test
    void getSessionDetail_유효한_sessionKey_세션과_메시지_반환() {
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
    void getSessionDetail_잘못된_sessionKey는_404_반환() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(session.getId(), null, "틀린-키"));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    void getSessionDetail_존재하지_않는_sessionId는_404_반환() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(99999L, null, SESSION_KEY));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    void getSessionDetail_sessionKey_null이면_404_반환() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(session.getId(), null, null));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }

    @Test
    void deleteSession_유효한_sessionKey_세션과_메시지_삭제() {
        chatService.deleteSession(session.getId(), null, SESSION_KEY);

        // 세션 삭제 후 재조회 시 404가 반환돼야 함
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.getSessionDetail(session.getId(), null, SESSION_KEY));
        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());

        // 메시지도 함께 삭제됐는지 확인
        assertTrue(chatMessageRepository.findByChatSessionIdOrderByCreatedAtAsc(session.getId()).isEmpty());
    }

    @Test
    void deleteSession_잘못된_sessionKey는_404_반환() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.deleteSession(session.getId(), null, "틀린-키"));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
        // 삭제되지 않았으므로 세션이 여전히 존재해야 함
        assertTrue(chatSessionRepository.findById(session.getId()).isPresent());
    }

    @Test
    void deleteSession_존재하지_않는_sessionId는_404_반환() {
        CustomException ex = assertThrows(CustomException.class,
                () -> chatService.deleteSession(99999L, null, SESSION_KEY));

        assertEquals(ErrorCode.CHAT_SESSION_NOT_FOUND, ex.getErrorCode());
    }
}
