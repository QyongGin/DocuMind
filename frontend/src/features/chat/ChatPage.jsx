import { useEffect, useRef, useState } from 'react'
import StatusBadge from '../../components/common/StatusBadge.jsx'
import { env } from '../../config/env.js'
import { openChatStream } from '../../services/chatStream.js'
import { getSessionKey } from '../../utils/sessionKey.js'

function ChatPage() {
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

    eventSourceRef.current = openChatStream({
      question: trimmedQuestion,
      sessionKey: getSessionKey(),
      topK: env.defaultTopK,
      onToken: (token) => setAnswer((prev) => prev + token),
      onDone: ({ answer: completedAnswer, sources: nextSources }) => {
        if (completedAnswer) {
          setAnswer(completedAnswer)
        }
        setSources(nextSources)
        setIsStreaming(false)
      },
      onError: (message) => {
        setErrorMessage(message)
        setIsStreaming(false)
      },
    })
  }

  const stopStream = () => {
    eventSourceRef.current?.close()
    setIsStreaming(false)
  }

  return (
    <section className="page page--narrow">
      <header className="page-header">
        <div>
          <p className="eyebrow">Knowledge Assistant</p>
          <h1>사내 문서 질의응답</h1>
        </div>
        <StatusBadge active={isStreaming}>{isStreaming ? '답변 생성 중' : '대기 중'}</StatusBadge>
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
              <li key={`${source.document_id ?? source.source ?? 'source'}-${index}`}>
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
  )
}

export default ChatPage
