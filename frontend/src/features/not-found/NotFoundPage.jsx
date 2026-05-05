import { Link } from 'react-router-dom'

function NotFoundPage() {
  return (
    <section className="page page--compact">
      <header className="page-header">
        <div>
          <p className="eyebrow">404</p>
          <h1>페이지를 찾을 수 없습니다</h1>
        </div>
      </header>

      <Link className="text-link" to="/">
        질의응답으로 이동
      </Link>
    </section>
  )
}

export default NotFoundPage
