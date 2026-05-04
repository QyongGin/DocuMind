const SESSION_KEY_STORAGE = 'documind-session-key'

function createSessionKey() {
  if (crypto.randomUUID) {
    return crypto.randomUUID()
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function getSessionKey() {
  try {
    const saved = localStorage.getItem(SESSION_KEY_STORAGE)
    if (saved) return saved

    const sessionKey = createSessionKey()
    localStorage.setItem(SESSION_KEY_STORAGE, sessionKey)
    return sessionKey
  } catch {
    // Private 모드나 storage quota 초과 시 localStorage가 throw한다 — 메모리 키로 폴백
    return createSessionKey()
  }
}
