import { apiRequest } from './apiClient.js'

// 관리자 개발자 모드(ADR-0050 결정 6, ADR-0052): 답 하나의 원문 답, 화면 처리 내역, 근거 후보, 처리 기록
export async function getChatDevInfo(messageId) {
  return apiRequest(`/admin/chat-messages/${messageId}/dev-info`, {
    method: 'GET',
    auth: true,
  })
}
