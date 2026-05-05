const ACCESS_TOKEN_KEY = 'documind-access-token'
const REFRESH_TOKEN_KEY = 'documind-refresh-token'

function normalizeToken(token) {
  if (typeof token !== 'string') return null
  const normalized = token.trim()
  if (!normalized || normalized.toLowerCase() === 'undefined' || normalized.toLowerCase() === 'null') {
    return null
  }
  return normalized
}

export function getAccessToken() {
  return normalizeToken(localStorage.getItem(ACCESS_TOKEN_KEY))
}

export function getRefreshToken() {
  return normalizeToken(localStorage.getItem(REFRESH_TOKEN_KEY))
}

export function hasAccessToken() {
  return Boolean(getAccessToken())
}

export function saveTokens({ accessToken, refreshToken } = {}) {
  const normalizedAccessToken = normalizeToken(accessToken)
  if (normalizedAccessToken) {
    localStorage.setItem(ACCESS_TOKEN_KEY, normalizedAccessToken)
  } else {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
  }

  const normalizedRefreshToken = normalizeToken(refreshToken)
  if (normalizedRefreshToken) {
    localStorage.setItem(REFRESH_TOKEN_KEY, normalizedRefreshToken)
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}
