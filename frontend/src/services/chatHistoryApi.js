import { apiRequest } from './apiClient.js'

function createSessionHeaders(sessionKey) {
  return sessionKey ? { 'X-Session-Key': sessionKey } : {}
}

export async function listChatSessions({ sessionKey } = {}) {
  return apiRequest('/chat/sessions', {
    method: 'GET',
    headers: createSessionHeaders(sessionKey),
  })
}

export async function getChatSession(sessionId, { sessionKey } = {}) {
  return apiRequest(`/chat/sessions/${sessionId}`, {
    method: 'GET',
    headers: createSessionHeaders(sessionKey),
  })
}

export async function deleteChatSession(sessionId, { sessionKey } = {}) {
  return apiRequest(`/chat/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: createSessionHeaders(sessionKey),
  })
}
