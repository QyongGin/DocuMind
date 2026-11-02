import { useState } from 'react'
import { getChatDevInfo } from '../../services/chatAdminApi.js'

// 관리자 개발자 모드(ADR-0050 결정 6, ADR-0052, docs/project/챗봇-답변-형식.md §4).
// 열 때 관리자 API에서 답 하나의 원문 답, 화면 처리 내역, 근거 후보와 검색 점수, 단계별 걸린 시간, 프롬프트를 받아 온다
const STAGES = [
  ['embedding', '임베딩'],
  ['vector_search', '벡터 검색'],
  ['lexical_search', '키워드 검색'],
  ['rerank', '재순위'],
  ['context_build', '근거 블록 만들기'],
  ['prepare', '검색 전체'],
  ['first_token', '첫 글자까지'],
  ['generation', '생성'],
  ['total', '전체'],
]

const RETRIEVERS = {
  vector: '벡터',
  retrieval_chunk_vector: '벡터(검색용 청크)',
  bm25: '키워드',
  table_fact_lexical: '표 사실',
}

function sourceTitle(source, index) {
  return source?.document_original_name || source?.source || `근거 ${index + 1}`
}

function chunkLabel(source) {
  const chunkNumber = Number(source?.chunk_index)
  if (source?.chunk_index === null || source?.chunk_index === undefined || !Number.isFinite(chunkNumber)) return ''
  return `문서 안 ${chunkNumber + 1}번째 청크`
}

function formatNumber(value) {
  return typeof value === 'number' ? String(Number(value.toFixed(3))) : null
}

function candidateScores(candidate) {
  if (!candidate) return []
  const retrieval = candidate.retrieval ?? {}
  return [
    ['찾은 검색기', (retrieval.retrieval_methods ?? []).map((name) => RETRIEVERS[name] ?? name).join(', ')],
    ['벡터 거리', formatNumber(retrieval.vector_distance)],
    ['키워드 점수', formatNumber(retrieval.bm25_score)],
    ['표 사실 점수', formatNumber(retrieval.table_fact_score)],
    ['순위 융합', candidate.fused_rank ? `${candidate.fused_rank}위` : null],
    ['재순위 점수', formatNumber(candidate.rerank_score)],
  ].filter(([, value]) => value)
}

function Scores({ items, label }) {
  if (!items.length) return null

  return (
    <dl className="dev-info__scores" aria-label={label}>
      {items.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function DevInfoContent({ info }) {
  const trace = info.trace
  const sources = Array.isArray(info.sources) ? info.sources : []
  const candidates = Array.isArray(trace?.candidates) ? trace.candidates : []
  const cited = new Set(info.citedSources ?? [])
  const count = Math.max(sources.length, candidates.length)
  const stageSeconds = STAGES.filter(([key]) => typeof trace?.seconds?.[key] === 'number').map(([key, label]) => [
    label,
    `${trace.seconds[key].toFixed(2)}초`,
  ])

  return (
    <>
      <section className="dev-info__block">
        <h3>모델 원문 답</h3>
        <p className="dev-info__raw">{info.rawAnswer || '저장된 답이 없어요.'}</p>
        <p className="dev-info__note">
          {cited.size > 0 ? `지운 출처 번호 ${[...cited].join(', ')}` : '지운 출처 번호 없음'}
          {info.guidanceAttached ? ', 정해 둔 안내 붙임' : ''}
        </p>
      </section>

      <section className="dev-info__block">
        <h3>근거 후보 {count}개</h3>
        <ol className="dev-info__candidates">
          {Array.from({ length: count }, (_, index) => (
            <li key={index} className="dev-info__candidate">
              <p className="dev-info__candidate-title">
                <span>
                  [출처 {index + 1}] {sourceTitle(sources[index], index)}
                </span>
                {cited.has(index + 1) && <strong className="dev-info__cited">답이 씀</strong>}
              </p>
              {chunkLabel(sources[index]) && <p className="dev-info__note">{chunkLabel(sources[index])}</p>}
              <Scores items={candidateScores(candidates[index])} label={`출처 ${index + 1} 검색 점수`} />
              {sources[index]?.content && <p className="dev-info__snippet">{sources[index].content}</p>}
            </li>
          ))}
        </ol>
      </section>

      {trace ? (
        <>
          <section className="dev-info__block">
            <h3>단계별 걸린 시간</h3>
            <Scores items={stageSeconds} label="단계별 걸린 시간" />
            <p className="dev-info__note">
              모델 {trace.model?.llm_model ?? '알 수 없음'}, 재순위 {trace.rerank?.used ? '씀' : '안 씀'}
            </p>
          </section>
          <section className="dev-info__block">
            <h3>프롬프트</h3>
            {trace.prompt ? (
              <details className="dev-info__prompt">
                <summary>프롬프트 보기({trace.prompt.length.toLocaleString()}자)</summary>
                <pre>{trace.prompt}</pre>
              </details>
            ) : (
              <p className="dev-info__note">근거가 없어 프롬프트를 만들지 않았어요.</p>
            )}
          </section>
        </>
      ) : (
        <p className="dev-info__note">처리 기록이 없어요. 30일이 지났거나 기록을 남기기 전 답이에요.</p>
      )}
    </>
  )
}

// className은 놓이는 자리의 바깥 모양(채팅 답 아래는 source-card, 관리자 목록은 그 목록의 모양)
export function DevInfoPanel({ messageId, className = 'source-card' }) {
  const [isOpen, setIsOpen] = useState(false)
  const [info, setInfo] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const panelId = `dev-info-${messageId}`

  const toggle = async () => {
    if (isOpen) {
      setIsOpen(false)
      return
    }
    setIsOpen(true)
    if (info || isLoading) return

    setIsLoading(true)
    setError('')
    try {
      setInfo(await getChatDevInfo(messageId))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <section className={`${className} dev-info`} aria-label="개발자 정보">
      <button
        type="button"
        className="dev-info__toggle"
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={toggle}
      >
        {isOpen ? '개발자 정보 닫기' : '개발자 정보 보기'}
      </button>
      {isOpen && (
        <div id={panelId} className="dev-info__body">
          {isLoading && <p className="dev-info__note">불러오는 중</p>}
          {error && <p className="error">{error}</p>}
          {info && <DevInfoContent info={info} />}
        </div>
      )}
    </section>
  )
}
