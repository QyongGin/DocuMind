import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { login } from '../../services/authApi.js'
import { hasAccessToken } from '../../services/authStorage.js'

function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (hasAccessToken()) {
    return <Navigate to="/admin" replace />
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setErrorMessage('')
    setIsSubmitting(true)

    try {
      await login({ username, password })
      navigate('/admin')
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="page page--compact">
      <header className="page-header">
        <div>
          <p className="eyebrow">Admin</p>
          <h1>관리자 로그인</h1>
        </div>
      </header>

      <form className="form-card" onSubmit={handleSubmit}>
        <label>
          아이디
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            disabled={isSubmitting}
          />
        </label>

        <label>
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            disabled={isSubmitting}
          />
        </label>

        {errorMessage && <p className="error">{errorMessage}</p>}

        <button type="submit" disabled={!username || !password || isSubmitting}>
          {isSubmitting ? '확인 중' : '로그인'}
        </button>
      </form>
    </section>
  )
}

export default LoginPage
