package com.documind.documind.domain.chat;

import java.time.Instant;

/** POST /api/chat/stream/session으로 생성된 스트리밍 세션 데이터. 단일 소비 후 삭제된다. */
public record StreamSessionData(String question, String sessionKey, int topK, Instant createdAt) {}
