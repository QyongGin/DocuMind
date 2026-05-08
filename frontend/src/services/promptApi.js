import { apiRequest } from './apiClient.js'

export async function getPromptConfig() {
  return apiRequest('/admin/prompt', {
    method: 'GET',
    auth: true,
  })
}

export async function updatePromptConfig(systemPrompt) {
  return apiRequest('/admin/prompt', {
    method: 'PUT',
    auth: true,
    body: { systemPrompt },
  })
}
