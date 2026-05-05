package com.documind.documind.domain.chat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * SSE 스트리밍 세션 임시 저장소 단위 테스트.
 */
class StreamSessionStoreTest {

    @Test
    @DisplayName("저장한 streamId는 한 번만 소비할 수 있다")
    void consumeById_removesSessionAfterFirstRead() {
        StreamSessionStore store = new StreamSessionStore();

        String streamId = store.save("질문", "session-key", 5);

        StreamSessionData data = store.consumeById(streamId).orElseThrow();
        assertEquals("질문", data.question());
        assertEquals("session-key", data.sessionKey());
        assertEquals(5, data.topK());
        assertTrue(store.consumeById(streamId).isEmpty());
    }

    @Test
    @DisplayName("존재하지 않는 streamId는 빈 Optional을 반환한다")
    void consumeById_withUnknownId_returnsEmpty() {
        StreamSessionStore store = new StreamSessionStore();

        assertTrue(store.consumeById("unknown").isEmpty());
    }
}
