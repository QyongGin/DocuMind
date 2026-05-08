import { apiRequest } from './apiClient.js'

export async function getFeedbackStats() {
  return apiRequest('/admin/feedback-stats', {
    method: 'GET',
    auth: true,
  })
}
