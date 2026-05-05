import { useEffect, useRef, useState } from 'react'
import StatusBadge from '../../components/common/StatusBadge.jsx'
import { env } from '../../config/env.js'
import { openChatStream } from '../../services/chatStream.js'
import { getSessionKey } from '../../utils/sessionKey.js'

const EXAMPLE_QUESTIONS = [
  '최근 업로드된 문서의 핵심 내용을 요약해줘.',
  '보안 정책에서 비밀번호 변경 기준을 알려줘.',
  '문서에 근거해서 프로젝트 배포 절차를 설명해줘.',
]

function getSourceTitle(source, index) {
  return source.source || source.document_name || source.filename || `참조 문서 ${index + 1}`
}

function getSourcePath(source) {
  return ['Header 1', 'Header 2', 'Header 3']
    .map((key) => source[key])
    .filter(Boolean)
    .join(' · ')
}

function getSourceSnippet(source) {
  return source.content || source.text || source.page_content || '출처 본문이 응답에 포함되지 않았습니다.'
}

function ChatPage() {
  const eventSourceRef = useRef(null)
  const transcriptRef = useRef(null)
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [feedback, setFeedback] = useState(null)

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close()
    }
  }, [])

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [answer, errorMessage])

  const startStream = (event) => {
    event.preventDefault()

    const trimmedQuestion = question.trim()
    if (!trimmedQuestion || isStreaming) {
      return
    }

    eventSourceRef.current?.close()
    setSubmittedQuestion(trimmedQuestion)
    setAnswer('')
    setSources([])
    setErrorMessage('')
    setFeedback(null)
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

  const selectExample = (nextQuestion) => {
    if (!isStreaming) {
      setQuestion(nextQuestion)
    }
  }

  const handleFeedback = (nextFeedback) => {
    setFeedback((prevFeedback) => (prevFeedback === nextFeedback ? null : nextFeedback))
  }

  const canSend = question.trim().length > 0 && !isStreaming
  const hasConversation = submittedQuestion || answer || errorMessage
  const canGiveFeedback = Boolean(answer) && !isStreaming && !errorMessage

  return (
    <section className="chat-page">
      <header className="chat-hero">
        <div className="chat-hero__copy">
          <p className="eyebrow">DocuMind Assistant</p>
          <h1>문서에서 답을 찾는 사내 AI</h1>
          <p>온프레미스 문서 저장소와 연결된 질의응답 화면이다.</p>
        </div>
        <StatusBadge active={isStreaming}>{isStreaming ? '생성 중' : '대기 중'}</StatusBadge>
      </header>

      <div className="chat-workspace">
        <section className="chat-panel chat-panel--transcript" aria-label="대화">
          <div className="chat-panel__header">
            <div>
              <p className="eyebrow">Conversation</p>
              <h2>질의응답</h2>
            </div>
            {isStreaming && <span className="stream-dot" aria-label="답변 생성 중" />}
          </div>

          <div ref={transcriptRef} className="chat-transcript" aria-live="polite">
            {hasConversation ? (
              <>
                {submittedQuestion && (
                  <article className="message message--user">
                    <span>질문</span>
                    <p>{submittedQuestion}</p>
                  </article>
                )}

                <article className="message message--assistant">
                  <span>답변</span>
                  {answer ? (
                    <p>
                      {answer}
                      {isStreaming && <span className="typing-caret" aria-hidden="true" />}
                    </p>
                  ) : (
                    <p className="muted">{isStreaming ? '답변을 준비하고 있습니다.' : '답변 대기 중'}</p>
                  )}
                  {errorMessage && <p className="error">{errorMessage}</p>}
                </article>
              </>
            ) : (
              <div className="empty-answer">
                <strong>질문 대기 중</strong>
                <p>문서 근거가 준비되면 답변과 함께 정리됩니다.</p>
              </div>
            )}
          </div>

          <div className="feedback-bar" aria-label="답변 피드백">
            <span>{feedback ? '피드백 선택됨' : '답변 평가'}</span>
            <div>
              <button
                type="button"
                className={feedback === 'positive' ? 'icon-action icon-action--selected' : 'icon-action'}
                onClick={() => handleFeedback('positive')}
                disabled={!canGiveFeedback}
                aria-label="좋아요"
                title="좋아요"
              >
                👍
              </button>
              <button
                type="button"
                className={feedback === 'negative' ? 'icon-action icon-action--selected' : 'icon-action'}
                onClick={() => handleFeedback('negative')}
                disabled={!canGiveFeedback}
                aria-label="싫어요"
                title="싫어요"
              >
                👎
              </button>
            </div>
          </div>
        </section>

        <aside className="chat-side">
          <section className="chat-panel chat-panel--ask" aria-label="질문 입력">
            <div className="chat-panel__header">
              <div>
                <p className="eyebrow">Ask</p>
                <h2>질문</h2>
              </div>
            </div>

            <form className="chat-form" onSubmit={startStream}>
              <label htmlFor="chat-question">질문 입력</label>
              <textarea
                id="chat-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="문서 내용에 대해 질문하세요."
                rows={6}
                disabled={isStreaming}
              />
              <div className="actions">
                <button type="submit" disabled={!canSend}>
                  질문하기
                </button>
                <button type="button" className="secondary" onClick={stopStream} disabled={!isStreaming}>
                  중단
                </button>
              </div>
            </form>

            <div className="prompt-chips" aria-label="예시 질문">
              {EXAMPLE_QUESTIONS.map((example) => (
                <button key={example} type="button" className="prompt-chip" onClick={() => selectExample(example)}>
                  {example}
                </button>
              ))}
            </div>
          </section>

          <section className="chat-panel chat-panel--sources" aria-label="출처">
            <div className="chat-panel__header">
              <div>
                <p className="eyebrow">Sources</p>
                <h2>출처</h2>
              </div>
              <span className="source-count">{sources.length}</span>
            </div>

            {sources.length > 0 ? (
              <ol className="source-list">
                {sources.map((source, index) => (
                  <li key={`${source.document_id ?? source.source ?? 'source'}-${index}`}>
                    <strong>{getSourceTitle(source, index)}</strong>
                    {getSourcePath(source) && <span>{getSourcePath(source)}</span>}
                    <p>{getSourceSnippet(source)}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">답변 완료 후 참조 문서가 표시됩니다.</p>
            )}
          </section>
        </aside>
      </div>
    </section>
  )
}

export default ChatPage
