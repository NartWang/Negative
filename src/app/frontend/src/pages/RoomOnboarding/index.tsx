import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useAuth } from '../../contexts/AuthContext'
import { useRoom } from '../../contexts/RoomContext'
import './style.css'

function friendlyRoomError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return '分享码不可用，请向对方获取新的分享码'
    if (error.status === 403) return '你没有执行这个操作的权限'
  }
  return '暂时无法完成，请稍后重试'
}

export default function RoomOnboarding() {
  const { user, logout } = useAuth()
  const { room, invite, createRoom, rotateInvite, joinRoom, leaveRoom, refresh } = useRoom()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => { headingRef.current?.focus() }, [room?.state])

  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name)
    setError(null)
    try {
      await action()
    } catch (cause) {
      setError(friendlyRoomError(cause))
    } finally {
      setBusy(null)
    }
  }

  const copyCode = async () => {
    if (!invite) return
    try {
      await navigator.clipboard.writeText(invite.code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setError('复制失败，请长按分享码手动复制')
    }
  }

  if (room?.state === 'waiting') {
    return (
      <main className="pair-page waiting-page">
        <header className="pair-topline">
          <span>{user?.nickname}</span>
          <button type="button" onClick={() => run('logout', logout)}>退出登录</button>
        </header>
        <section className="waiting-card" aria-labelledby="waiting-title">
          <div className="pair-orbit" aria-hidden="true"><span>你</span><i /><span>TA</span></div>
          <h1 id="waiting-title" ref={headingRef} tabIndex={-1}>等你一起</h1>
          <p className="waiting-copy">把分享码发给对方。加入之后，你们才会看见彼此主动分享的内容。</p>

          {invite ? (
            <button className="invite-code" type="button" onClick={copyCode} aria-label="复制分享码">
              <span>{invite.code}</span>
              <small aria-live="polite">{copied ? '已复制' : '轻触复制 · 24 小时有效'}</small>
            </button>
          ) : (
            <button className="pair-primary" type="button" onClick={() => run('invite', rotateInvite)} disabled={busy !== null}>
              生成分享码
            </button>
          )}

          {error && <p className="pair-error" role="alert">{error}</p>}

          <div className="waiting-actions">
            <button type="button" onClick={() => run('refresh', refresh)} disabled={busy !== null}>刷新房间状态</button>
            <button type="button" onClick={() => run('invite', rotateInvite)} disabled={busy !== null}>换一个分享码</button>
          </div>
          <button
            className="pair-danger"
            type="button"
            onClick={() => {
              if (window.confirm('关闭房间后，这个分享码会立即失效。确定关闭吗？')) {
                run('leave', leaveRoom)
              }
            }}
            disabled={busy !== null}
          >
            关闭这个房间
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="pair-page">
      <header className="pair-topline">
        <span>你好，{user?.nickname}</span>
        <button type="button" onClick={() => run('logout', logout)}>退出登录</button>
      </header>
      <section className="pair-intro" aria-labelledby="pair-title">
        <h1 id="pair-title" ref={headingRef} tabIndex={-1}>建立可见关系</h1>
      </section>

      <section className="pair-choice" aria-label="建立双人房间">
        <article className="pair-option create-option">
          <span className="option-number">01</span>
          <h2>我来创建</h2>
          <button
            className="pair-primary"
            type="button"
            onClick={() => run('create', createRoom)}
            disabled={busy !== null}
          >
            {busy === 'create' ? '正在创建…' : '创建我们的房间'}
          </button>
        </article>

        <div className="choice-divider"><span>或</span></div>

        <article className="pair-option join-option">
          <span className="option-number">02</span>
          <h2>我有分享码</h2>
          <form onSubmit={(event: FormEvent) => {
            event.preventDefault()
            if (code.trim()) run('join', () => joinRoom(code))
          }}>
            <label htmlFor="invite-code">分享码</label>
            <input
              id="invite-code"
              value={code}
              onChange={event => setCode(event.target.value.toUpperCase())}
              placeholder="ABCD-EFGH-JKMP-QRST"
              autoCapitalize="characters"
              autoComplete="off"
              maxLength={19}
            />
            <button
              className="pair-secondary"
              type="submit"
              disabled={busy !== null || !code.trim()}
            >
              {busy === 'join' ? '正在加入…' : '加入房间'}
            </button>
          </form>
        </article>
      </section>
      {error && <p className="pair-error onboarding-error" role="alert">{error}</p>}
    </main>
  )
}
