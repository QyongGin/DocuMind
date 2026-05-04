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

export async function reissueAccessToken() {
  const refreshToken = getRefreshToken()
  const accessToken = await apiRequest('/auth/reissue', {
    method: 'POST',
    headers: {
      'Refresh-Token': refreshToken,
    },
  })

  saveTokens({ accessToken, refreshToken })
  return accessToken
}
