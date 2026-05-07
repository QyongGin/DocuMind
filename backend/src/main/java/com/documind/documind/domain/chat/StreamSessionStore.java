package com.documind.documind.domain.chat;

import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * SSE 스트리밍 세션 임시 저장소.
 * POST /api/chat/stream/session에서 발급된 streamId와 질문 파라미터를 30초간 보관한다.
 * GET /api/chat/stream/{streamId} 호출 시 단일 소비(remove)하여 재사용을 방지한다.
 */
@Component
public class StreamSessionStore {

    // 기본 TTL: 세션 생성 후 GET 연결이 이 시간 내에 이루어지지 않으면 자동 만료
    private static final Duration DEFAULT_TTL = Duration.ofSeconds(30);
    // 기본 최대 보관 수: 비정상 요청 폭주 시 JVM 메모리 사용량을 제한한다
    private static final int DEFAULT_MAX_ENTRIES = 1000;

    private final Clock clock;
    private final Duration ttl;
    private final int maxEntries;
    private final ConcurrentHashMap<String, StreamSessionData> store = new ConcurrentHashMap<>();

    /**
     * 운영용 생성자.
     * TTL과 최대 보관 수는 환경변수로 조정 가능하며, 기본값은 30초·1000건이다.
     */
    @Autowired
    public StreamSessionStore(
            @Value("${chat.stream-session-ttl:30s}") Duration ttl,
            @Value("${chat.stream-session-max-entries:1000}") int maxEntries
    ) {
        this(Clock.systemUTC(), ttl, maxEntries);
    }

    StreamSessionStore() {
        this(Clock.systemUTC(), DEFAULT_TTL, DEFAULT_MAX_ENTRIES);
    }

    StreamSessionStore(Clock clock, Duration ttl, int maxEntries) {
        if (ttl == null || ttl.isZero() || ttl.isNegative()) {
            throw new IllegalArgumentException("ttl은 양수여야 합니다.");
        }
        if (maxEntries < 1) {
            throw new IllegalArgumentException("maxEntries는 1 이상이어야 합니다.");
        }
        this.clock = clock;
        this.ttl = ttl;
        this.maxEntries = maxEntries;
    }

    /**
     * 스트리밍 파라미터를 저장하고 단일 사용 streamId를 발급한다.
     * 호출마다 만료된 항목을 제거해 메모리 누수를 방지한다.
     * 저장소가 가득 찬 경우 빈 Optional을 반환해 호출자가 429로 응답하도록 한다.
     */
    public synchronized Optional<String> save(StreamSessionSaveCommand command) {
        evictStale();
        if (store.size() >= maxEntries) {
            return Optional.empty();
        }
        String streamId = UUID.randomUUID().toString();
        store.put(streamId, new StreamSessionData(
                command.question(),
                command.userId(),
                command.sessionKey(),
                command.topK(),
                clock.instant()
        ));
        return Optional.of(streamId);
    }

    /**
     * streamId로 세션 데이터를 조회하고 저장소에서 즉시 삭제한다 (단일 소비).
     * 존재하지 않거나 만료된 경우 빈 Optional을 반환한다.
     */
    public Optional<StreamSessionData> consumeById(String streamId) {
        evictStale();
        StreamSessionData data = store.remove(streamId);
        if (data == null || isExpired(data, clock.instant())) {
            return Optional.empty();
        }
        return Optional.of(data);
    }

    // TTL이 지난 항목을 일괄 제거한다
    private void evictStale() {
        Instant now = clock.instant();
        store.entrySet().removeIf(entry -> isExpired(entry.getValue(), now));
    }

    private boolean isExpired(StreamSessionData data, Instant now) {
        return !data.createdAt().plus(ttl).isAfter(now);
    }
}
