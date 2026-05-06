import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { createCategory, listCategories } from '../../services/categoryApi.js'
import { deleteDocument, listDocumentChunks, listDocuments, uploadDocument } from '../../services/documentApi.js'
import inhaBadgeUrl from '../../images/inha-badge.svg'

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

function formatDuration(durationMs) {
  if (!Number.isFinite(durationMs) || durationMs < 0) return null
  if (durationMs < 1000) return `${durationMs}ms`

  const totalSeconds = durationMs / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}초`

  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60).toString().padStart(2, '0')
  return `${minutes}분 ${seconds}초`
}

function AdminDashboardPage() {
  const [documents, setDocuments] = useState([])
  const [categories, setCategories] = useState([])
  const [selectedCategory, setSelectedCategory] = useState('전체')
  const [selectedFile, setSelectedFile] = useState(null)
  const [selectedUploadCategoryId, setSelectedUploadCategoryId] = useState('')
  const [categoryName, setCategoryName] = useState('')
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [lastUploadDurationMs, setLastUploadDurationMs] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [isRailCollapsed, setIsRailCollapsed] = useState(false)
  const [activeSection, setActiveSection] = useState('dashboard')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [selectedDocument, setSelectedDocument] = useState(null)
  const [documentChunks, setDocumentChunks] = useState([])
  const [isChunksLoading, setIsChunksLoading] = useState(false)
  const [chunksErrorMessage, setChunksErrorMessage] = useState('')

  const filteredDocuments = useMemo(() => {
    if (selectedCategory === '전체') return documents
    return documents.filter((document) => (document.categoryName || '미분류') === selectedCategory)
  }, [documents, selectedCategory])

  const totalChunks = documents.reduce((sum, document) => sum + (document.chunkCount ?? 0), 0)

  const loadDashboard = async () => {
    setIsLoading(true)
    setErrorMessage('')

    try {
      const [nextDocuments, nextCategories] = await Promise.all([
        listDocuments(),
        listCategories(),
      ])
      setDocuments(Array.isArray(nextDocuments) ? nextDocuments : [])
      setCategories(Array.isArray(nextCategories) ? nextCategories : [])
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  const handleUpload = async (event) => {
    event.preventDefault()
    if (!selectedFile || isUploading) return

    setIsUploading(true)
    setMessage('')
    setErrorMessage('')
    setLastUploadDurationMs(null)

    try {
      const uploadResult = await uploadDocument(selectedFile, { categoryId: selectedUploadCategoryId })
      setSelectedFile(null)
      setLastUploadDurationMs(uploadResult?.processingDurationMs ?? null)
      setMessage('문서를 업로드했습니다.')
      await loadDashboard()
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
    setLastUploadDurationMs(null)

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
    if (!deleteTarget) return

    setMessage('')
    setErrorMessage('')
    setLastUploadDurationMs(null)

    try {
      await deleteDocument(deleteTarget.id)
      setMessage('문서를 삭제했습니다.')
      setDocuments((prevDocuments) => prevDocuments.filter((document) => document.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (error) {
      setErrorMessage(error.message)
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
    setLastUploadDurationMs(null)
  }

  return (
    <section className={isRailCollapsed ? 'admin-surface admin-surface--rail-collapsed' : 'admin-surface'}>
      <aside className="admin-rail" aria-label="관리자 메뉴">
        <div className="admin-rail__top">
          <Link className="admin-brand-link" to="/" aria-label="챗봇 홈으로 이동">
            <img src={inhaBadgeUrl} alt="" />
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
                <label className="upload-drop">
                  <input
                    type="file"
                    accept=".pdf,.docx,.pptx,.xlsx"
                    onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
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
                    >
                      <span>
                        <strong>{document.originalName}</strong>
                        <small>
                          {document.categoryName || '미분류'} · {formatFileSize(document.fileSize)} · {document.chunkCount} chunks
                          {formatDuration(document.processingDurationMs) && ` · 처리 ${formatDuration(document.processingDurationMs)}`}
                        </small>
                      </span>
                    </button>
                    <time>{formatDate(document.createdAt)}</time>
                    <button type="button" className="admin-text-button" onClick={() => setDeleteTarget(document)}>
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
            <div className="prompt-panel">
              <label>
                시스템 프롬프트
                <textarea
                  defaultValue="인하공업전문대학 홈페이지와 학사 안내 문서에 근거해서 간결하고 정확하게 답변한다."
                  rows={5}
                />
              </label>
              <button type="button" className="admin-primary-button" disabled>
                저장 API 연결 예정
              </button>
            </div>
          </section>
        )}
      </main>

      {(message || errorMessage) && (
        <div className="admin-modal-backdrop" role="presentation">
          <section
            className={errorMessage ? 'admin-modal admin-modal--error' : 'admin-modal'}
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-notice-title"
          >
            <p>{errorMessage ? '처리할 수 없습니다' : '완료'}</p>
            <h2 id="admin-notice-title">{errorMessage || message}</h2>
            {!errorMessage && formatDuration(lastUploadDurationMs) && (
              <span>처리 시간 {formatDuration(lastUploadDurationMs)}</span>
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
            <div className="admin-modal__actions">
              <button type="button" className="admin-ghost-button" onClick={() => setDeleteTarget(null)}>
                취소
              </button>
              <button type="button" className="admin-danger-button" onClick={handleConfirmDeleteDocument}>
                삭제
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
