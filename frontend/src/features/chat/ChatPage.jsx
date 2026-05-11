import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { env } from '../../config/env.js'
import { logout } from '../../services/authApi.js'
import { updateChatFeedback } from '../../services/chatFeedbackApi.js'
import { openChatStream } from '../../services/chatStream.js'
import { getAuthProfile, hasAccessToken } from '../../services/authStorage.js'
import { deleteChatSession, getChatSession, listChatSessions } from '../../services/chatHistoryApi.js'
import { getSessionKey } from '../../utils/sessionKey.js'
import inqLogoUrl from '../../images/inq-logo.png'
import inqSymbolUrl from '../../images/inq-symbol.png'

const TOKEN_FLUSH_INTERVAL_MS = 50

function NewChatIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M12 5v14M5 12h14" />
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

function ThumbUpIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M7 10.5v9" />
      <path d="M3.8 10.5h3.2v9H3.8a1.3 1.3 0 0 1-1.3-1.3v-6.4a1.3 1.3 0 0 1 1.3-1.3Z" />
      <path d="M7 10.5 11.7 4a1.7 1.7 0 0 1 3 1.4l-.9 3.2h4.6a2 2 0 0 1 1.9 2.5l-1.6 6a3.3 3.3 0 0 1-3.2 2.4H7" />
    </svg>
  )
}

function ThumbDownIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M7 13.5v-9" />
      <path d="M3.8 13.5h3.2v-9H3.8a1.3 1.3 0 0 0-1.3 1.3v6.4a1.3 1.3 0 0 0 1.3 1.3Z" />
      <path d="M7 13.5 11.7 20a1.7 1.7 0 0 0 3-1.4l-.9-3.2h4.6a2 2 0 0 0 1.9-2.5l-1.6-6a3.3 3.3 0 0 0-3.2-2.4H7" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2.05 2.05 0 0 1-2.9 2.9l-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V21a2.05 2.05 0 0 1-4.1 0v-.08A1.7 1.7 0 0 0 8.9 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2.05 2.05 0 0 1-2.9-2.9l.06-.06A1.7 1.7 0 0 0 4.46 15 1.7 1.7 0 0 0 2.9 13.97H2.8a2.05 2.05 0 0 1 0-4.1h.08A1.7 1.7 0 0 0 4.44 8.9a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2.05 2.05 0 0 1 2.9-2.9l.06.06A1.7 1.7 0 0 0 8.88 4.46 1.7 1.7 0 0 0 9.91 2.9V2.8a2.05 2.05 0 0 1 4.1 0v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06a2.05 2.05 0 0 1 2.9 2.9l-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.08a2.05 2.05 0 0 1 0 4.1h-.08A1.7 1.7 0 0 0 19.4 15Z" />
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
      <img src={inqSymbolUrl} alt="" />
    </button>
  )
}

function getSourceTitle(source, index) {
  return source.document_original_name || source.source || source.document_name || source.filename || `참조 문서 ${index + 1}`
}

function getSourcePath(source) {
  return ['Header 1', 'Header 2', 'Header 3', 'Header 4', 'Header 5', 'Header 6']
    .map((key) => source[key])
    .filter(Boolean)
    .join(' · ')
}

function toSourcePageNumber(value) {
  if (value === null || value === undefined || value === '') return null

  const pageNumber = Number(value)
  return Number.isFinite(pageNumber) ? pageNumber : null
}

function getSourcePageLabel(source) {
  const startPage = toSourcePageNumber(source.page_start ?? source.pageStart ?? source.page)
  const endPage = toSourcePageNumber(source.page_end ?? source.pageEnd)

  if (startPage === null) return ''
  if (endPage !== null && endPage !== startPage) return `PDF ${startPage}-${endPage}페이지`
  return `PDF ${startPage}페이지`
}

function getSourceDetailMeta(source) {
  const pageLabel = getSourcePageLabel(source)

  return [
    pageLabel,
    getChunkPositionLabel(source),
    pageLabel ? '' : getSourcePath(source),
  ].filter(Boolean)
}

function getDocumentInfoMeta(group) {
  return [
    group.documentId ? `문서 ID ${group.documentId}` : '',
    group.uploadedAt ? `업로드 ${formatSourceDateTime(group.uploadedAt)}` : '',
  ].filter(Boolean)
}

function getChunkPositionLabel(source) {
  if (source.chunk_index === null || source.chunk_index === undefined) {
    return ''
  }

  const chunkNumber = Number(source.chunk_index)
  if (!Number.isFinite(chunkNumber)) {
    return ''
  }

  return `문서 내 ${chunkNumber + 1}번째 청크`
}

function getSourceSnippet(source) {
  return source.content || source.text || source.page_content || '출처 본문이 응답에 포함되지 않았습니다.'
}

function formatSourceDateTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

function getSourceGroupKey(source, index) {
  return source.document_id || source.document_original_name || source.source || source.filename || `source-${index}`
}

function groupSourcesByDocument(sources) {
  const groups = new Map()

  sources.forEach((source, index) => {
    const key = getSourceGroupKey(source, index)
    const existing = groups.get(key)
    const sourcePath = getSourcePath(source)

    if (existing) {
      existing.chunks.push({ source, originalIndex: index })
      if (!existing.primaryPath && sourcePath) {
        existing.primaryPath = sourcePath
      }
      return
    }

    groups.set(key, {
      key,
      documentId: source.document_id,
      title: getSourceTitle(source, index),
      uploadedAt: source.document_uploaded_at,
      primaryPath: sourcePath,
      chunks: [{ source, originalIndex: index }],
    })
  })

  return Array.from(groups.values())
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

function feedbackFromScore(score) {
  if (Number(score) === 1) return 'positive'
  if (Number(score) === -1) return 'negative'
  return null
}

function scoreFromFeedback(feedback) {
  return feedback === 'positive' ? 1 : -1
}

function renderMarkdownInline(text) {
  return String(text)
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, index) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
      }
      return part
    })
}

function renderAnswerText(text) {
  return String(text)
    .split('\n')
    .map((line, index, lines) => (
      <span key={`${line}-${index}`}>
        {renderMarkdownInline(line)}
        {index < lines.length - 1 && <br />}
      </span>
    ))
}

function ChatPage() {
  const eventSourceRef = useRef(null)
  const transcriptRef = useRef(null)
  const profileMenuRef = useRef(null)
  const deleteModalRef = useRef(null)
  const previousFocusRef = useRef(null)
  const pendingTokenRef = useRef('')
  const tokenFlushTimerRef = useRef(null)
  const [isLoggedIn, setIsLoggedIn] = useState(() => hasAccessToken())
  const [isProfileOpen, setIsProfileOpen] = useState(false)
  const [isSidebarOpen, setIsSidebarOpen] = useState(() =>
    typeof window === 'undefined' ? true : window.matchMedia('(min-width: 834px)').matches
  )
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [messageId, setMessageId] = useState(null)
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [isFeedbackSaving, setIsFeedbackSaving] = useState(false)
  const [feedbackError, setFeedbackError] = useState('')
  const [historySessions, setHistorySessions] = useState([])
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [activeSourceIndex, setActiveSourceIndex] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const authProfile = isLoggedIn ? getAuthProfile() : null

  const refreshLoginState = () => {
    const nextIsLoggedIn = hasAccessToken()
    if (nextIsLoggedIn !== isLoggedIn) {
      setIsLoggedIn(nextIsLoggedIn)
      if (!nextIsLoggedIn) {
        setIsProfileOpen(false)
        setHistorySessions([])
      }
    }
    return nextIsLoggedIn
  }

  const clearTokenFlushTimer = () => {
    if (tokenFlushTimerRef.current === null) return

    window.clearTimeout(tokenFlushTimerRef.current)
    tokenFlushTimerRef.current = null
  }

  const flushBufferedAnswerTokens = () => {
    clearTokenFlushTimer()

    const bufferedTokens = pendingTokenRef.current
    if (!bufferedTokens) return

    pendingTokenRef.current = ''
    setAnswer((prevAnswer) => prevAnswer + bufferedTokens)
  }

  const resetBufferedAnswerTokens = () => {
    clearTokenFlushTimer()
    pendingTokenRef.current = ''
  }

  const appendAnswerToken = (token) => {
    pendingTokenRef.current += token

    if (tokenFlushTimerRef.current !== null) return

    tokenFlushTimerRef.current = window.setTimeout(() => {
      tokenFlushTimerRef.current = null
      flushBufferedAnswerTokens()
    }, TOKEN_FLUSH_INTERVAL_MS)
  }

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close()
      if (tokenFlushTimerRef.current !== null) {
        window.clearTimeout(tokenFlushTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [answer, errorMessage])

  useEffect(() => {
    if (isLoggedIn) {
      loadHistory()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoggedIn])

  useEffect(() => {
    if (question) return

    document
      .querySelectorAll('.chat-composer textarea')
      .forEach((textarea) => {
        textarea.style.height = '38px'
      })
  }, [question])

  const loadHistory = async () => {
    const shouldUseAuth = refreshLoginState()
    setIsHistoryLoading(true)
    setHistoryError('')

    try {
      const sessions = await listChatSessions({
        auth: shouldUseAuth,
        sessionKey: getSessionKey(),
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

    const shouldUseAuth = refreshLoginState()
    resetBufferedAnswerTokens()
    setErrorMessage('')
    setFeedback(null)
    setFeedbackError('')
    setActiveSourceIndex(null)

    try {
      const detail = await getChatSession(sessionId, {
        auth: shouldUseAuth,
        sessionKey: getSessionKey(),
      })
      const messages = Array.isArray(detail?.messages) ? detail.messages : []
      const lastMessage = [...messages].reverse().find((message) => message.question || message.answer)
      if (!lastMessage) return

      setSubmittedQuestion(lastMessage.question ?? detail.title ?? '')
      setMessageId(lastMessage.messageId ?? null)
      setAnswer(lastMessage.answer ?? '')
      setSources(Array.isArray(lastMessage.sources) ? lastMessage.sources : [])
      setFeedback(feedbackFromScore(lastMessage.feedbackScore))
    } catch (error) {
      setHistoryError(error.message)
    }
  }

  const requestHistoryDelete = (session) => {
    if (!session?.sessionId || isStreaming) return

    setDeleteTarget(session)
  }

  const cancelHistoryDelete = () => {
    setDeleteTarget(null)
  }

  useEffect(() => {
    if (!isProfileOpen) return

    const handlePointerDown = (event) => {
      if (!profileMenuRef.current?.contains(event.target)) {
        setIsProfileOpen(false)
      }
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsProfileOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isProfileOpen])

  useEffect(() => {
    if (!deleteTarget) return

    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null

    window.setTimeout(() => {
      const firstButton = deleteModalRef.current?.querySelector('button')
      ;(firstButton ?? deleteModalRef.current)?.focus()
    }, 0)

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        cancelHistoryDelete()
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previousFocusRef.current?.focus()
      previousFocusRef.current = null
    }
  }, [deleteTarget])

  const confirmHistoryDelete = async () => {
    if (!deleteTarget?.sessionId || isStreaming) return

    const shouldUseAuth = refreshLoginState()
    try {
      await deleteChatSession(deleteTarget.sessionId, {
        auth: shouldUseAuth,
        sessionKey: getSessionKey(),
      })
      setHistorySessions((prevSessions) =>
        prevSessions.filter((session) => session.sessionId !== deleteTarget.sessionId)
      )
      setDeleteTarget(null)
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
    resetBufferedAnswerTokens()
    const sessionKey = getSessionKey()
    const shouldUseAuth = refreshLoginState()
    setSubmittedQuestion(trimmedQuestion)
    setMessageId(null)
    setQuestion('')
    setAnswer('')
    setSources([])
    setErrorMessage('')
    setFeedback(null)
    setFeedbackError('')
    setActiveSourceIndex(null)
    setIsStreaming(true)

    eventSourceRef.current = openChatStream({
      question: trimmedQuestion,
      auth: shouldUseAuth,
      sessionKey,
      topK: env.defaultTopK,
      onToken: appendAnswerToken,
      onDone: ({ answer: completedAnswer, messageId: completedMessageId, sources: nextSources }) => {
        flushBufferedAnswerTokens()
        if (completedAnswer) {
          setAnswer(completedAnswer)
        }
        setMessageId(completedMessageId ?? null)
        setSources(nextSources)
        setIsStreaming(false)
        loadHistory()
      },
      onError: (message) => {
        flushBufferedAnswerTokens()
        setErrorMessage(message)
        setIsStreaming(false)
      },
    })
  }

  const stopStream = () => {
    eventSourceRef.current?.close()
    flushBufferedAnswerTokens()
    setIsStreaming(false)
  }

  const handleFeedback = async (nextFeedback) => {
    if (!messageId || isFeedbackSaving || feedback === nextFeedback) return

    const shouldUseAuth = refreshLoginState()
    setFeedbackError('')
    setIsFeedbackSaving(true)

    try {
      const response = await updateChatFeedback(messageId, scoreFromFeedback(nextFeedback), {
        auth: shouldUseAuth,
        sessionKey: getSessionKey(),
      })
      setFeedback(feedbackFromScore(response?.score) ?? nextFeedback)
    } catch (error) {
      setFeedbackError(error.message)
    } finally {
      setIsFeedbackSaving(false)
    }
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
  const canGiveFeedback = Boolean(answer) && Boolean(messageId) && !isStreaming && !errorMessage && !isFeedbackSaving
  const sourceGroups = groupSourcesByDocument(sources)
  const isAdmin = authProfile?.role === 'ADMIN'

  const resetChat = () => {
    eventSourceRef.current?.close()
    resetBufferedAnswerTokens()
    setQuestion('')
    setSubmittedQuestion('')
    setMessageId(null)
    setAnswer('')
    setSources([])
    setErrorMessage('')
    setFeedback(null)
    setFeedbackError('')
    setActiveSourceIndex(null)
    setIsStreaming(false)
    setIsProfileOpen(false)
    setDeleteTarget(null)
  }

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      eventSourceRef.current?.close()
      resetBufferedAnswerTokens()
      setIsLoggedIn(false)
      setIsSidebarOpen(false)
      setIsProfileOpen(false)
      setHistorySessions([])
      setHistoryError('')
      setSubmittedQuestion('')
      setMessageId(null)
      setAnswer('')
      setSources([])
      setFeedback(null)
      setFeedbackError('')
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
              onClick={() => requestHistoryDelete(session)}
              disabled={isStreaming}
              aria-label={`${session.title || '대화'} 삭제`}
            >
              <DeleteIcon />
            </button>
          )}
        </div>
      ))
    }

    return <p className="history-state">최근 질문이 없습니다.</p>
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
      ].filter(Boolean).join(' ')}
    >
      {!isLoggedIn && (
        <>
          <Link className="guest-brand-link" to="/" aria-label="챗봇 홈">
            <img src={inqLogoUrl} alt="InQ" />
          </Link>
          <Link className="login-shortcut" to="/admin/login" aria-label="로그인">
            <LoginIcon />
          </Link>
        </>
      )}

      {isLoggedIn && (
        <aside className="chat-sidebar" aria-label="대화 목록">
          <div className="chat-sidebar__brand">
            <button type="button" className="sidebar-brand-button" onClick={resetChat} aria-label="챗봇 홈">
              <img className="sidebar-brand-button__logo" src={inqLogoUrl} alt="InQ" />
              <img className="sidebar-brand-button__symbol" src={inqSymbolUrl} alt="" />
            </button>
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

          {isAdmin && (
            <Link className="admin-home-link" to="/admin" aria-label="관리자 홈" title="관리자 홈">
              <SettingsIcon />
            </Link>
          )}
        </aside>
      )}

      <section className="chat-main">
        <header className="chat-topbar">
          {isLoggedIn ? (
            <div className="profile-menu" ref={profileMenuRef}>
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
                    <strong>{authProfile?.username || '-'}</strong>
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
                    <img src={inqSymbolUrl} alt="" />
                  </span>
                  <article className="answer-card">
                    <div className="answer-card__header">
                      <strong>인하공전 AI 답변</strong>
                    </div>
                    {answer ? (
                      <p>
                        {renderAnswerText(answer)}
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

                {sourceGroups.length > 0 && (
                  <section className="source-card" aria-label="출처 문서">
                    <h2>출처 문서</h2>
                    <ol className="source-list">
                      {sourceGroups.map((group, index) => (
                        <li key={group.key}>
                          <article className="source-document">
                            <button
                              type="button"
                              className="source-trigger"
                              aria-expanded={activeSourceIndex === index}
                              aria-controls={`source-detail-${index}`}
                              onClick={() => setActiveSourceIndex((prevIndex) => (prevIndex === index ? null : index))}
                            >
                              <strong>{group.title}</strong>
                            </button>
                            {activeSourceIndex === index && (
                              <div id={`source-detail-${index}`} className="source-detail">
                                <dl className="source-detail__meta source-detail__meta--document" aria-label="문서 상세 정보">
                                  {getDocumentInfoMeta(group).map((item) => (
                                    <div key={item}>
                                      <dt className="sr-only">출처 정보</dt>
                                      <dd>{item}</dd>
                                    </div>
                                  ))}
                                </dl>
                                <div className="source-chunk-list" aria-label={`${group.title} 검색 청크 목록`}>
                                  {group.chunks.map(({ source, originalIndex }) => (
                                    <section className="source-chunk" key={`${group.key}-${originalIndex}`}>
                                      <dl className="source-detail__meta" aria-label="청크 상세 정보">
                                        {getSourceDetailMeta(source).map((item) => (
                                          <div key={item}>
                                            <dt className="sr-only">청크 정보</dt>
                                            <dd>{item}</dd>
                                          </div>
                                        ))}
                                      </dl>
                                      <p>{getSourceSnippet(source)}</p>
                                    </section>
                                  ))}
                                </div>
                              </div>
                            )}
                          </article>
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                <div className="feedback-bar" aria-label="답변 피드백">
                  <button
                    type="button"
                    className={
                      feedback === 'positive'
                        ? 'icon-action icon-action--positive icon-action--selected'
                        : 'icon-action icon-action--positive'
                    }
                    onClick={() => handleFeedback('positive')}
                    disabled={!canGiveFeedback}
                    aria-pressed={feedback === 'positive'}
                    aria-label="좋아요"
                    title="좋아요"
                  >
                    <ThumbUpIcon />
                  </button>
                  <button
                    type="button"
                    className={
                      feedback === 'negative'
                        ? 'icon-action icon-action--negative icon-action--selected'
                        : 'icon-action icon-action--negative'
                    }
                    onClick={() => handleFeedback('negative')}
                    disabled={!canGiveFeedback}
                    aria-pressed={feedback === 'negative'}
                    aria-label="싫어요"
                    title="싫어요"
                  >
                    <ThumbDownIcon />
                  </button>
                  {(isFeedbackSaving || feedbackError) && (
                    <span className={feedbackError ? 'feedback-status feedback-status--error' : 'feedback-status'}>
                      {feedbackError || '저장 중'}
                    </span>
                  )}
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

      {deleteTarget && (
        <div
          className="chat-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              cancelHistoryDelete()
            }
          }}
        >
          <section
            ref={deleteModalRef}
            className="chat-confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-history-title"
            tabIndex={-1}
          >
            <h2 id="delete-history-title">질문 기록을 삭제할까요?</h2>
            <p>삭제한 질문 기록은 다시 불러올 수 없습니다.</p>
            <div className="chat-confirm-modal__actions">
              <button type="button" className="chat-modal-secondary" onClick={cancelHistoryDelete}>
                취소
              </button>
              <button type="button" className="chat-modal-danger" onClick={confirmHistoryDelete} disabled={isStreaming}>
                삭제
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  )
}

export default ChatPage
