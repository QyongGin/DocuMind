import { env } from '../config/env.js'
import { getAccessToken } from './authStorage.js'

const DEFAULT_TIMEOUT_MS = 30000

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

  try {
    return await response.json()
  } catch {
    return null
  }
}

export async function apiRequest(path, options = {}) {
  const { body, headers = {}, auth = false, timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options
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

  const controller = new AbortController()
  const shouldApplyTimeout = !fetchOptions.signal && Number.isFinite(timeoutMs) && timeoutMs > 0
  const timeoutId = shouldApplyTimeout
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null

  let response
  try {
    response = await fetch(createUrl(path), {
      ...fetchOptions,
      headers: requestHeaders,
      // HttpOnly 쿠키(refresh-token)를 cross-origin 요청에도 전송하기 위해 credentials 포함
      credentials: 'include',
      signal: fetchOptions.signal ?? controller.signal,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('요청 시간이 초과되었습니다.')
    }
    throw new Error('서버와 통신하지 못했습니다.')
  } finally {
    if (timeoutId) {
      window.clearTimeout(timeoutId)
    }
  }

  const payload = await parseResponse(response)
  if (!response.ok || payload?.success === false) {
    if (response.status === 413) {
      throw new Error('업로드할 파일이 서버 허용 크기를 초과했습니다.')
    }
    if (response.status === 502 || response.status === 503 || response.status === 504) {
      throw new Error('백엔드 서버에 연결하지 못했습니다. Spring Boot 서버가 실행 중인지 확인해 주세요.')
    }
    throw new Error(payload?.message ?? '요청을 처리하지 못했습니다.')
  }

  return payload?.data ?? null
}
