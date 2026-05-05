import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout.jsx'
import AdminDashboardPage from './features/admin/AdminDashboardPage.jsx'
import LoginPage from './features/admin/LoginPage.jsx'
import ChatPage from './features/chat/ChatPage.jsx'
import NotFoundPage from './features/not-found/NotFoundPage.jsx'
import { verifyAccessToken } from './services/authApi.js'
import { clearTokens, hasAccessToken } from './services/authStorage.js'
import './App.css'

/**
 * 관리자 전용 라우트 보호 컴포넌트.
 * 마운트 시 서버에 JWT 유효성을 검증하고, 만료·위조·권한 없음이면 로그인 화면으로 리다이렉트한다.
 * localStorage 단독 검사와 달리 서버 서명과 만료 시간까지 확인한다.
 */
function RequireAdmin({ children }) {
  // lazy initializer로 렌더 전에 토큰 존재 여부를 확인한다.
  // 토큰이 없으면 effect 없이 바로 redirect 처리한다.
  const [status, setStatus] = useState(() =>
    hasAccessToken() ? 'pending' : 'redirect'
  )

  useEffect(() => {
    // status가 pending이 아니면 이미 처리 완료 (no-op 반환)
    if (status !== 'pending') return

    let cancelled = false

    verifyAccessToken()
      .then(() => { if (!cancelled) setStatus('ok') })
      .catch(() => {
        if (cancelled) return
        clearTokens()
        setStatus('redirect')
      })

    return () => { cancelled = true }
  }, [status])

  if (status === 'pending') return null
  if (status === 'redirect') return <Navigate to="/admin/login" replace />
  return children
}

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<ChatPage />} />
        <Route path="admin/login" element={<LoginPage />} />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <AdminDashboardPage />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
