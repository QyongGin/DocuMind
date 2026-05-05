const ACCESS_TOKEN_KEY = 'documind-access-token'

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function hasAccessToken() {
  const token = getAccessToken()
  return typeof token === 'string' && token.trim() !== '' && token !== 'undefined' && token !== 'null'
}

export function saveTokens({ accessToken }) {
  if (typeof accessToken === 'string' && accessToken.trim() !== '') {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
  } else {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
  }
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
}
