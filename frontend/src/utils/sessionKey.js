const SESSION_KEY_STORAGE = 'documind-session-key'

function createSessionKey() {
  if (crypto.randomUUID) {
    return crypto.randomUUID()
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function getSessionKey() {
  const saved = localStorage.getItem(SESSION_KEY_STORAGE)
  if (saved) {
    return saved
  }

  const sessionKey = createSessionKey()
  localStorage.setItem(SESSION_KEY_STORAGE, sessionKey)
  return sessionKey
}
