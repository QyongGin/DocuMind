const form = document.querySelector('#queryForm')
const questionInput = document.querySelector('#question')
const topKInput = document.querySelector('#topK')
const systemPromptInput = document.querySelector('#systemPrompt')
const includeTraceInput = document.querySelector('#includeTrace')
const answerRendered = document.querySelector('#answerRendered')
const answerRaw = document.querySelector('#answerRaw')
const answerMeta = document.querySelector('#answerMeta')
const sourcesEl = document.querySelector('#sources')
const traceSummary = document.querySelector('#traceSummary')
const traceRaw = document.querySelector('#traceRaw')
const toast = document.querySelector('#toast')
const serverStatus = document.querySelector('#serverStatus')
const submitButton = form.querySelector('button[type="submit"]')

const panels = {
  rendered: document.querySelector('#renderedPanel'),
  raw: document.querySelector('#rawPanel'),
  trace: document.querySelector('#tracePanel'),
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function showToast(message) {
  toast.textContent = message
  toast.hidden = false
  window.clearTimeout(showToast.timer)
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true
  }, 6000)
}

function setActiveTab(name) {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('is-active', tab.dataset.tab === name)
  })
  Object.entries(panels).forEach(([key, panel]) => {
    panel.classList.toggle('is-active', key === name)
  })
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.error || `요청 실패: ${response.status}`)
  }
  return data
}

function buildPayload() {
  return {
    question: questionInput.value.trim(),
    top_k: Number(topKInput.value || 5),
    system_prompt: systemPromptInput.value.trim(),
  }
}

function renderSources(sources) {
  if (!Array.isArray(sources) || sources.length === 0) {
    sourcesEl.innerHTML = ''
    return
  }

  sourcesEl.innerHTML = sources
    .map((source, index) => {
      const headers = Object.entries(source)
        .filter(([key, value]) => key.startsWith('Header') && value)
        .map(([, value]) => value)
        .join(' > ')
      const page = source.page_start || source.page || source.page_end
      const meta = [
        page ? `페이지 ${escapeHtml(page)}` : '',
        source.chunk_index !== undefined && source.chunk_index !== null ? `청크 ${escapeHtml(source.chunk_index)}` : '',
        headers ? `섹션 ${escapeHtml(headers)}` : '',
      ]
        .filter(Boolean)
        .join(' · ')

      return `
        <article class="source-item">
          <strong>출처 ${index + 1}. ${escapeHtml(source.source || '문서명 없음')}</strong>
          <p>${escapeHtml(meta || '위치 정보 없음')}</p>
          <p>${escapeHtml(source.content || '')}</p>
        </article>
      `
    })
    .join('')
}

function metric(label, value) {
  return `
    <div class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? '-')}</strong>
    </div>
  `
}

function renderTraceSummary(summary) {
  if (!summary) {
    traceSummary.innerHTML = ''
    return
  }

  const candidates = Array.isArray(summary.final_candidates) ? summary.final_candidates : []
  const candidateHtml = candidates
    .map((candidate) => {
      const scores = candidate.scores || {}
      const retrieval = candidate.retrieval || {}
      const methods = Array.isArray(retrieval.retrieval_methods) ? retrieval.retrieval_methods.join(', ') : '-'
      const facts = Array.isArray(candidate.query_evidence_facts)
        ? candidate.query_evidence_facts.join('\n')
        : ''

      return `
        <article class="candidate">
          <h3>${escapeHtml(candidate.source || '문서명 없음')} · ${escapeHtml(candidate.chunk_id || '-')}</h3>
          <p>검색 경로: ${escapeHtml(methods)} · 총점: ${escapeHtml(scores.rerank_total ?? '-')} · evidence: ${escapeHtml(scores.query_evidence ?? '-')}</p>
          <p>${escapeHtml(candidate.header_path || candidate.section_scope || '')}</p>
          <p>${escapeHtml(candidate.content_preview || '')}</p>
          ${facts ? `<p><strong>근거</strong><br>${escapeHtml(facts).replaceAll('\n', '<br>')}</p>` : ''}
        </article>
      `
    })
    .join('')

  traceSummary.innerHTML = `
    <div class="metric-grid">
      ${metric('Intent', summary.intent || 'none')}
      ${metric('Vector', summary.vector_count)}
      ${metric('BM25', summary.bm25_count)}
      ${metric('Table fact', summary.table_fact_count)}
      ${metric('Evidence focus', summary.evidence_focus_count)}
      ${metric('Final', summary.final_count)}
      ${metric('Embedding', summary.embedding_elapsed ? `${summary.embedding_elapsed}s` : '-')}
      ${metric('Trace total', summary.total_elapsed ? `${summary.total_elapsed}s` : '-')}
    </div>
    <p>Subject: ${escapeHtml((summary.subject_terms || []).join(', ') || '-')}</p>
    <div class="candidate-list">${candidateHtml}</div>
  `
}

async function runQuery(event) {
  event.preventDefault()
  const payload = buildPayload()

  if (!payload.question) {
    showToast('질문을 입력해야 한다.')
    questionInput.focus()
    return
  }

  submitButton.disabled = true
  submitButton.textContent = '실행 중'
  answerMeta.textContent = 'AI 서버에 질의 중이다.'
  answerRendered.innerHTML = ''
  answerRaw.textContent = ''
  sourcesEl.innerHTML = ''
  traceSummary.innerHTML = ''
  traceRaw.textContent = ''

  try {
    const queryResult = await postJson('/api/query', payload)
    answerRendered.innerHTML = queryResult.answer_html || ''
    answerRaw.textContent = queryResult.answer || ''
    answerMeta.textContent = `AI 서버: ${queryResult.ai_base_url} · 응답 ${queryResult.elapsed}s`
    renderSources(queryResult.sources)
    setActiveTab('rendered')

    if (includeTraceInput.checked) {
      const traceResult = await postJson('/api/trace', payload)
      renderTraceSummary(traceResult.summary)
      traceRaw.textContent = JSON.stringify(traceResult.trace, null, 2)
    }
  } catch (error) {
    answerMeta.textContent = '요청 실패'
    showToast(error.message)
  } finally {
    submitButton.disabled = false
    submitButton.textContent = '질문 실행'
  }
}

async function loadHealth() {
  try {
    const response = await fetch('/api/health')
    const data = await response.json()
    serverStatus.textContent = `AI 서버: ${data.ai_base_url}`
  } catch {
    serverStatus.textContent = '실험 웹 상태 확인 실패'
  }
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => setActiveTab(tab.dataset.tab))
})

document.querySelectorAll('[data-question]').forEach((button) => {
  button.addEventListener('click', () => {
    questionInput.value = button.dataset.question
    questionInput.focus()
  })
})

form.addEventListener('submit', runQuery)
loadHealth()
