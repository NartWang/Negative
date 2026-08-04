import { useState } from 'react'
import Today from './pages/Today'
import Diary from './pages/Diary'
import Mine from './pages/Mine'
import DiaryEditor from './pages/DiaryEditor'
import DualTimeline from './pages/DualTimeline'
import Auth from './pages/Auth'
import RoomOnboarding from './pages/RoomOnboarding'
import We from './pages/We'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { RoomProvider, useRoom } from './contexts/RoomContext'
import { DateProvider } from './contexts/DateContext'
import { ToastProvider } from './contexts/ToastContext'
import Toast from './components/Toast'
import { useReminder } from './hooks/useReminder'
import './App.css'

type Tab = 'we' | 'record' | 'memories' | 'mine'

function LoadingScreen({ label }: { label: string }) {
  return (
    <main className="app-loading" role="status">
      <span className="loading-mark" aria-hidden="true">知己</span>
      <p>{label}</p>
    </main>
  )
}

function RoomUnavailable() {
  const { refresh } = useRoom()
  const [busy, setBusy] = useState(false)
  const retry = async () => {
    setBusy(true)
    try { await refresh() }
    catch { /* RoomContext keeps the visible error state. */ }
    finally { setBusy(false) }
  }
  return (
    <main className="app-loading">
      <span className="loading-mark" aria-hidden="true">知己</span>
      <p role="alert">暂时无法读取房间状态</p>
      <button className="loading-retry" type="button" onClick={retry} disabled={busy}>
        {busy ? '正在重试…' : '重试'}
      </button>
    </main>
  )
}

function AccountActions() {
  const { user, logout } = useAuth()
  const { room, leaveRoom } = useRoom()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runLogout = async () => {
    setBusy(true)
    setError(null)
    try { await logout() }
    catch { setError('退出失败，请稍后重试') }
    finally { setBusy(false) }
  }

  const closeRoom = async () => {
    if (!window.confirm('离开会关闭双人房间，并立即停止双方的共享访问。确定继续吗？')) return
    setBusy(true)
    setError(null)
    try { await leaveRoom() }
    catch { setError('关闭房间失败，请稍后重试') }
    finally { setBusy(false) }
  }

  return (
    <section className="account-actions" aria-label="账号与房间">
      <div>
        <span className="account-actions-label">当前账号</span>
        <strong>{user?.nickname}</strong>
      </div>
      <div>
        <span className="account-actions-label">双人房间</span>
        <strong>与 {room?.partner?.nickname}</strong>
      </div>
      <p>你只会看到对方明确发布到房间的内容。</p>
      {error && <p className="account-action-error" role="alert">{error}</p>}
      <button className="account-logout" type="button" onClick={runLogout} disabled={busy}>退出登录</button>
      <button className="account-leave" type="button" onClick={closeRoom} disabled={busy}>关闭并离开房间</button>
    </section>
  )
}

function Shell() {
  const [activeTab, setActiveTab] = useState<Tab>('we')
  const [editorDate, setEditorDate] = useState<string | null>(null)
  const [showDualTimeline, setShowDualTimeline] = useState(false)
  const userId = useAuth().user?.id
  useReminder(userId)

  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: 'we', label: '我们', icon: '⌂' },
    { key: 'record', label: '记录', icon: '＋' },
    { key: 'memories', label: '回忆', icon: '▣' },
    { key: 'mine', label: '我的', icon: '○' },
  ]

  if (editorDate) {
    return <DiaryEditor userId={userId} date={editorDate} onBack={() => setEditorDate(null)} />
  }
  if (showDualTimeline) {
    return <DualTimeline userId={userId} onBack={() => setShowDualTimeline(false)} />
  }

  return (
    <div className="app">
      <div className="app-content">
        {activeTab === 'we' && <div key="we" className="tab-fade"><We onOpenDiary={setEditorDate} /></div>}
        {activeTab === 'record' && (
          <div key="record" className="tab-fade">
            <Today onOpenEditor={setEditorDate} />
          </div>
        )}
        {activeTab === 'memories' && (
          <div key="memories" className="tab-fade">
            <Diary
              userId={userId}
              onOpenEditor={date => setEditorDate(date)}
              onOpenDualTimeline={() => setShowDualTimeline(true)}
            />
          </div>
        )}
        {activeTab === 'mine' && (
          <div key="mine" className="tab-fade">
            <Mine userId={userId} />
            <AccountActions />
          </div>
        )}
      </div>
      <nav className="tab-bar" aria-label="主导航">
        {tabs.map(tab => (
          <button
            key={tab.key}
            type="button"
            className={`tab-item ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
            aria-current={activeTab === tab.key ? 'page' : undefined}
          >
            <span className="tab-icon" aria-hidden="true">{tab.icon}</span>
            <span className="tab-label">{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}

function RoomState() {
  const { room, status, error } = useRoom()
  if (status === 'loading') return <LoadingScreen label="正在打开你们的房间…" />
  if (status === 'retrying') return <LoadingScreen label="正在重试房间状态…" />
  if (error) return <RoomUnavailable />
  if (!room || room.state === 'waiting') return <RoomOnboarding />
  return (
    <DateProvider>
      <ToastProvider>
        <Toast />
        <Shell />
      </ToastProvider>
    </DateProvider>
  )
}

function ApplicationState() {
  const { user, status } = useAuth()
  if (status === 'loading') return <LoadingScreen label="正在确认账号…" />
  if (!user) return <Auth />
  return <RoomProvider><RoomState /></RoomProvider>
}

export default function App() {
  return <AuthProvider><ApplicationState /></AuthProvider>
}
