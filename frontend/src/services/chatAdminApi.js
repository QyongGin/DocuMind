import { apiRequest } from './apiClient.js'

// 관리자 개발자 모드(ADR-0050 결정 6, ADR-0052): 못 답한 질문 목록, 답 하나의 원문 답·화면 처리 내역·근거 후보·처리 기록
export async function getUnansweredQuestions({ page = 0, size = 20 } = {}) {
  return apiRequest(`/admin/chat-messages/unanswered?page=${page}&size=${size}`, {
    method: 'GET',
    auth: true,
  })
}

export async function getChatDevInfo(messageId) {
  return apiRequest(`/admin/chat-messages/${messageId}/dev-info`, {
    method: 'GET',
    auth: true,
  })
}
