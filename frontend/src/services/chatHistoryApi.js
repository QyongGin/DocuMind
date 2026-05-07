import { apiRequest } from './apiClient.js'

function createSessionHeaders(sessionKey) {
  return sessionKey ? { 'X-Session-Key': sessionKey } : {}
}

export async function listChatSessions({ sessionKey, auth = false } = {}) {
  return apiRequest('/chat/sessions', {
    method: 'GET',
    auth,
    headers: createSessionHeaders(sessionKey),
  })
}

export async function getChatSession(sessionId, { sessionKey, auth = false } = {}) {
  return apiRequest(`/chat/sessions/${sessionId}`, {
    method: 'GET',
    auth,
    headers: createSessionHeaders(sessionKey),
  })
}

export async function deleteChatSession(sessionId, { sessionKey, auth = false } = {}) {
  return apiRequest(`/chat/sessions/${sessionId}`, {
    method: 'DELETE',
    auth,
    headers: createSessionHeaders(sessionKey),
  })
}
