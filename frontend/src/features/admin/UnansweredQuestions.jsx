import { useEffect, useState } from 'react'
import { getUnansweredQuestions } from '../../services/chatAdminApi.js'
import { DevInfoPanel } from '../chat/DevInfoPanel.jsx'

// 관리자 '못 답한 질문'(ADR-0052 결정 5): 거절 문장만 나간 답의 질문을 최근 것부터 보이고, 질문마다 개발자 정보를 연다
const PAGE_SIZE = 20

function formatAskedAt(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function UnansweredQuestions() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [nextPage, setNextPage] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const loadPage = async (page) => {
    setIsLoading(true)
    setError('')
    try {
      const result = await getUnansweredQuestions({ page, size: PAGE_SIZE })
      const pageItems = Array.isArray(result?.items) ? result.items : []
      setItems((prevItems) => (page === 0 ? pageItems : [...prevItems, ...pageItems]))
      setTotal(result?.total ?? 0)
      setNextPage(page + 1)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadPage(0)
  }, [])

  return (
    <section className="admin-view" aria-labelledby="admin-unanswered-title">
      <div className="admin-section__header">
        <div>
          <p>Unanswered</p>
          <h1 id="admin-unanswered-title">못 답한 질문 {total}개</h1>
        </div>
        <button type="button" className="admin-ghost-button" onClick={() => loadPage(0)} disabled={isLoading}>
          새로고침
        </button>
      </div>

      {error && <p className="admin-toast admin-toast--error">{error}</p>}
      {!error && !isLoading && items.length === 0 && <p className="unanswered-empty">못 답한 질문이 없어요.</p>}

      {items.length > 0 && (
        <ol className="unanswered-list">
          {items.map((item) => (
            <li key={item.messageId} className="unanswered-item">
              <p className="unanswered-item__question">{item.question}</p>
              <p className="unanswered-item__meta">{formatAskedAt(item.askedAt)}</p>
              <DevInfoPanel messageId={item.messageId} className="unanswered-item__dev-info" />
            </li>
          ))}
        </ol>
      )}

      {items.length < total && (
        <button
          type="button"
          className="admin-ghost-button unanswered-more"
          onClick={() => loadPage(nextPage)}
          disabled={isLoading}
        >
          {isLoading ? '불러오는 중' : '더 보기'}
        </button>
      )}
    </section>
  )
}
