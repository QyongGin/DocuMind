function AdminDashboardPage() {
  return (
    <section className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Admin Console</p>
          <h1>관리자 대시보드</h1>
        </div>
      </header>

      <div className="dashboard-grid">
        <article className="summary-card">
          <span>문서 관리</span>
          <strong>업로드·목록·삭제</strong>
        </article>
        <article className="summary-card">
          <span>카테고리</span>
          <strong>분류 기준 관리</strong>
        </article>
        <article className="summary-card">
          <span>프롬프트</span>
          <strong>답변 정책 조정</strong>
        </article>
      </div>
    </section>
  )
}

export default AdminDashboardPage
