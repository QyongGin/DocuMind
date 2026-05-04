import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { hasAccessToken } from '../../services/authStorage.js'
import { logout } from '../../services/authApi.js'

function AppLayout() {
  const navigate = useNavigate()
  // 라우트 변경(로그인·로그아웃 후 navigate) 시 컴포넌트를 재렌더링해 isAdmin을 최신 값으로 읽는다
  useLocation()
  const isAdmin = hasAccessToken()

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      navigate('/admin/login')
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink className="brand" to="/">
          <span className="brand-mark">D</span>
          <span>
            <strong>DocuMind</strong>
            <small>On-premise RAG</small>
          </span>
        </NavLink>

        <nav className="app-nav" aria-label="주요 메뉴">
          <NavLink to="/" className={({ isActive }) => (isActive ? 'nav-link nav-link--active' : 'nav-link')}>
            질의응답
          </NavLink>
          <NavLink
            to="/admin"
            className={({ isActive }) => (isActive ? 'nav-link nav-link--active' : 'nav-link')}
          >
            관리자
          </NavLink>
          {isAdmin ? (
            <button type="button" className="nav-button" onClick={handleLogout}>
              로그아웃
            </button>
          ) : (
            <NavLink
              to="/admin/login"
              className={({ isActive }) => (isActive ? 'nav-link nav-link--active' : 'nav-link')}
            >
              로그인
            </NavLink>
          )}
        </nav>
      </header>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}

export default AppLayout
