import { apiRequest } from './apiClient.js'

export async function listDocuments() {
  return apiRequest('/documents', {
    method: 'GET',
    auth: true,
  })
}

export async function uploadDocument(file, { categoryId } = {}) {
  const formData = new FormData()
  formData.append('file', file)
  if (categoryId) {
    formData.append('categoryId', categoryId)
  }

  return apiRequest('/documents', {
    method: 'POST',
    auth: true,
    body: formData,
    timeoutMs: 0,
  })
}

export async function listDocumentChunks(id) {
  return apiRequest(`/documents/${id}/chunks`, {
    method: 'GET',
    auth: true,
  })
}

export async function deleteDocument(id) {
  return apiRequest(`/documents/${id}`, {
    method: 'DELETE',
    auth: true,
  })
}
