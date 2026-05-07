import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import StatusBadge from '../../components/common/StatusBadge.jsx'
import { env } from '../../config/env.js'
import { logout } from '../../services/authApi.js'
import { openChatStream } from '../../services/chatStream.js'
import { getAuthProfile, hasAccessToken } from '../../services/authStorage.js'
import { deleteChatSession, getChatSession, listChatSessions } from '../../services/chatHistoryApi.js'
import { getSessionKey } from '../../utils/sessionKey.js'
import inhaBadgeUrl from '../../images/inha-badge.svg'

const RECENT_QUESTIONS = [
  { title: '입학전형 일정', date: '2026년 3월 30일' },
  { title: '휴학·복학 신청 방법', date: '2026년 3월 29일' },
  { title: '장학금 수혜 기준', date: '2026년 3월 28일' },
]

function NewChatIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="m20 20-4.2-4.2M10.8 18a7.2 7.2 0 1 1 0-14.4 7.2 7.2 0 0 1 0 14.4Z" />
    </svg>
  )
}

function SidebarIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M5 5.5h14A1.5 1.5 0 0 1 20.5 7v10A1.5 1.5 0 0 1 19 18.5H5A1.5 1.5 0 0 1 3.5 17V7A1.5 1.5 0 0 1 5 5.5Z" />
      <path d="M9 5.5v13" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </svg>
  )
}

function DeleteIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M5 7h14" />
      <path d="M10 11v6M14 11v6" />
      <path d="M8 7l.8 12h6.4L16 7" />
      <path d="M9.5 7l.8-2h3.4l.8 2" />
    </svg>
  )
}

function LoadingDots() {
  return (
    <span className="loading-dots" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  )
}

function LoginIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M15 3.8h3.2A1.8 1.8 0 0 1 20 5.6v12.8a1.8 1.8 0 0 1-1.8 1.8H15" />
      <path d="m10 8 4 4-4 4M14 12H4" />
    </svg>
  )
}

function ProfileIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M12 12.5a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
      <path d="M4.8 20a7.2 7.2 0 0 1 14.4 0" />
    </svg>
  )
}

function BadgeButton({ className = '', onClick, label }) {
  return (
    <button type="button" className={`badge-button ${className}`} onClick={onClick} aria-label={label}>
      <img src={inhaBadgeUrl} alt="" />
    </button>
  )
}

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

function getRoleLabel(role) {
  if (role === 'ADMIN') return '관리자'
  if (role === 'STAFF') return '교직원'
  return '학생'
}

function getIdentifierLabel(role) {
  if (role === 'ADMIN') return '관리자 번호'
  if (role === 'STAFF') return '교번'
  return '학번'
}

function ChatPage() {
  const eventSourceRef = useRef(null)
  const transcriptRef = useRef(null)
  const [isLoggedIn, setIsLoggedIn] = useState(() => hasAccessToken())
  const [isProfileOpen, setIsProfileOpen] = useState(false)
  const [isSidebarOpen, setIsSidebarOpen] = useState(() =>
    typeof window === 'undefined' ? true : window.matchMedia('(min-width: 834px)').matches
  )
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [isGuestHistoryOpen, setIsGuestHistoryOpen] = useState(false)
  const [historySessions, setHistorySessions] = useState([])
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [activeSourceIndex, setActiveSourceIndex] = useState(null)
  const authProfile = isLoggedIn ? getAuthProfile() : null

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

  useEffect(() => {
    if (isLoggedIn || isGuestHistoryOpen) {
      loadHistory()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGuestHistoryOpen, isLoggedIn])

  useEffect(() => {
    if (question) return

    document
      .querySelectorAll('.chat-composer textarea')
      .forEach((textarea) => {
        textarea.style.height = '38px'
      })
  }, [question])

  const loadHistory = async () => {
    setIsHistoryLoading(true)
    setHistoryError('')

    try {
      const sessions = await listChatSessions({
        auth: isLoggedIn,
        sessionKey: isLoggedIn ? undefined : getSessionKey(),
      })
      setHistorySessions(Array.isArray(sessions) ? sessions : [])
    } catch (error) {
      setHistoryError(error.message)
    } finally {
      setIsHistoryLoading(false)
    }
  }

  const openHistorySession = async (sessionId) => {
    if (!sessionId || isStreaming) return

    setErrorMessage('')
    setFeedback(null)
    setActiveSourceIndex(null)

    try {
      const detail = await getChatSession(sessionId, {
        auth: isLoggedIn,
        sessionKey: isLoggedIn ? undefined : getSessionKey(),
      })
      const messages = Array.isArray(detail?.messages) ? detail.messages : []
      const lastMessage = [...messages].reverse().find((message) => message.question || message.answer)
      if (!lastMessage) return

      setSubmittedQuestion(lastMessage.question ?? detail.title ?? '')
      setAnswer(lastMessage.answer ?? '')
      setSources(Array.isArray(lastMessage.sources) ? lastMessage.sources : [])
      setIsGuestHistoryOpen(false)
    } catch (error) {
      setHistoryError(error.message)
    }
  }

  const removeHistorySession = async (sessionId) => {
    if (!sessionId || isStreaming) return

    try {
      await deleteChatSession(sessionId, {
        auth: isLoggedIn,
        sessionKey: isLoggedIn ? undefined : getSessionKey(),
      })
      setHistorySessions((prevSessions) => prevSessions.filter((session) => session.sessionId !== sessionId))
    } catch (error) {
      setHistoryError(error.message)
    }
  }

  const startStream = (event) => {
    event.preventDefault()

    const trimmedQuestion = question.trim()
    if (!trimmedQuestion || isStreaming) {
      return
    }

    eventSourceRef.current?.close()
    setSubmittedQuestion(trimmedQuestion)
    setQuestion('')
    setAnswer('')
    setSources([])
    setErrorMessage('')
    setFeedback(null)
    setActiveSourceIndex(null)
    setIsStreaming(true)

    eventSourceRef.current = openChatStream({
      question: trimmedQuestion,
      auth: isLoggedIn,
      sessionKey: isLoggedIn ? undefined : getSessionKey(),
      topK: env.defaultTopK,
      onToken: (token) => setAnswer((prev) => prev + token),
      onDone: ({ answer: completedAnswer, sources: nextSources }) => {
        if (completedAnswer) {
          setAnswer(completedAnswer)
        }
        setSources(nextSources)
        setIsStreaming(false)
        loadHistory()
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

  const resizeComposer = (target) => {
    target.style.height = '38px'
    target.style.height = `${Math.min(target.scrollHeight, 120)}px`
  }

  const handleQuestionChange = (event) => {
    setQuestion(event.target.value)
    resizeComposer(event.target)
  }

  const handleComposerKeyDown = (event) => {
    if (event.key !== 'Enter' || event.shiftKey) return

    event.preventDefault()
    event.currentTarget.form?.requestSubmit()
  }

  const canSend = question.trim().length > 0 && !isStreaming
  const hasConversation = submittedQuestion || answer || errorMessage
  const canGiveFeedback = Boolean(answer) && !isStreaming && !errorMessage

  const resetChat = () => {
    eventSourceRef.current?.close()
    setQuestion('')
    setSubmittedQuestion('')
    setAnswer('')
    setSources([])
    setErrorMessage('')
    setFeedback(null)
    setActiveSourceIndex(null)
    setIsStreaming(false)
    setIsGuestHistoryOpen(false)
    setIsProfileOpen(false)
  }

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      eventSourceRef.current?.close()
      setIsLoggedIn(false)
      setIsSidebarOpen(false)
      setIsProfileOpen(false)
      setHistorySessions([])
      setHistoryError('')
      setSubmittedQuestion('')
      setAnswer('')
      setSources([])
      setFeedback(null)
      setErrorMessage('')
      setActiveSourceIndex(null)
      setIsStreaming(false)
    }
  }

  const renderHistoryContent = (compact = false, allowDelete = !compact) => {
    if (isHistoryLoading) {
      return <p className="history-state">불러오는 중</p>
    }

    if (historyError) {
      return <p className="history-state history-state--error">{historyError}</p>
    }

    if (historySessions.length > 0) {
      return historySessions.map((session) => (
        <div key={session.sessionId} className="history-entry">
          <button
            type="button"
            className={compact ? 'history-link' : 'history-card'}
            onClick={() => openHistorySession(session.sessionId)}
            disabled={isStreaming}
          >
            <strong>{session.title || '새 대화'}</strong>
          </button>
          {allowDelete && (
            <button
              type="button"
              className="history-delete"
              onClick={() => removeHistorySession(session.sessionId)}
              disabled={isStreaming}
              aria-label={`${session.title || '대화'} 삭제`}
            >
              <DeleteIcon />
            </button>
          )}
        </div>
      ))
    }

    return RECENT_QUESTIONS.map((item) => (
      <button
        key={item.title}
        type="button"
        className={compact ? 'history-link' : 'history-card'}
        onClick={() => {
          selectExample(item.title)
          setIsGuestHistoryOpen(false)
        }}
        disabled={isStreaming}
      >
        <strong>{item.title}</strong>
      </button>
    ))
  }

  const renderComposer = (home = false) => (
    <form className={home ? 'chat-composer chat-composer--home' : 'chat-composer'} onSubmit={startStream}>
      <span className="composer-plus" aria-hidden="true">
        <NewChatIcon />
      </span>
      <label className="sr-only" htmlFor={home ? 'chat-question-home' : 'chat-question'}>질문 입력</label>
      <textarea
        id={home ? 'chat-question-home' : 'chat-question'}
        value={question}
        onChange={handleQuestionChange}
        onKeyDown={handleComposerKeyDown}
        placeholder="질문하기"
        rows={1}
        disabled={isStreaming}
      />
      {isStreaming ? (
        <button type="button" className="composer-icon-button composer-icon-button--stop" onClick={stopStream} aria-label="답변 중단" title="답변 중단">
          <StopIcon />
        </button>
      ) : (
        <button type="submit" className="composer-icon-button" disabled={!canSend} aria-label="질문 보내기">
          ↑
        </button>
      )}
    </form>
  )

  return (
    <section
      className={[
        'chat-shell',
        isLoggedIn ? 'chat-shell--logged-in' : 'chat-shell--guest',
        isLoggedIn && !isSidebarOpen ? 'chat-shell--sidebar-collapsed' : '',
        !isLoggedIn && isGuestHistoryOpen ? 'chat-shell--guest-history-open' : '',
      ].filter(Boolean).join(' ')}
    >
      {!isLoggedIn && (
        <aside className="chat-rail" aria-label="빠른 메뉴">
          <BadgeButton
            className="badge-button--rail"
            onClick={() => setIsGuestHistoryOpen(true)}
            label="대화 내역 열기"
          />
          <button type="button" className="rail-button" onClick={resetChat} aria-label="새 질문">
            <NewChatIcon />
          </button>
        </aside>
      )}

      {!isLoggedIn && (
        <>
          <Link className="login-shortcut" to="/admin/login" aria-label="로그인">
            <LoginIcon />
          </Link>
          {isGuestHistoryOpen && (
            <>
              <button
                type="button"
                className="history-scrim history-scrim--open"
                onClick={() => setIsGuestHistoryOpen(false)}
                aria-label="대화 내역 닫기"
              />
              <aside className="history-drawer history-drawer--open" aria-label="대화 내역">
                <header className="history-drawer__header">
                  <div>
                    <strong>인하공전 AI</strong>
                    <small>홈페이지 안내</small>
                  </div>
                  <button
                    type="button"
                    className="drawer-icon-button"
                    onClick={() => setIsGuestHistoryOpen(false)}
                    aria-label="사이드바 닫기"
                  >
                    <SidebarIcon />
                  </button>
                </header>

                <nav className="drawer-menu" aria-label="대화 작업">
                  <button type="button" className="drawer-menu__item drawer-menu__item--active" onClick={resetChat}>
                    <NewChatIcon />
                    <span>새 질문</span>
                  </button>
                  <button type="button" className="drawer-menu__item" disabled>
                    <SearchIcon />
                    <span>질문 검색</span>
                  </button>
                </nav>

                <section className="history-group" aria-label="최근 질문">
                  <h2>최근</h2>
                  {renderHistoryContent(true, true)}
                </section>

                <p className="history-drawer__note">
                  비로그인 질문 기록은 공개 홈페이지 방문 흐름에 맞춰 임시 항목으로만 표시합니다.
                </p>
              </aside>
            </>
          )}
        </>
      )}

      {isLoggedIn && (
        <aside className="chat-sidebar" aria-label="대화 목록">
          <div className="chat-sidebar__brand">
            <BadgeButton
              className="badge-button--sidebar"
              onClick={resetChat}
              label="새 질문 시작"
            />
            <button
              type="button"
              className="sidebar-toggle sidebar-toggle--inside"
              onClick={() => setIsSidebarOpen((prev) => !prev)}
              aria-label={isSidebarOpen ? '사이드바 접기' : '사이드바 열기'}
              title={isSidebarOpen ? '사이드바 접기' : '사이드바 열기'}
            >
              <SidebarIcon />
            </button>
          </div>

          <button type="button" className="new-chat-button" onClick={resetChat}>
            <NewChatIcon />
            새 질문
          </button>

          <div className="sidebar-section">
            <span>최근 질문</span>
            <div className="history-list">
              {renderHistoryContent()}
            </div>
          </div>
        </aside>
      )}

      <section className="chat-main">
        <header className="chat-topbar">
          <div>
            <span>Inha Technical College</span>
            <strong>인하공업전문대학 AI 안내</strong>
          </div>
          {isLoggedIn ? (
            <div className="profile-menu">
              <button
                type="button"
                className="chat-topbar__auth"
                onClick={() => setIsProfileOpen((prev) => !prev)}
                aria-label="프로필"
                aria-expanded={isProfileOpen}
              >
                <ProfileIcon />
              </button>
              {isProfileOpen && (
                <section className="profile-popover" aria-label="사용자 정보">
                  <header>
                    <span>{getRoleLabel(authProfile?.role)}</span>
                    <strong>{authProfile?.username || 'admin'}</strong>
                  </header>
                  <dl>
                    <div>
                      <dt>{getIdentifierLabel(authProfile?.role)}</dt>
                      <dd>{authProfile?.id ?? '-'}</dd>
                    </div>
                    <div>
                      <dt>계정</dt>
                      <dd>{authProfile?.username || '-'}</dd>
                    </div>
                  </dl>
                  <button type="button" className="profile-logout" onClick={handleLogout}>
                    로그아웃
                  </button>
                </section>
              )}
            </div>
          ) : (
            <Link className="chat-topbar__auth" to="/admin/login" aria-label="로그인">
              <LoginIcon />
            </Link>
          )}
          <StatusBadge active={isStreaming}>
            {isStreaming ? (
              <span className="status-badge__loading">
                답변 생성 중
                <LoadingDots />
              </span>
            ) : '대기 중'}
          </StatusBadge>
        </header>

        <div ref={transcriptRef} className="chat-canvas" aria-live="polite">
          <div className="conversation-stack">
            {hasConversation ? (
              <>
                {submittedQuestion && (
                  <article className="chat-row chat-row--user">
                    <div className="user-bubble">{submittedQuestion}</div>
                  </article>
                )}

                <div className="assistant-cluster">
                  <span className="avatar avatar--assistant" aria-hidden="true">
                    <img src={inhaBadgeUrl} alt="" />
                  </span>
                  <article className="answer-card">
                    <div className="answer-card__header">
                      <strong>인하공전 AI 답변</strong>
                      {isStreaming && <span className="stream-dot" aria-label="답변 생성 중" />}
                    </div>
                    {answer ? (
                      <p>
                        {answer}
                        {isStreaming && <span className="typing-caret" aria-hidden="true" />}
                      </p>
                    ) : (
                      <p className="muted">
                        {isStreaming ? (
                          <span className="answer-loading">
                            학교 안내 문서를 찾고 답변을 작성하고 있습니다
                            <LoadingDots />
                          </span>
                        ) : '답변 대기 중'}
                      </p>
                    )}
                    {errorMessage && <p className="error">{errorMessage}</p>}
                  </article>
                </div>

                {sources.length > 0 && (
                  <section className="source-card" aria-label="출처 문서">
                    <h2>출처 문서</h2>
                    <ol className="source-list">
                      {sources.map((source, index) => (
                        <li key={`${source.document_id ?? source.source ?? 'source'}-${index}`}>
                          <button
                            type="button"
                            className="source-trigger"
                            onClick={() => setActiveSourceIndex((prevIndex) => (prevIndex === index ? null : index))}
                          >
                            <strong>{getSourceTitle(source, index)}</strong>
                            {getSourcePath(source) && <span>{getSourcePath(source)}</span>}
                          </button>
                          {activeSourceIndex === index && (
                            <p>{getSourceSnippet(source)}</p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                <div className="feedback-bar" aria-label="답변 피드백">
                  <button
                    type="button"
                    className={feedback === 'positive' ? 'icon-action icon-action--selected' : 'icon-action'}
                    onClick={() => handleFeedback('positive')}
                    disabled={!canGiveFeedback}
                    aria-label="좋아요"
                    title="좋아요"
                  >
                    좋아요
                  </button>
                  <button
                    type="button"
                    className={feedback === 'negative' ? 'icon-action icon-action--selected' : 'icon-action'}
                    onClick={() => handleFeedback('negative')}
                    disabled={!canGiveFeedback}
                    aria-label="싫어요"
                    title="싫어요"
                  >
                    싫어요
                  </button>
                </div>
              </>
            ) : (
              <div className="chat-welcome">
                <h1>무엇을 도와드릴까요?</h1>
                <p>입학, 학사, 장학, 휴학·복학 안내를 학교 문서에 근거해 답변합니다.</p>
                {renderComposer(true)}
              </div>
            )}
          </div>
        </div>

        {hasConversation && renderComposer()}
      </section>
    </section>
  )
}

export default ChatPage
