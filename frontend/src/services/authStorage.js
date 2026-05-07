const ACCESS_TOKEN_KEY = 'documind-access-token'

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

export function hasAccessToken() {
  const accessToken = getAccessToken()
  if (!accessToken) return false

  const claims = parseTokenClaims(accessToken)
  if (!claims?.exp) return true

  return claims.exp * 1000 > Date.now()
}

function decodeBase64Url(value) {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/')
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
  return decodeURIComponent(
    atob(padded)
      .split('')
      .map((char) => `%${char.charCodeAt(0).toString(16).padStart(2, '0')}`)
      .join('')
  )
}

function parseTokenClaims(accessToken) {
  if (!accessToken) return null

  try {
    const [, payload] = accessToken.split('.')
    if (!payload) return null

    return JSON.parse(decodeBase64Url(payload))
  } catch {
    return null
  }
}

export function getAuthProfile() {
  const claims = parseTokenClaims(getAccessToken())
  if (!claims) return null

  try {
    return {
      id: claims.userId,
      username: claims.sub,
      role: claims.role,
    }
  } catch {
    return null
  }
}

export function saveTokens({ accessToken } = {}) {
  const normalizedAccessToken = normalizeToken(accessToken)
  if (normalizedAccessToken) {
    localStorage.setItem(ACCESS_TOKEN_KEY, normalizedAccessToken)
  } else {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
  }
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
}
