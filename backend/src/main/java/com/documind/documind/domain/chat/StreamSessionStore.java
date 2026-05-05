package com.documind.documind.domain.chat;

import org.springframework.stereotype.Component;

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

    // streamId TTL: 세션 생성 후 GET 연결이 이 시간 내에 이루어지지 않으면 자동 만료
    private static final Duration TTL = Duration.ofSeconds(30);

    private final ConcurrentHashMap<String, StreamSessionData> store = new ConcurrentHashMap<>();

    /**
     * 스트리밍 파라미터를 저장하고 단일 사용 streamId를 발급한다.
     * 호출마다 만료된 항목을 제거해 메모리 누수를 방지한다.
     */
    public String save(String question, String sessionKey, int topK) {
        evictStale();
        String streamId = UUID.randomUUID().toString();
        store.put(streamId, new StreamSessionData(question, sessionKey, topK, Instant.now()));
        return streamId;
    }

    /**
     * streamId로 세션 데이터를 조회하고 저장소에서 즉시 삭제한다 (단일 소비).
     * 존재하지 않거나 만료된 경우 빈 Optional을 반환한다.
     */
    public Optional<StreamSessionData> consumeById(String streamId) {
        evictStale();
        return Optional.ofNullable(store.remove(streamId));
    }

    // TTL이 지난 항목을 일괄 제거한다
    private void evictStale() {
        Instant cutoff = Instant.now().minus(TTL);
        store.entrySet().removeIf(entry -> entry.getValue().createdAt().isBefore(cutoff));
    }
}
