const ACCESS_TOKEN_KEY = 'documind-access-token'
const REFRESH_TOKEN_KEY = 'documind-refresh-token'

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function hasAccessToken() {
  const token = getAccessToken()
  return typeof token === 'string' && token.trim() !== '' && token !== 'undefined' && token !== 'null'
}

export function saveTokens({ accessToken, refreshToken }) {
  if (typeof accessToken === 'string' && accessToken.trim() !== '') {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
  } else {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
  }

  if (typeof refreshToken === 'string' && refreshToken.trim() !== '') {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}
