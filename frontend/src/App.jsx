import { useEffect, useRef, useState } from 'react'
import './App.css'

const SESSION_KEY_STORAGE = 'documind-session-key'

function createSessionKey() {
  if (crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function getSessionKey() {
  const saved = localStorage.getItem(SESSION_KEY_STORAGE)
  if (saved) {
    return saved
  }

  const sessionKey = createSessionKey()
  localStorage.setItem(SESSION_KEY_STORAGE, sessionKey)
  return sessionKey
}

function App() {
  const eventSourceRef = useRef(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close()
    }
  }, [])

  const startStream = (event) => {
    event.preventDefault()

    const trimmedQuestion = question.trim()
    if (!trimmedQuestion || isStreaming) {
      return
    }

    eventSourceRef.current?.close()
    setAnswer('')
    setSources([])
    setErrorMessage('')
    setIsStreaming(true)

    const params = new URLSearchParams({
      question: trimmedQuestion,
      sessionKey: getSessionKey(),
      topK: '5',
    })
    const eventSource = new EventSource(`/api/chat/stream?${params.toString()}`)
    eventSourceRef.current = eventSource

    eventSource.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data)

        if (data.token) {
          setAnswer((prev) => prev + data.token)
        }

        if (data.done) {
          if (data.answer) {
            setAnswer(data.answer)
          }
          setSources(data.sources ?? [])
          setIsStreaming(false)
          eventSource.close()
        }

        if (data.error) {
          setErrorMessage(data.error)
          setIsStreaming(false)
          eventSource.close()
        }
      } catch {
        setErrorMessage('스트리밍 응답을 처리하지 못했습니다.')
        setIsStreaming(false)
        eventSource.close()
      }
    }

    eventSource.onerror = () => {
      setErrorMessage('서버 연결이 끊어졌습니다.')
      setIsStreaming(false)
      eventSource.close()
    }
  }

  const stopStream = () => {
    eventSourceRef.current?.close()
    setIsStreaming(false)
  }

  return (
    <main className="app">
      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <p className="eyebrow">DocuMind</p>
            <h1>사내 문서 질의응답</h1>
          </div>
          <span className={isStreaming ? 'status active' : 'status'}>
            {isStreaming ? '답변 생성 중' : '대기 중'}
          </span>
        </header>

        <form className="question-form" onSubmit={startStream}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="문서 내용에 대해 질문하세요."
            rows={4}
            disabled={isStreaming}
          />
          <div className="actions">
            <button type="submit" disabled={!question.trim() || isStreaming}>
              질문하기
            </button>
            <button type="button" className="secondary" onClick={stopStream} disabled={!isStreaming}>
              중단
            </button>
          </div>
        </form>

        <section className="answer-box" aria-live="polite">
          <h2>답변</h2>
          {answer ? <p>{answer}</p> : <p className="muted">질문을 입력하면 답변이 스트리밍으로 표시됩니다.</p>}
          {errorMessage && <p className="error">{errorMessage}</p>}
        </section>

        <section className="sources-box">
          <h2>출처</h2>
          {sources.length > 0 ? (
            <ul>
              {sources.map((source, index) => (
                <li key={`${source.document_id}-${index}`}>
                  <strong>{source.source || '문서명 없음'}</strong>
                  {source['Header 1'] && <span>{source['Header 1']}</span>}
                  <p>{source.content}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">답변 완료 후 출처가 표시됩니다.</p>
          )}
        </section>
      </section>
    </main>
  )
}

export default App
