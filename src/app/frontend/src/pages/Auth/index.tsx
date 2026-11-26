import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useAuth } from '../../contexts/AuthContext'
import './style.css'

type Mode = 'login' | 'register'

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return '用户名或密码不正确'
    if (error.status === 409) return '这个用户名暂时不可用'
    if (error.status === 422) return '请检查填写的信息'
  }
  return '暂时无法完成，请稍后重试'
}

export default function Auth() {
  const { login, register, bootstrapError } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [nickname, setNickname] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(bootstrapError)
  const titleRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => { titleRef.current?.focus() }, [mode])

  const changeMode = (nextMode: Mode) => {
    setMode(nextMode)
    setError(null)
    setPassword('')
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'login') await login(username.trim(), password)
      else await register(username.trim(), password, nickname.trim())
    } catch (cause) {
      setError(friendlyError(cause))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-mark" aria-hidden="true">
        <span>知</span><span>己</span>
      </div>
      <section className="auth-card" aria-labelledby="auth-title">
        <p className="auth-eyebrow">PRIVATE, JUST FOR TWO</p>
        <h1 id="auth-title" ref={titleRef} tabIndex={-1}>{mode === 'login' ? '欢迎回来' : '从今天开始记录'}</h1>
        <p className="auth-intro">
          {mode === 'login'
            ? '回到只属于你和重要之人的小房间。'
            : '你的记录默认只属于你，分享由你决定。'}
        </p>

        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="auth-username">用户名</label>
          <input
            id="auth-username"
            value={username}
            onChange={event => setUsername(event.target.value)}
            autoComplete="username"
            maxLength={128}
            required
          />

          {mode === 'register' && (
            <>
              <label htmlFor="auth-nickname">昵称</label>
              <input
                id="auth-nickname"
                value={nickname}
                onChange={event => setNickname(event.target.value)}
                autoComplete="nickname"
                maxLength={100}
                required
              />
            </>
          )}

          <label htmlFor="auth-password">密码</label>
          <input
            id="auth-password"
            type="password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            minLength={mode === 'register' ? 8 : 1}
            maxLength={1024}
            aria-describedby={mode === 'register' ? 'password-help' : undefined}
            required
          />
          {mode === 'register' && <p className="auth-help" id="password-help">至少 8 个字符</p>}

          {error && <p className="form-error" role="alert">{error}</p>}

          <button className="auth-submit" type="submit" disabled={submitting}>
            {submitting ? '请稍候…' : mode === 'login' ? '登录' : '创建账号'}
          </button>
        </form>

        {mode === 'login' ? (
          <button className="auth-mode" type="button" aria-label="注册新账号" onClick={() => changeMode('register')}>
            还没有账号？<strong>注册新账号</strong>
          </button>
        ) : (
          <button className="auth-mode" type="button" aria-label="返回登录" onClick={() => changeMode('login')}>
            已有账号？<strong>返回登录</strong>
          </button>
        )}
      </section>
      <p className="auth-privacy">日程、碎片和草稿不会自动分享</p>
    </main>
  )
}
