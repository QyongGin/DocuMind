package com.documind.documind.domain.chat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;

import static org.junit.jupiter.api.Assertions.*;

/**
 * SSE 스트리밍 세션 임시 저장소 단위 테스트.
 */
class StreamSessionStoreTest {

    @Test
    @DisplayName("저장한 streamId는 한 번만 소비할 수 있다")
    void consumeById_removesSessionAfterFirstRead() {
        StreamSessionStore store = new StreamSessionStore(
                Clock.fixed(Instant.parse("2026-05-05T00:00:00Z"), ZoneId.of("UTC")),
                Duration.ofSeconds(30),
                100
        );

        String streamId = store.save(new StreamSessionSaveCommand("질문", 10L, "session-key", 5)).orElseThrow();

        StreamSessionData data = store.consumeById(streamId).orElseThrow();
        assertEquals("질문", data.question());
        assertEquals(10L, data.userId());
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

    @Test
    @DisplayName("TTL이 지나면 streamId는 소비되지 않는다")
    void consumeById_afterTtl_returnsEmpty() {
        MutableClock clock = new MutableClock(Instant.parse("2026-05-05T00:00:00Z"));
        StreamSessionStore store = new StreamSessionStore(clock, Duration.ofSeconds(30), 100);
        String streamId = store.save(new StreamSessionSaveCommand("질문", null, "session-key", 5)).orElseThrow();

        clock.advance(Duration.ofSeconds(31));

        assertTrue(store.consumeById(streamId).isEmpty());
    }

    @Test
    @DisplayName("최대 보관 수를 초과하면 streamId를 발급하지 않는다")
    void save_whenStoreIsFull_returnsEmpty() {
        StreamSessionStore store = new StreamSessionStore(
                Clock.fixed(Instant.parse("2026-05-05T00:00:00Z"), ZoneId.of("UTC")),
                Duration.ofSeconds(30),
                1
        );

        assertTrue(store.save(new StreamSessionSaveCommand("첫 질문", null, "session-key", 5)).isPresent());
        assertTrue(store.save(new StreamSessionSaveCommand("두 번째 질문", null, "session-key", 5)).isEmpty());
    }

    private static class MutableClock extends Clock {
        private Instant instant;

        MutableClock(Instant instant) {
            this.instant = instant;
        }

        void advance(Duration duration) {
            instant = instant.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneId.of("UTC");
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }
}
