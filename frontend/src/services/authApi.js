import { apiRequest } from './apiClient.js'
import { clearTokens, saveTokens } from './authStorage.js'

export async function login({ username, password }) {
  const data = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username, password },
  })
  // 응답 body에는 accessToken만 있다. refreshToken은 서버가 HttpOnly 쿠키로 설정한다
  saveTokens({ accessToken: data.accessToken })
  return data
}

export async function logout() {
  try {
    await apiRequest('/auth/logout', {
      method: 'POST',
      auth: true,
    })
  } finally {
    // 서버가 refresh-token 쿠키를 만료시키고, 클라이언트는 access token만 제거한다
    clearTokens()
  }
}

export async function reissueAccessToken() {
  let accessToken
  try {
    // refresh token은 HttpOnly 쿠키로 자동 전송된다 — 헤더에 직접 포함하지 않는다
    accessToken = await apiRequest('/auth/reissue', { method: 'POST' })
  } catch (error) {
    clearTokens()
    throw error
  }

  if (typeof accessToken !== 'string' || !accessToken) {
    clearTokens()
    throw new Error('세션이 만료되었습니다. 다시 로그인해 주세요.')
  }

  saveTokens({ accessToken })
  return accessToken
}
