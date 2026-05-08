import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { login } from '../../services/authApi.js'
import { hasAccessToken } from '../../services/authStorage.js'
import inqLogoUrl from '../../images/inq-logo.png'

function LoginPage() {
  const navigate = useNavigate()
  const [loginType, setLoginType] = useState('student')
  const [studentId, setStudentId] = useState('')
  const [studentPassword, setStudentPassword] = useState('')
  const [adminUsername, setAdminUsername] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [noticeMessage, setNoticeMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (hasAccessToken()) {
    return <Navigate to="/admin" replace />
  }

  const switchLoginType = (nextType) => {
    setLoginType(nextType)
    setErrorMessage('')
    setNoticeMessage('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setErrorMessage('')
    setNoticeMessage('')

    if (loginType === 'student') {
      setNoticeMessage('학생 로그인은 학교 포털 연동 이슈에서 연결합니다.')
      return
    }

    setIsSubmitting(true)
    try {
      await login({ username: adminUsername, password: adminPassword })
      navigate('/admin')
    } catch (error) {
      setErrorMessage(error.message)
    } finally {
      setIsSubmitting(false)
    }
  }

  const canSubmit = loginType === 'student'
    ? studentId.trim() && studentPassword
    : adminUsername.trim() && adminPassword

  return (
    <section className="portal-login">
      <header className="portal-brand">
        <Link className="portal-home-link" to="/" aria-label="챗봇 홈으로 이동">
          <img src={inqLogoUrl} alt="InQ" />
        </Link>
      </header>

      <main className="portal-card">
        <section className="portal-login-panel" aria-label="로그인">
          <div className="portal-tabs" role="tablist" aria-label="로그인 유형">
            <button
              type="button"
              role="tab"
              aria-selected={loginType === 'student'}
              className={loginType === 'student' ? 'portal-tab portal-tab--active' : 'portal-tab'}
              onClick={() => switchLoginType('student')}
            >
              아이디 로그인
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={loginType === 'admin'}
              className={loginType === 'admin' ? 'portal-tab portal-tab--active' : 'portal-tab'}
              onClick={() => switchLoginType('admin')}
            >
              관리자 로그인
            </button>
          </div>

          <form className="portal-form" onSubmit={handleSubmit}>
            <p>
              {loginType === 'student'
                ? '본인의 학번과 비밀번호를 입력하세요.'
                : '관리자 계정으로 문서 관리 화면에 접속합니다.'}
            </p>

            <div className="portal-fields">
              <input
                value={loginType === 'student' ? studentId : adminUsername}
                onChange={(event) => (
                  loginType === 'student'
                    ? setStudentId(event.target.value)
                    : setAdminUsername(event.target.value)
                )}
                placeholder={loginType === 'student' ? '학번' : '관리자 아이디'}
                autoComplete="username"
                disabled={isSubmitting}
              />
              <input
                type="password"
                value={loginType === 'student' ? studentPassword : adminPassword}
                onChange={(event) => (
                  loginType === 'student'
                    ? setStudentPassword(event.target.value)
                    : setAdminPassword(event.target.value)
                )}
                placeholder="비밀번호"
                autoComplete="current-password"
                disabled={isSubmitting}
              />
              <button type="submit" disabled={!canSubmit || isSubmitting}>
                {isSubmitting ? '확인 중' : '로그인'}
              </button>
            </div>

            <div className="portal-options">
              <label>
                <input type="checkbox" />
                아이디 저장
              </label>
              <span>아이디찾기 ㅣ 비밀번호재설정</span>
            </div>

            {noticeMessage && <p className="portal-message">{noticeMessage}</p>}
            {errorMessage && <p className="portal-message portal-message--error">{errorMessage}</p>}
          </form>
        </section>

        <aside className="portal-notice" aria-label="시스템 공지">
          <h2>시스템공지</h2>
          <ul>
            <li>학교 홈페이지 안내 챗봇은 비로그인으로 이용할 수 있습니다.</li>
            <li>관리자 로그인은 문서 업로드와 시스템 설정에만 사용합니다.</li>
          </ul>
        </aside>
      </main>

      <nav className="portal-shortcuts" aria-label="바로가기">
        <a href="https://www.inhatc.ac.kr" target="_blank" rel="noreferrer">대표홈페이지</a>
        <a href="https://cyber.inhatc.ac.kr" target="_blank" rel="noreferrer">이러닝</a>
        <a href="https://www.inhatc.ac.kr" target="_blank" rel="noreferrer">증명발급</a>
        <a href="https://www.inhatc.ac.kr" target="_blank" rel="noreferrer">일자리</a>
      </nav>
    </section>
  )
}

export default LoginPage
