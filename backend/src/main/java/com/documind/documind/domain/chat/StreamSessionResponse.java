package com.documind.documind.domain.chat;

/** POST /api/chat/stream/session 응답 DTO. streamId로 SSE 스트리밍 연결을 식별한다. */
public record StreamSessionResponse(String streamId) {}
