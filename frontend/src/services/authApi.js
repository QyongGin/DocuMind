import { apiRequest } from './apiClient.js'
import { clearTokens, getRefreshToken, saveTokens } from './authStorage.js'

export async function login({ username, password }) {
  const tokens = await apiRequest('/auth/login', {
    method: 'POST',
    body: { username, password },
  })

  saveTokens(tokens)
  return tokens
}

export async function logout() {
  try {
    await apiRequest('/auth/logout', {
      method: 'POST',
      auth: true,
    })
  } finally {
    clearTokens()
  }
}

export async function verifyAccessToken() {
  // 서버가 JWT 서명·만료·권한을 검증한다. 실패 시 apiRequest가 예외를 던진다.
  await apiRequest('/auth/verify', { method: 'GET', auth: true })
}

export async function reissueAccessToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    clearTokens()
    throw new Error('세션이 만료되었습니다. 다시 로그인해 주세요.')
  }

  const accessToken = await apiRequest('/auth/reissue', {
    method: 'POST',
    headers: {
      'Refresh-Token': refreshToken,
    },
  })

  saveTokens({ accessToken, refreshToken })
  return accessToken
}
