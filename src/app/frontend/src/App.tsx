import { useState } from 'react'
import Today from './pages/Today'
import Record from './pages/Record'
import Diary from './pages/Diary'
import Mine from './pages/Mine'
import DiaryEditor from './pages/DiaryEditor'
import DualTimeline from './pages/DualTimeline'
import { DateProvider } from './contexts/DateContext'
import { ToastProvider } from './contexts/ToastContext'
import { UserProvider } from './contexts/UserContext'
import Toast from './components/Toast'
import Splash from './components/Splash'
import { useReminder } from './hooks/useReminder'
import { useReactionPoll } from './hooks/useReactionPoll'
import './App.css'

type Tab = 'today' | 'record' | 'diary' | 'mine'

function Shell() {
  const [activeTab, setActiveTab] = useState<Tab>('today')
  const [editorDate, setEditorDate] = useState<string | null>(null)
  const [showDualTimeline, setShowDualTimeline] = useState(false)
  useReminder()
  const { unseenCount } = useReactionPoll()

  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: 'today',  label: '今天',   icon: '☀️' },
    { key: 'record', label: '记录',   icon: '📝' },
    { key: 'diary',  label: '日记本', icon: '📖' },
    { key: 'mine',   label: '我的',   icon: '⚙️' },
  ]

  if (editorDate) {
    return <DiaryEditor date={editorDate} onBack={() => setEditorDate(null)} />
  }
  if (showDualTimeline) {
    return <DualTimeline onBack={() => setShowDualTimeline(false)} />
  }

  return (
    <div className="app">
      <div className="app-content">
        {activeTab === 'today'  && <div key="today" className="tab-fade"><Today  onOpenEditor={(d) => setEditorDate(d)} /></div>}
        {activeTab === 'record' && <div key="record" className="tab-fade"><Record /></div>}
        {activeTab === 'diary'  && (
          <div key="diary" className="tab-fade">
            <Diary
              onOpenEditor={(d) => setEditorDate(d)}
              onOpenDualTimeline={() => setShowDualTimeline(true)}
            />
          </div>
        )}
        {activeTab === 'mine'   && <div key="mine" className="tab-fade"><Mine /></div>}
      </div>
      <nav className="tab-bar">
        {tabs.map(tab => (
          <button
            key={tab.key}
            className={`tab-item ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            <span className="tab-icon">{tab.icon}</span>
            <span className="tab-label">{tab.label}</span>
            {tab.key === 'mine' && unseenCount > 0 && (
              <span className="tab-badge">{unseenCount}</span>
            )}
          </button>
        ))}
      </nav>
    </div>
  )
}

const SPLASH_KEY = 'zhiji.splash_shown'

export default function App() {
  const [splashDone, setSplashDone] = useState(
    typeof window !== 'undefined' && sessionStorage.getItem(SPLASH_KEY) === '1'
  )

  if (!splashDone) {
    return (
      <Splash onDone={() => {
        sessionStorage.setItem(SPLASH_KEY, '1')
        setSplashDone(true)
      }} />
    )
  }

  return (
    <UserProvider>
      <DateProvider>
        <ToastProvider>
          <Toast />
          <Shell />
        </ToastProvider>
      </DateProvider>
    </UserProvider>
  )
}
