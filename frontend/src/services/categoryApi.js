import { apiRequest } from './apiClient.js'

export async function listCategories() {
  return apiRequest('/categories', {
    method: 'GET',
  })
}

export async function createCategory(name) {
  return apiRequest('/categories', {
    method: 'POST',
    auth: true,
    body: { name },
  })
}
