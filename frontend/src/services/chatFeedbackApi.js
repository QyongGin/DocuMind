import { apiRequest } from './apiClient.js'

function createSessionHeaders(sessionKey) {
  return sessionKey ? { 'X-Session-Key': sessionKey } : {}
}

export async function updateChatFeedback(messageId, score, { sessionKey, auth = false } = {}) {
  return apiRequest(`/chat/messages/${messageId}/feedback`, {
    method: 'PUT',
    auth,
    headers: createSessionHeaders(sessionKey),
    body: { score },
  })
}
