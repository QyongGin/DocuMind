import { apiRequest } from './apiClient.js'

export async function listDocuments() {
  return apiRequest('/documents', {
    method: 'GET',
    auth: true,
  })
}

// 출처 정보(원래 주소·게시일·학년도)는 선택이다. 값이 있는 칸만 보낸다(#126)
export async function uploadDocument(file, { categoryId, sourceUrl, sourcePostedAt, academicYear } = {}) {
  const formData = new FormData()
  formData.append('file', file)
  const optionalFields = { categoryId, sourceUrl, sourcePostedAt, academicYear }
  Object.entries(optionalFields).forEach(([name, value]) => {
    const text = value == null ? '' : String(value).trim()
    if (text) {
      formData.append(name, text)
    }
  })

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

export async function getDocumentProgress(id) {
  return apiRequest(`/documents/${id}/progress`, {
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
