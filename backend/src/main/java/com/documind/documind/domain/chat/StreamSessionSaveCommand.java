package com.documind.documind.domain.chat;

/**
 * POST /api/chat/stream/session에서 임시 저장소에 보관할 스트리밍 요청 정보.
 */
record StreamSessionSaveCommand(String question, Long userId, String sessionKey, int topK) {
}
