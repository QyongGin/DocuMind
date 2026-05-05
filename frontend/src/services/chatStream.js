import { env } from '../config/env.js'

function createStreamUrl({ question, sessionKey, topK }) {
  const normalizedBase = env.apiBaseUrl.replace(/\/$/, '')
  const params = new URLSearchParams({
    question,
    topK: String(topK ?? env.defaultTopK),
  })
  if (sessionKey) {
    params.set('sessionKey', sessionKey)
  }

  return `${normalizedBase}/chat/stream?${params.toString()}`
}

export function openChatStream({ question, sessionKey, topK, onToken, onDone, onError }) {
  const eventSource = new EventSource(createStreamUrl({ question, sessionKey, topK }))

  eventSource.onmessage = (message) => {
    try {
      const data = JSON.parse(message.data)

      if (data.token) {
        onToken(data.token)
      } else if (data.done) {
        onDone({
          answer: data.answer,
          sources: data.sources ?? [],
        })
        eventSource.close()
      } else if (data.error) {
        onError(data.error)
        eventSource.close()
      }
    } catch {
      onError('스트리밍 응답을 처리하지 못했습니다.')
      eventSource.close()
    }
  }

  eventSource.onerror = () => {
    onError('서버 연결이 끊어졌습니다.')
    eventSource.close()
  }

  return eventSource
}
