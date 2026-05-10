import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { logout } from '../../services/authApi.js'
import { createCategory, listCategories } from '../../services/categoryApi.js'
import { deleteDocument, listDocumentChunks, listDocuments, uploadDocument } from '../../services/documentApi.js'
import { getFeedbackStats } from '../../services/feedbackStatsApi.js'
import { getPromptConfig, updatePromptConfig } from '../../services/promptApi.js'
import inqLogoUrl from '../../images/inq-logo.png'
import inqSymbolUrl from '../../images/inq-symbol.png'

function formatFileSize(size) {
  if (!Number.isFinite(size) || size <= 0) return '-'
  if (size < 1024 * 1024) return `${Math.round(size / 1024)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

function formatDateTime(value) {
  if (!value) return '저장 전'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '저장 전'
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function formatDuration(durationMs) {
  if (!Number.isFinite(durationMs) || durationMs < 0) return null
  if (durationMs < 1000) return `${durationMs}ms`

  const totalSeconds = durationMs / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}초`

  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60).toString().padStart(2, '0')
  return `${minutes}분 ${seconds}초`
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function formatPercent(rate) {
  const percent = Number(rate) * 100
  if (!Number.isFinite(percent)) return '0%'
  return `${Math.round(percent)}%`
}

function AdminDashboardPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)
  const [documents, setDocuments] = useState([])
  const [categories, setCategories] = useState([])
  const [feedbackStats, setFeedbackStats] = useState({
    totalCount: 0,
    positiveCount: 0,
    negativeCount: 0,
    positiveRate: 0,
  })
  const [selectedCategory, setSelectedCategory] = useState('전체')
  const [selectedFile, setSelectedFile] = useState(null)
  const [selectedUploadCategoryId, setSelectedUploadCategoryId] = useState('')
  const [categoryName, setCategoryName] = useState('')
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [lastUploadSummary, setLastUploadSummary] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [isUploadDragActive, setIsUploadDragActive] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isRailCollapsed, setIsRailCollapsed] = useState(false)
  const [activeSection, setActiveSection] = useState('dashboard')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [selectedDocument, setSelectedDocument] = useState(null)
  const [documentChunks, setDocumentChunks] = useState([])
  const [isChunksLoading, setIsChunksLoading] = useState(false)
  const [chunksErrorMessage, setChunksErrorMessage] = useState('')
  const [promptConfig, setPromptConfig] = useState(null)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [promptMessage, setPromptMessage] = useState('')
  const [promptErrorMessage, setPromptErrorMessage] = useState('')
  const [isPromptLoading, setIsPromptLoading] = useState(true)
  const [isPromptSaving, setIsPromptSaving] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)

  const filteredDocuments = useMemo(() => {
    if (selectedCategory === '전체') return documents
    return documents.filter((document) => (document.categoryName || '미분류') === selectedCategory)
  }, [documents, selectedCategory])

  const hasProcessingDocuments = useMemo(
    () => documents.some((document) => document.processingStatus === 'PROCESSING'),
    [documents],
  )

  const totalChunks = documents.reduce((sum, document) => sum + (document.chunkCount ?? 0), 0)
  const isPromptDirty = systemPrompt !== (promptConfig?.systemPrompt ?? '')

  const loadDashboard = async ({ silent = false, throwOnError = false } = {}) => {
    if (!silent) {
      setIsLoading(true)
      setErrorMessage('')
    }

    try {
      const [nextDocuments, nextCategories, nextFeedbackStats] = await Promise.all([
        listDocuments(),
        listCategories(),
        getFeedbackStats(),
      ])
      const normalizedDocuments = Array.isArray(nextDocuments) ? nextDocuments : []
      setDocuments(normalizedDocuments)
      setCategories(Array.isArray(nextCategories) ? nextCategories : [])
      setFeedbackStats(nextFeedbackStats ?? {
        totalCount: 0,
        positiveCount: 0,
        negativeCount: 0,
        positiveRate: 0,
      })
      return normalizedDocuments
    } catch (error) {
      if (!silent) {
        setErrorMessage(error.message)
      }
      if (throwOnError) {
        throw error
      }
      return []
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }

  const loadPromptConfig = async () => {
    setIsPromptLoading(true)
    setPromptErrorMessage('')

    try {
      const nextPromptConfig = await getPromptConfig()
      setPromptConfig(nextPromptConfig)
      setSystemPrompt(nextPromptConfig?.systemPrompt ?? '')
    } catch (error) {
      setPromptErrorMessage(error.message)
    } finally {
      setIsPromptLoading(false)
    }
  }

  useEffect(() => {
    loadDashboard()
    loadPromptConfig()
  }, [])

  useEffect(() => {
    if (!hasProcessingDocuments || isUploading) return undefined

    const intervalId = window.setInterval(() => {
      loadDashboard({ silent: true })
    }, 2500)

    return () => window.clearInterval(intervalId)
  }, [hasProcessingDocuments, isUploading])

  const waitForDocumentProcessing = async (documentId) => {
    const startedAt = Date.now()
    const timeoutMs = 20 * 60 * 1000

    while (Date.now() - startedAt < timeoutMs) {
      const nextDocuments = await loadDashboard({ silent: true, throwOnError: true })
      const targetDocument = nextDocuments.find((document) => String(document.id) === String(documentId))

      if (targetDocument?.processingStatus === 'READY' || targetDocument?.processingStatus == null) {
        return targetDocument
      }

      if (targetDocument?.processingStatus === 'FAILED') {
        throw new Error('문서 색인 처리에 실패했습니다. ai-server 로그를 확인해야 합니다.')
      }

      await sleep(2500)
    }

    throw new Error('문서 처리 결과 확인 시간이 초과되었습니다. 목록을 새로고침해 상태를 확인해 주세요.')
  }

  const showUploadComplete = (document) => {
    setLastUploadSummary({
      originalName: document?.originalName ?? '',
      chunkCount: document?.chunkCount ?? 0,
      processingDurationMs: document?.processingDurationMs ?? null,
    })
    setMessage('문서 처리가 완료되었습니다.')
  }

  const resetSelectedFile = () => {
    setSelectedFile(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleSelectFile = (file) => {
    if (!file || isUploading) return

    setSelectedFile(file)
    setMessage('')
    setErrorMessage('')
    setLastUploadSummary(null)
  }

  const handleFileInputChange = (event) => {
    handleSelectFile(event.target.files?.[0] ?? null)
  }

  const handleUploadDragEnter = (event) => {
    event.preventDefault()
    event.stopPropagation()
    if (!isUploading && !isUploadDragActive) {
      setIsUploadDragActive(true)
    }
  }

  const handleUploadDragOver = (event) => {
    event.preventDefault()
    event.stopPropagation()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = isUploading ? 'none' : 'copy'
    }
    if (!isUploading && !isUploadDragActive) {
      setIsUploadDragActive(true)
    }
  }

  const handleUploadDragLeave = (event) => {
    event.preventDefault()
    event.stopPropagation()

    const nextTarget = event.relatedTarget
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return
    setIsUploadDragActive(false)
  }

  const handleUploadDrop = (event) => {
    event.preventDefault()
    event.stopPropagation()
    setIsUploadDragActive(false)

    if (isUploading) return
    handleSelectFile(event.dataTransfer.files?.[0] ?? null)
  }

  const handleUpload = async (event) => {
    event.preventDefault()
    if (!selectedFile || isUploading) return

    setIsUploading(true)
    setMessage('')
    setErrorMessage('')
    setLastUploadSummary(null)

    try {
      const uploadResult = await uploadDocument(selectedFile, { categoryId: selectedUploadCategoryId })
      resetSelectedFile()
      if (uploadResult?.processingStatus === 'PROCESSING') {
        const completedDocument = await waitForDocumentProcessing(uploadResult.documentId)
        showUploadComplete(completedDocument)
        return
      }

      await loadDashboard({ silent: true })
      showUploadComplete(uploadResult)
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setIsUploading(false)
    }
  }

  const handleCreateCategory = async (event) => {
    event.preventDefault()
    const trimmedName = categoryName.trim()
    if (!trimmedName) return

    setMessage('')
    setErrorMessage('')
    setLastUploadSummary(null)

    try {
      await createCategory(trimmedName)
      setCategoryName('')
      setMessage('카테고리를 추가했습니다.')
      await loadDashboard()
    } catch (error) {
      setErrorMessage(error.message)
    }
  }

  const handleConfirmDeleteDocument = async () => {
    if (!deleteTarget || isUploading || isDeleting) return

    setMessage('')
    setErrorMessage('')
    setLastUploadSummary(null)
    setIsDeleting(true)

    try {
      await deleteDocument(deleteTarget.id)
      setMessage('문서를 삭제했습니다.')
      setDocuments((prevDocuments) => prevDocuments.filter((document) => document.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setIsDeleting(false)
    }
  }

  const handleOpenDocumentChunks = async (document) => {
    setSelectedDocument(document)
    setDocumentChunks([])
    setChunksErrorMessage('')
    setIsChunksLoading(true)

    try {
      const chunks = await listDocumentChunks(document.id)
      setDocumentChunks(Array.isArray(chunks) ? chunks : [])
    } catch (error) {
      setChunksErrorMessage(error.message)
    } finally {
      setIsChunksLoading(false)
    }
  }

  const handleCloseNotice = () => {
    setMessage('')
    setErrorMessage('')
    setLastUploadSummary(null)
  }

  const handleSavePrompt = async (event) => {
    event.preventDefault()
    const trimmedPrompt = systemPrompt.trim()
    if (!trimmedPrompt || isPromptSaving) return

    setPromptMessage('')
    setPromptErrorMessage('')
    setIsPromptSaving(true)

    try {
      const updatedPromptConfig = await updatePromptConfig(trimmedPrompt)
      setPromptConfig(updatedPromptConfig)
      setSystemPrompt(updatedPromptConfig?.systemPrompt ?? trimmedPrompt)
      setPromptMessage('프롬프트 설정을 저장했습니다.')
    } catch (error) {
      setPromptErrorMessage(error.message)
    } finally {
      setIsPromptSaving(false)
    }
  }

  const handleLogout = async () => {
    setIsLoggingOut(true)

    try {
      await logout()
    } finally {
      navigate('/admin/login')
    }
  }

  return (
    <section className={isRailCollapsed ? 'admin-surface admin-surface--rail-collapsed' : 'admin-surface'}>
      <aside className="admin-rail" aria-label="관리자 메뉴">
        <div className="admin-rail__top">
          <Link className="admin-brand-link" to="/" aria-label="챗봇 홈으로 이동">
            <img className="admin-brand-link__logo" src={inqLogoUrl} alt="InQ" />
            <img className="admin-brand-link__symbol" src={inqSymbolUrl} alt="" />
          </Link>
          <button
            type="button"
            className="admin-rail__toggle"
            aria-label={isRailCollapsed ? '관리자 사이드바 열기' : '관리자 사이드바 닫기'}
            aria-expanded={!isRailCollapsed}
            onClick={() => setIsRailCollapsed((prev) => !prev)}
          >
            <span aria-hidden="true" />
          </button>
        </div>

        <nav className="admin-rail__nav" aria-label="관리자 섹션">
          <button
            type="button"
            className={activeSection === 'dashboard' ? 'admin-rail__item admin-rail__item--active' : 'admin-rail__item'}
            onClick={() => setActiveSection('dashboard')}
          >
            대시보드
          </button>
          <button
            type="button"
            className={activeSection === 'documents' ? 'admin-rail__item admin-rail__item--active' : 'admin-rail__item'}
            onClick={() => setActiveSection('documents')}
          >
            문서
          </button>
          <button
            type="button"
            className={activeSection === 'prompt' ? 'admin-rail__item admin-rail__item--active' : 'admin-rail__item'}
            onClick={() => setActiveSection('prompt')}
          >
            프롬프트
          </button>
        </nav>

        <div className="admin-rail__bottom">
          <button
            type="button"
            className="admin-rail__logout"
            onClick={handleLogout}
            disabled={isLoggingOut}
          >
            {isLoggingOut ? '로그아웃 중' : '로그아웃'}
          </button>
        </div>
      </aside>

      <main className="admin-main">
        {activeSection === 'dashboard' && (
          <section className="admin-view" aria-labelledby="admin-dashboard-title">
            <header className="admin-hero">
              <div>
                <p>Admin Console</p>
                <h1 id="admin-dashboard-title">관리자 대시보드</h1>
              </div>
              <button type="button" className="admin-ghost-button" onClick={loadDashboard} disabled={isLoading}>
                새로고침
              </button>
            </header>

            <section className="admin-metrics" aria-label="시스템 요약">
              <article>
                <span>문서</span>
                <strong>{documents.length}</strong>
              </article>
              <article>
                <span>청크</span>
                <strong>{totalChunks}</strong>
              </article>
              <article>
                <span>카테고리</span>
                <strong>{categories.length}</strong>
              </article>
            </section>

            <section className="feedback-summary" aria-label="답변 피드백 요약">
              <header>
                <div>
                  <span>답변 피드백</span>
                  <strong>{formatPercent(feedbackStats.positiveRate)} 긍정</strong>
                </div>
                <p>총 {feedbackStats.totalCount}건</p>
              </header>
              <div
                className="feedback-summary__bar"
                role="img"
                aria-label={`좋아요 ${feedbackStats.positiveCount}건, 싫어요 ${feedbackStats.negativeCount}건`}
              >
                <span
                  className="feedback-summary__bar-positive"
                  style={{ width: feedbackStats.totalCount > 0 ? formatPercent(feedbackStats.positiveRate) : '0%' }}
                />
                <span
                  className="feedback-summary__bar-negative"
                  style={{ width: feedbackStats.totalCount > 0 ? formatPercent(1 - feedbackStats.positiveRate) : '0%' }}
                />
              </div>
              <div className="feedback-summary__legend">
                <span>
                  <i className="feedback-summary__dot feedback-summary__dot--positive" aria-hidden="true" />
                  좋아요 {feedbackStats.positiveCount}
                </span>
                <span>
                  <i className="feedback-summary__dot feedback-summary__dot--negative" aria-hidden="true" />
                  싫어요 {feedbackStats.negativeCount}
                </span>
              </div>
            </section>
          </section>
        )}

        {activeSection === 'documents' && (
          <section className="admin-view" aria-labelledby="admin-documents-title">
            <div className="admin-section__header">
              <div>
                <p>Documents</p>
                <h1 id="admin-documents-title">문서 관리</h1>
              </div>
              <div className="category-filter" aria-label="카테고리 필터">
                {['전체', ...categories.map((category) => category.name), '미분류'].map((name) => (
                  <button
                    key={name}
                    type="button"
                    className={selectedCategory === name ? 'filter-chip filter-chip--active' : 'filter-chip'}
                    onClick={() => setSelectedCategory(name)}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>

            <div className="document-grid">
              <form className="upload-panel" onSubmit={handleUpload}>
                <label
                  className={[
                    'upload-drop',
                    isUploadDragActive ? 'upload-drop--active' : '',
                    isUploading ? 'upload-drop--disabled' : '',
                  ].filter(Boolean).join(' ')}
                  onDragEnter={handleUploadDragEnter}
                  onDragOver={handleUploadDragOver}
                  onDragLeave={handleUploadDragLeave}
                  onDrop={handleUploadDrop}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.docx,.pptx,.xlsx"
                    onChange={handleFileInputChange}
                    disabled={isUploading}
                  />
                  <span>{selectedFile ? selectedFile.name : 'PDF, DOCX, PPTX, XLSX 업로드'}</span>
                  <small>{selectedFile ? formatFileSize(selectedFile.size) : '학교 안내 문서를 추가합니다.'}</small>
                </label>
                <label className="upload-category">
                  문서 카테고리
                  <select
                    value={selectedUploadCategoryId}
                    onChange={(event) => setSelectedUploadCategoryId(event.target.value)}
                    disabled={isUploading}
                  >
                    <option value="">미분류</option>
                    {categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="submit" className="admin-primary-button" disabled={!selectedFile || isUploading}>
                  {isUploading ? '업로드 중' : '업로드'}
                </button>
              </form>

              <form className="category-panel" onSubmit={handleCreateCategory}>
                <label>
                  카테고리 추가
                  <input
                    value={categoryName}
                    onChange={(event) => setCategoryName(event.target.value)}
                    placeholder="예: 입학"
                  />
                </label>
                <button type="submit" className="admin-ghost-button" disabled={!categoryName.trim()}>
                  추가
                </button>
              </form>
            </div>

            <div className="document-list" aria-label="문서 목록">
              {isLoading ? (
                <p className="admin-empty">문서를 불러오는 중입니다.</p>
              ) : filteredDocuments.length > 0 ? (
                filteredDocuments.map((document) => (
                  <article key={document.id} className="document-row">
                    <button
                      type="button"
                      className="document-row__open"
                      onClick={() => handleOpenDocumentChunks(document)}
                      disabled={document.processingStatus !== 'READY' && document.processingStatus != null}
                    >
                      <span>
                        <strong>{document.originalName}</strong>
                        <span className="document-row__meta">
                          <small>
                            {document.categoryName || '미분류'} · {formatFileSize(document.fileSize)} · {document.chunkCount} chunks
                            {formatDuration(document.processingDurationMs) && ` · 처리 ${formatDuration(document.processingDurationMs)}`}
                          </small>
                        </span>
                      </span>
                    </button>
                    <time>{formatDate(document.createdAt)}</time>
                    <button
                      type="button"
                      className="admin-text-button admin-text-button--delete"
                      onClick={() => setDeleteTarget(document)}
                      disabled={isUploading || isDeleting || document.processingStatus === 'PROCESSING'}
                    >
                      삭제
                    </button>
                  </article>
                ))
              ) : (
                <p className="admin-empty">등록된 문서가 없습니다.</p>
              )}
            </div>
          </section>
        )}

        {activeSection === 'prompt' && (
          <section className="admin-view" aria-labelledby="admin-prompt-title">
            <div className="admin-section__header">
              <div>
                <p>Prompt</p>
                <h1 id="admin-prompt-title">답변 정책</h1>
              </div>
            </div>
            <form className="prompt-panel" onSubmit={handleSavePrompt}>
              <label>
                시스템 프롬프트
                <textarea
                  value={systemPrompt}
                  onChange={(event) => {
                    setSystemPrompt(event.target.value)
                    setPromptMessage('')
                    setPromptErrorMessage('')
                  }}
                  disabled={isPromptLoading || isPromptSaving}
                  rows={5}
                />
              </label>
              <div className="prompt-panel__meta">
                <span>마지막 저장: {formatDateTime(promptConfig?.updatedAt)}</span>
                <span>수정 관리자: {promptConfig?.updatedByUsername || '-'}</span>
              </div>
              {promptMessage && <p className="prompt-panel__message">{promptMessage}</p>}
              {promptErrorMessage && (
                <p className="prompt-panel__message prompt-panel__message--error">{promptErrorMessage}</p>
              )}
              <button
                type="submit"
                className="admin-primary-button"
                disabled={isPromptLoading || isPromptSaving || !systemPrompt.trim() || !isPromptDirty}
              >
                {isPromptSaving ? '저장 중' : '저장'}
              </button>
            </form>
          </section>
        )}
      </main>

      {isUploading && (
        <div className="admin-modal-backdrop" role="presentation">
          <section
            className="admin-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-uploading-title"
          >
            <p>업로드 중</p>
            <h2 id="admin-uploading-title">문서를 처리하고 있습니다</h2>
            <span>청킹과 임베딩 색인이 끝나면 결과를 표시합니다.</span>
          </section>
        </div>
      )}

      {!isUploading && (message || errorMessage) && (
        <div className="admin-modal-backdrop" role="presentation">
          <section
            className={errorMessage ? 'admin-modal admin-modal--error' : 'admin-modal'}
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-notice-title"
          >
            <p>{errorMessage ? '처리할 수 없습니다' : '완료'}</p>
            <h2 id="admin-notice-title">{errorMessage || message}</h2>
            {!errorMessage && lastUploadSummary && (
              <span>
                청크 {lastUploadSummary.chunkCount}개
                {formatDuration(lastUploadSummary.processingDurationMs)
                  ? ` · 처리 시간 ${formatDuration(lastUploadSummary.processingDurationMs)}`
                  : ''}
              </span>
            )}
            <button type="button" className="admin-primary-button" onClick={handleCloseNotice}>
              확인
            </button>
          </section>
        </div>
      )}

      {deleteTarget && (
        <div className="admin-modal-backdrop" role="presentation">
          <section
            className="admin-modal admin-modal--danger"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-delete-title"
          >
            <p>문서 삭제</p>
            <h2 id="admin-delete-title">정말 삭제할까요?</h2>
            <span>{deleteTarget.originalName}</span>
            {isUploading && <small className="admin-modal__hint">업로드 중에는 삭제할 수 없습니다.</small>}
            <div className="admin-modal__actions">
              <button type="button" className="admin-ghost-button" onClick={() => setDeleteTarget(null)}>
                취소
              </button>
              <button
                type="button"
                className="admin-danger-button"
                onClick={handleConfirmDeleteDocument}
                disabled={isUploading || isDeleting}
              >
                {isDeleting ? '삭제 중' : '삭제'}
              </button>
            </div>
          </section>
        </div>
      )}

      {selectedDocument && (
        <div className="admin-modal-backdrop" role="presentation">
          <section
            className="admin-modal admin-modal--wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-chunks-title"
          >
            <div className="admin-modal__header">
              <div>
                <p>Document Chunks</p>
                <h2 id="admin-chunks-title">{selectedDocument.originalName}</h2>
              </div>
              <button type="button" className="admin-text-button" onClick={() => setSelectedDocument(null)}>
                닫기
              </button>
            </div>

            <div className="chunk-list">
              {isChunksLoading ? (
                <p className="admin-empty">청크를 불러오는 중입니다.</p>
              ) : chunksErrorMessage ? (
                <p className="admin-empty">{chunksErrorMessage}</p>
              ) : documentChunks.length > 0 ? (
                documentChunks.map((chunk) => (
                  <article key={chunk.id || chunk.chunkIndex} className="chunk-card">
                    <header>
                      <strong>Chunk {chunk.chunkIndex + 1}</strong>
                      <span>{chunk.id}</span>
                    </header>
                    <p>{chunk.content}</p>
                  </article>
                ))
              ) : (
                <p className="admin-empty">저장된 청크가 없습니다.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </section>
  )
}

export default AdminDashboardPage
