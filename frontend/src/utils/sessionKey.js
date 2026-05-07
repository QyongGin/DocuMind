const SESSION_KEY_COOKIE = 'documind-session-key'
const LEGACY_SESSION_KEY_STORAGE = 'documind-session-key'

let memorySessionKey = null

function createSessionKey() {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function readSessionCookie() {
  if (typeof document === 'undefined') return null

  return document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith(`${SESSION_KEY_COOKIE}=`))
    ?.split('=')
    .slice(1)
    .join('=')
}

function writeSessionCookie(sessionKey) {
  if (typeof document === 'undefined') return

  document.cookie = `${SESSION_KEY_COOKIE}=${encodeURIComponent(sessionKey)}; path=/; SameSite=Lax`
}

function readLegacyStorage() {
  try {
    return localStorage.getItem(LEGACY_SESSION_KEY_STORAGE)
  } catch {
    return null
  }
}

function clearLegacyStorage() {
  try {
    localStorage.removeItem(LEGACY_SESSION_KEY_STORAGE)
  } catch {
    // localStorage 접근이 제한된 환경에서는 기존 키 정리를 건너뛴다.
  }
}

function persistCookie(sessionKey) {
  writeSessionCookie(sessionKey)

  const persisted = readSessionCookie()
  return persisted ? decodeURIComponent(persisted) === sessionKey : false
}

export function getSessionKey() {
  try {
    const saved = readSessionCookie()
    if (saved) return decodeURIComponent(saved)

    const legacySessionKey = readLegacyStorage()
    if (legacySessionKey) {
      if (persistCookie(legacySessionKey)) {
        clearLegacyStorage()
        return legacySessionKey
      }

      memorySessionKey = memorySessionKey ?? legacySessionKey
      return memorySessionKey
    }

    const nextSessionKey = createSessionKey()
    if (persistCookie(nextSessionKey)) {
      clearLegacyStorage()
      return nextSessionKey
    }

    memorySessionKey = memorySessionKey ?? nextSessionKey
    return memorySessionKey
  } catch {
    // 쿠키 접근이 제한된 환경에서는 같은 탭 안에서만 유지되는 메모리 키로 폴백한다.
    memorySessionKey = memorySessionKey ?? createSessionKey()
    return memorySessionKey
  }
}
