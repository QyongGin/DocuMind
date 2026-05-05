import { env } from '../config/env.js'
import { getAccessToken } from './authStorage.js'

function createUrl(path) {
  const normalizedBase = env.apiBaseUrl.replace(/\/$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizedBase}${normalizedPath}`
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    return null
  }

  return response.json()
}

export async function apiRequest(path, options = {}) {
  const { body, headers = {}, auth = false, ...fetchOptions } = options
  const requestHeaders = {
    ...headers,
  }

  // FormData는 Content-Type(boundary 포함)을 브라우저가 자동 설정한다 — 직접 지정하면 boundary가 누락돼 서버 파싱 실패
  if (body !== undefined && !(body instanceof FormData)) {
    requestHeaders['Content-Type'] = 'application/json'
  }

  if (auth) {
    const accessToken = getAccessToken()
    if (accessToken) {
      requestHeaders.Authorization = `Bearer ${accessToken}`
    }
  }

  const response = await fetch(createUrl(path), {
    ...fetchOptions,
    headers: requestHeaders,
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  })

  const payload = await parseResponse(response)
  if (!response.ok || payload?.success === false) {
    throw new Error(payload?.message ?? '요청을 처리하지 못했습니다.')
  }

  return payload?.data ?? null
}
