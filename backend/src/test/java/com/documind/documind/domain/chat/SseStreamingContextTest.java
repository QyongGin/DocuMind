package com.documind.documind.domain.chat;

import com.documind.documind.domain.document.DocumentRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * SSE 스트림 상태 객체의 완료·중단 저장 흐름을 검증하는 단위 테스트.
 */
class SseStreamingContextTest {

    private static final Long MESSAGE_ID = 1L;
    private static final Long SESSION_ID = 10L;

    private final SseEmitter emitter = mock(SseEmitter.class);
    private final ChatStreamPersistenceService persistenceService = mock(ChatStreamPersistenceService.class);
    private final SourceDocumentMetadataEnricher sourceDocumentMetadataEnricher = mock(SourceDocumentMetadataEnricher.class);
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final DocumentRepository documentRepository = mock(DocumentRepository.class);

    @Test
    @DisplayName("done 이벤트 수신 시 완성 답변을 저장하고 이후 연결 종료에서는 부분 답변을 저장하지 않음")
    void onToken_withDoneEvent_savesFinalAnswerOnly() {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"안녕\"}");
        context.onToken("{\"token\":\"하세요\"}");
        context.onToken("{\"done\":true,\"sources\":[{\"source\":\"guide.pdf\"}]}");
        context.onClientDisconnect();

        verify(persistenceService).completeMessage(
                eq(MESSAGE_ID),
                eq(SESSION_ID),
                eq("안녕하세요"),
                eq("안녕하세요"),
                eq("[{\"source\":\"guide.pdf\"}]"),
                eq(false)
        );
        verify(persistenceService, never()).savePartialAnswer(any(), any());
    }

    @Test
    @DisplayName("클라이언트 연결 종료 시 FastAPI 구독을 취소하고 누적된 부분 답변을 저장함")
    void onClientDisconnect_savesPartialAnswerAndDisposesSubscription() {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);

        context.onToken("{\"token\":\"부분\"}");
        context.onToken("{\"token\":\"답변\"}");
        context.onClientDisconnect();

        verify(subscription).dispose();
        verify(persistenceService).savePartialAnswer(MESSAGE_ID, "부분답변");
        verify(persistenceService, never()).completeMessage(any(), any(), any(), any(), any(), anyBoolean());
    }

    @Test
    @DisplayName("토큰 전송 실패 시 안전 오류 답변 대신 누적된 부분 답변을 저장함")
    void onToken_withSendFailure_savesPartialAnswer() throws Exception {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);
        doThrow(new IOException("broken pipe"))
                .when(emitter)
                .send(any(SseEmitter.SseEventBuilder.class));

        context.onToken("{\"token\":\"부분\"}");

        verify(subscription).dispose();
        verify(persistenceService).savePartialAnswer(MESSAGE_ID, "부분");
        verify(persistenceService, never()).completeMessage(any(), any(), any(), any(), any(), anyBoolean());
        verify(emitter).complete();
    }

    @Test
    @DisplayName("done 이벤트에 answer가 포함되면 누적 버퍼보다 answer 값을 우선 저장함")
    void onToken_withDoneAnswer_usesAnswerField() {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"검색\"}");
        context.onToken("{\"done\":true,\"answer\":\"검색 결과가 없습니다.\",\"sources\":[]}");

        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                "검색 결과가 없습니다.",
                "검색 결과가 없습니다.",
                "[]",
                false
        );
    }

    @Test
    @DisplayName("done 이벤트에서 출처 번호를 지운 화면용 답을 저장·전송하고 모델 원문은 원문 칸에 저장함")
    void onToken_withCitation_savesScreenAnswerAndRawAnswer() throws Exception {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"휴학 신청은 8월 29일까지입니다.\"}");
        context.onToken("{\"token\":\"\\n\\n[출처 1]\"}");
        context.onToken("{\"done\":true,\"sources\":[]}");

        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                "휴학 신청은 8월 29일까지입니다.",
                "휴학 신청은 8월 29일까지입니다.\n\n[출처 1]",
                "[]",
                false
        );
        verify(emitter, times(3)).send(any(SseEmitter.SseEventBuilder.class));
    }

    @Test
    @DisplayName("흐르는 토큰에서 출처 번호를 걸러 보내고(번호 중간에서 끊겨 와도), 원문은 그대로 쌓아 저장함")
    void onToken_filtersCitationsFromStreamedTokens() throws Exception {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"신청은 [참고] 메뉴에서 합니다.\"}");
        context.onToken("{\"token\":\" [\"}");
        context.onToken("{\"token\":\"출처\"}");
        context.onToken("{\"token\":\" 2]\"}");
        context.onToken("{\"done\":true,\"sources\":[]}");

        ArgumentCaptor<SseEmitter.SseEventBuilder> events = ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
        verify(emitter, times(3)).send(events.capture());
        String streamed = events.getAllValues().subList(0, 2).stream().map(SseStreamingContextTest::dataOf)
                .collect(java.util.stream.Collectors.joining());
        assertTrue(streamed.contains("신청은 [참고] 메뉴에서 합니다."), streamed);
        assertFalse(streamed.contains("출처"), streamed);
        verify(persistenceService).completeMessage(MESSAGE_ID, SESSION_ID, "신청은 [참고] 메뉴에서 합니다.",
                "신청은 [참고] 메뉴에서 합니다. [출처 2]", "[]", false);
    }

    @Test
    @DisplayName("done 이벤트의 처리 기록은 답을 저장한 뒤 따로 저장하고, 브라우저로 보내는 done 이벤트에는 넣지 않음")
    void onToken_withTrace_savesTraceAfterAnswerAndKeepsItFromBrowser() throws Exception {
        SseStreamingContext context = createContext();

        context.onToken("{\"token\":\"휴학 신청은 8월 29일까지입니다.\"}");
        context.onToken("{\"done\":true,\"sources\":[],\"trace\":{\"prompt\":\"[검색 근거] 가나대학\","
                + "\"seconds\":{\"total\":1.5}}}");

        var order = inOrder(persistenceService);
        order.verify(persistenceService).completeMessage(eq(MESSAGE_ID), eq(SESSION_ID), any(), any(), any(), anyBoolean());
        order.verify(persistenceService).saveTrace(MESSAGE_ID,
                "{\"prompt\":\"[검색 근거] 가나대학\",\"seconds\":{\"total\":1.5}}");
        ArgumentCaptor<SseEmitter.SseEventBuilder> events = ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
        verify(emitter, times(2)).send(events.capture());
        String done = dataOf(events.getAllValues().get(1));
        assertTrue(done.contains("\"answer\":\"휴학 신청은 8월 29일까지입니다.\""), done);
        assertFalse(done.contains("trace") || done.contains("검색 근거"), done);
    }

    @Test
    @DisplayName("검색 후보는 대화 기록에 저장하고, 브라우저로 보내는 done 이벤트에는 넣지 않음")
    void onToken_keepsSourcesFromBrowserButStoresThem() throws Exception {
        SseStreamingContext context = createContext();

        context.onToken("{\"done\":true,\"answer\":\"휴학 신청은 8월 29일까지입니다.\","
                + "\"sources\":[{\"source\":\"휴학 안내.pdf\",\"content\":\"가나대학 휴학 청크 본문\"}]}");

        verify(persistenceService).completeMessage(eq(MESSAGE_ID), eq(SESSION_ID), any(), any(),
                eq("[{\"source\":\"휴학 안내.pdf\",\"content\":\"가나대학 휴학 청크 본문\"}]"), eq(false));
        ArgumentCaptor<SseEmitter.SseEventBuilder> events = ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
        verify(emitter).send(events.capture());
        String done = dataOf(events.getValue());
        assertTrue(done.contains("\"answer\":\"휴학 신청은 8월 29일까지입니다.\""), done);
        assertFalse(done.contains("sources") || done.contains("청크 본문"), done);
    }

    @Test
    @DisplayName("거절 문장만 나간 답은 못 답한 질문으로 표시해 저장하고, 일부만 없는 답은 표시하지 않음")
    void onToken_marksRefusalOnlyAnswer() {
        SseStreamingContext refusal = createContext();
        refusal.onToken("{\"done\":true,\"answer\":\"학교 홈페이지 안내에서 찾지 못했습니다.\",\"sources\":[]}");
        verify(persistenceService).completeMessage(MESSAGE_ID, SESSION_ID, "학교 홈페이지 안내에서 찾지 못했습니다.",
                "학교 홈페이지 안내에서 찾지 못했습니다.", "[]", true);

        SseStreamingContext partial = createContext();
        partial.onToken("{\"done\":true,\"answer\":\"통학버스는 20분 앞당겨 운행됩니다. 요금은 학교 홈페이지 안내에서 찾지 못했습니다.\","
                + "\"sources\":[]}");
        verify(persistenceService).completeMessage(eq(MESSAGE_ID), eq(SESSION_ID),
                eq("통학버스는 20분 앞당겨 운행됩니다. 요금은 학교 홈페이지 안내에서 찾지 못했습니다."), any(), any(), eq(false));
    }

    @Test
    @DisplayName("처리 기록 저장이 실패해도 done 이벤트를 보내고 스트림을 정상 종료함")
    void onToken_whenTraceSaveFails_stillCompletesStream() throws Exception {
        SseStreamingContext context = createContext();
        doThrow(new RuntimeException("db down")).when(persistenceService).saveTrace(any(), any());

        context.onToken("{\"done\":true,\"answer\":\"휴학 신청은 8월 29일까지입니다.\",\"sources\":[],"
                + "\"trace\":{\"prompt\":\"P\"}}");

        verify(persistenceService).completeMessage(eq(MESSAGE_ID), eq(SESSION_ID), any(), any(), any(), anyBoolean());
        ArgumentCaptor<SseEmitter.SseEventBuilder> events = ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
        verify(emitter).send(events.capture());
        String sent = dataOf(events.getValue());
        assertTrue(sent.contains("\"done\":true") && !sent.contains("error"), sent);  // 오류 이벤트가 아닌 정상 done
        verify(emitter).complete();
    }

    @Test
    @DisplayName("처리 기록이 없는 done 이벤트(옛 AI 서버)는 기록을 저장하지 않음")
    void onToken_withoutTrace_savesNoTrace() {
        SseStreamingContext context = createContext();

        context.onToken("{\"done\":true,\"answer\":\"검색 결과가 없습니다.\",\"sources\":[]}");

        verify(persistenceService, never()).saveTrace(any(), any());
    }

    @Test
    @DisplayName("upstream 오류 발생 시 안전 오류 답변을 저장하고 스트림을 종료함")
    void onUpstreamError_savesSafeErrorAnswerAndDisposesSubscription() throws Exception {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);

        context.onUpstreamError(new RuntimeException("boom"));

        verify(subscription).dispose();
        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                SseStreamingContext.UPSTREAM_ERROR_MESSAGE,
                SseStreamingContext.UPSTREAM_ERROR_MESSAGE,
                "[]",
                false
        );
        verify(persistenceService, never()).savePartialAnswer(any(), any());
        verify(emitter).send(any(SseEmitter.SseEventBuilder.class));
        verify(emitter).complete();
    }

    @Test
    @DisplayName("깨진 JSON 수신 시 안전 오류 답변을 저장하고 스트림을 종료함")
    void onToken_withMalformedJson_savesSafeErrorAnswerAndDisposesSubscription() throws Exception {
        Disposable subscription = mock(Disposable.class);
        SseStreamingContext context = createContext();
        context.attachSubscription(subscription);

        context.onToken("{bad json");

        verify(subscription).dispose();
        verify(persistenceService).completeMessage(
                MESSAGE_ID,
                SESSION_ID,
                SseStreamingContext.STREAM_ERROR_MESSAGE,
                SseStreamingContext.STREAM_ERROR_MESSAGE,
                "[]",
                false
        );
        verify(persistenceService, never()).savePartialAnswer(any(), any());
        verify(emitter).send(any(SseEmitter.SseEventBuilder.class));
        verify(emitter).complete();
    }

    private static String dataOf(SseEmitter.SseEventBuilder event) {
        return event.build().stream().map(part -> String.valueOf(part.getData())).collect(java.util.stream.Collectors.joining());
    }

    private SseStreamingContext createContext() {
        when(sourceDocumentMetadataEnricher.enrich(any()))
                .thenAnswer(invocation -> invocation.getArgument(0));
        return new SseStreamingContext(
                emitter,
                MESSAGE_ID,
                SESSION_ID,
                objectMapper,
                persistenceService,
                sourceDocumentMetadataEnricher,
                new ScreenAnswerMaker(documentRepository, "학교 홈페이지 안내에서 찾지 못했습니다.",
                        "학과, 학년도, 학기를 넣어 다시 질문하기", "교내 전화번호 안내", "https://www.ganada.ac.kr/phone")
        );
    }
}
