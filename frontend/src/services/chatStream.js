import { env } from '../config/env.js'
import { getAccessToken } from './authStorage.js'

async function createStreamSession({ question, sessionKey, topK, auth = false }) {
  const normalizedBase = env.apiBaseUrl.replace(/\/$/, '')
  const body = { question, topK: topK ?? env.defaultTopK }
  if (sessionKey) {
    body.sessionKey = sessionKey
  }
  const headers = { 'Content-Type': 'application/json' }
  const accessToken = auth ? getAccessToken() : null
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }

  const response = await fetch(`${normalizedBase}/chat/stream/session`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw new Error('스트리밍 세션을 생성하지 못했습니다.')
  }

  const payload = await response.json()
  return payload.data.streamId
}

/**
 * SSE 스트리밍 채팅을 시작한다.
 * 먼저 POST /chat/stream/session으로 streamId를 발급받고,
 * EventSource(/chat/stream/{streamId})로 연결해 질문을 URL에 노출하지 않는다.
 *
 * @returns {{ close: Function }} 스트림 중단 함수를 포함한 객체
 */
export function openChatStream({ question, sessionKey, topK, auth = false, onToken, onDone, onError }) {
  let eventSource = null
  let cancelled = false

  function closeStream() {
    cancelled = true
    eventSource?.close()
  }

  createStreamSession({ question, sessionKey, topK, auth })
    .then((streamId) => {
      if (cancelled) return

      const normalizedBase = env.apiBaseUrl.replace(/\/$/, '')
      eventSource = new EventSource(`${normalizedBase}/chat/stream/${streamId}`, {
        withCredentials: true,
      })

      eventSource.onmessage = (message) => {
        if (cancelled) return

        try {
          const data = JSON.parse(message.data)

          if (data.token) {
            onToken(data.token)
          } else if (data.done) {
            onDone({
              answer: data.answer,
              sources: data.sources ?? [],
            })
            closeStream()
          } else if (data.error) {
            onError(data.error)
            closeStream()
          }
        } catch {
          onError('스트리밍 응답을 처리하지 못했습니다.')
          closeStream()
        }
      }

      eventSource.onerror = (event) => {
        if (cancelled) return

        if (typeof event.data === 'string') {
          try {
            const data = JSON.parse(event.data)
            onError(data.error ?? '스트리밍 응답을 처리하지 못했습니다.')
          } catch {
            onError('스트리밍 응답을 처리하지 못했습니다.')
          }
          closeStream()
          return
        }

        onError('서버 연결이 끊어졌습니다.')
        closeStream()
      }
    })
    .catch(() => {
      if (!cancelled) {
        onError('스트리밍 세션을 생성하지 못했습니다.')
      }
    })

  return {
    close() {
      closeStream()
    },
  }
}
