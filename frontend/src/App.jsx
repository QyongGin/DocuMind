import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout.jsx'
import AdminDashboardPage from './features/admin/AdminDashboardPage.jsx'
import LoginPage from './features/admin/LoginPage.jsx'
import ChatPage from './features/chat/ChatPage.jsx'
import NotFoundPage from './features/not-found/NotFoundPage.jsx'
import { hasAccessToken } from './services/authStorage.js'
import './App.css'

function RequireAdmin({ children }) {
  if (!hasAccessToken()) {
    return <Navigate to="/admin/login" replace />
  }

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
