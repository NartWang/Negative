import { useEffect, useState } from 'react'
import { ApiError, profileApi, statsApi, exportApi } from '../../api/client'
import type { Profile, Stats, EmotionMode, DrawStyle } from '../../types'
import { useToast } from '../../contexts/ToastContext'
import { getUserPreference, setUserPreference } from '../../utils/userPreferences'
import ProfileHeader from '../../components/ProfileHeader'
import StatCard from '../../components/StatCard'
import NaggingSheet from '../../components/NaggingSheet'
import './style.css'

const EMOTION_LABELS: Record<EmotionMode, string> = {
  real: '真实传达', warm: '温暖滤镜', humor: '幽默轻松',
  poetic: '诗意文艺', custom: '自定义',
}
const STYLE_LABELS: Record<DrawStyle, string> = {
  ghibli: '治愈插画', watercolor: '水彩日记', grid4: '四宫格',
  comic: '叙事漫画', pixel: '像素复古', custom: '自定义',
}

const EMOTION_OPTIONS: { key: EmotionMode; label: string; desc: string }[] = [
  { key: 'real', label: '真实传达', desc: '如实呈现，柔和表达' },
  { key: 'warm', label: '温暖滤镜', desc: '重心在积极面，让对方安心' },
  { key: 'humor', label: '幽默轻松', desc: '把辛苦讲成段子' },
  { key: 'poetic', label: '诗意文艺', desc: '日常升华成散文' },
  { key: 'custom', label: '自定义', desc: '你来定义风格' },
]
const STYLE_OPTIONS: { key: DrawStyle; label: string; desc: string }[] = [
  { key: 'ghibli', label: '治愈插画', desc: '吉卜力感' },
  { key: 'watercolor', label: '水彩日记', desc: '手绘水彩风' },
  { key: 'grid4', label: '四宫格', desc: '手绘线条' },
  { key: 'comic', label: '叙事漫画', desc: '分镜故事' },
  { key: 'pixel', label: '像素复古', desc: '8-bit 怀旧' },
  { key: 'custom', label: '自定义', desc: '你来定义画面感' },
]

function daysBetween(iso: string): number {
  const start = new Date(iso)
  if (isNaN(start.getTime())) return 1
  const ms = Date.now() - start.getTime()
  return Math.max(1, Math.floor(ms / 86400000) + 1)
}

export default function Mine({ userId }: { userId?: number }) {
  const toast = useToast()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [emotionMode, setEmotionMode] = useState<EmotionMode>(
    (getUserPreference(userId, 'emotionMode') as EmotionMode) || 'warm'
  )
  const [drawStyle, setDrawStyle] = useState<DrawStyle>(
    (getUserPreference(userId, 'drawStyle') as DrawStyle) || 'ghibli'
  )
  const [reminderTime, setReminderTime] = useState(
    getUserPreference(userId, 'reminderTime') || '21:00'
  )
  const [showEmotion, setShowEmotion] = useState(false)
  const [showStyle, setShowStyle] = useState(false)
  const [customEmotion, setCustomEmotion] = useState(
    getUserPreference(userId, 'customEmotion') || ''
  )
  const [customDraw, setCustomDraw] = useState(
    getUserPreference(userId, 'customDraw') || ''
  )

  const [showNagging, setShowNagging] = useState(false)

  useEffect(() => {
    profileApi.get().then(setProfile).catch(() => toast.error('加载资料失败'))
    statsApi.get().then(setStats).catch(() => {})
  }, [toast])

  const persistEmotion = (m: EmotionMode) => {
    setEmotionMode(m); setUserPreference(userId, 'emotionMode', m); setShowEmotion(false)
  }
  const persistStyle = (s: DrawStyle) => {
    setDrawStyle(s); setUserPreference(userId, 'drawStyle', s); setShowStyle(false)
  }
  const persistReminder = (t: string) => {
    setReminderTime(t); setUserPreference(userId, 'reminderTime', t)
  }

  const exportPdf = async () => {
    toast.info('正在准备 PDF...')
    try {
      const blob = await exportApi.downloadPdf()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'zhiji-diaries.pdf'; a.click()
      URL.revokeObjectURL(url)
      toast.success('PDF 已下载')
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) toast.error('导出失败')
    }
  }

  const shareCard = () => toast.info('截图分享暂未上线，先用系统截图分享吧 ✨')
  const annualReport = () => toast.info('年度报告正在烹饪中，敬请期待 🍳')

  if (!profile) {
    return <div className="page mine-page"><p style={{ padding: 20 }} className="muted">加载中…</p></div>
  }

  const joinedDays = daysBetween(profile.created_at)

  return (
    <div className="page mine-page">
      <ProfileHeader profile={profile} joinedDays={joinedDays} onUpdate={setProfile} />

      {stats && (
        <section className="mine-section">
          <div className="stat-grid">
            <StatCard label="日记" value={stats.diary_count} icon="📖"/>
            <StatCard label="碎片" value={stats.fragment_count} icon="📝"/>
            <StatCard label="最长连续" value={`${stats.longest_streak} 天`} icon="🔥"/>
            <StatCard label="本月打卡" value={`${stats.month_checkins} / ${stats.month_days}`} icon="📅"/>
          </div>
        </section>
      )}

      <section className="mine-section">
        <h2 className="mine-section-title">分享与导出</h2>
        <div className="cell-list">
          <button className="cell pressable" onClick={exportPdf}>
            <span className="cell-icon">📄</span>
            <span className="cell-label">导出全部日记为 PDF</span>
            <span className="cell-chev">›</span>
          </button>
          <button className="cell pressable" onClick={() => setShowNagging(true)}>
            <span className="cell-icon">💌</span>
            <span className="cell-label">化解对方的牵挂</span>
            <span className="cell-value">5 条待化解</span>
            <span className="cell-chev">›</span>
          </button>
          <button className="cell pressable" onClick={shareCard}>
            <span className="cell-icon">🎴</span>
            <span className="cell-label">分享我的知己卡片</span>
            <span className="cell-chev">›</span>
          </button>
          <button className="cell pressable" onClick={annualReport}>
            <span className="cell-icon">📊</span>
            <span className="cell-label">生成年度报告</span>
            <span className="cell-hint">敬请期待</span>
            <span className="cell-chev">›</span>
          </button>
        </div>
      </section>

      <section className="mine-section">
        <h2 className="mine-section-title">偏好设置</h2>
        <div className="cell-list">
          <button className="cell pressable" onClick={() => setShowEmotion(true)}>
            <span className="cell-icon">🎨</span>
            <span className="cell-label">默认情感模式</span>
            <span className="cell-value">{EMOTION_LABELS[emotionMode]}</span>
            <span className="cell-chev">›</span>
          </button>
          <button className="cell pressable" onClick={() => setShowStyle(true)}>
            <span className="cell-icon">🖼</span>
            <span className="cell-label">默认绘图风格</span>
            <span className="cell-value">{STYLE_LABELS[drawStyle]}</span>
            <span className="cell-chev">›</span>
          </button>
          <label className="cell">
            <span className="cell-icon">⏰</span>
            <span className="cell-label">日记提醒时间</span>
            <input
              className="cell-time"
              type="time"
              value={reminderTime}
              onChange={e => persistReminder(e.target.value)}
            />
          </label>
        </div>
      </section>

      {showEmotion && (
        <div className="mine-sheet-backdrop" onClick={() => setShowEmotion(false)}>
          <div className="mine-sheet" onClick={e => e.stopPropagation()}>
            <div className="bs-handle" />
            <div className="sheet-title">情感模式</div>
            <div className="option-list">
              {EMOTION_OPTIONS.map(o => (
                <button
                  key={o.key}
                  className={`option-row ${emotionMode === o.key ? 'active' : ''}`}
                  onClick={() => persistEmotion(o.key)}
                >
                  <div className="option-label">{o.label}</div>
                  <div className="option-desc">{o.desc}</div>
                </button>
              ))}
            </div>
            {emotionMode === 'custom' && (
              <input
                className="custom-prompt"
                placeholder="描述你想要的情感风格..."
                value={customEmotion}
                onChange={e => {
                  setCustomEmotion(e.target.value)
                  setUserPreference(userId, 'customEmotion', e.target.value)
                }}
              />
            )}
          </div>
        </div>
      )}

      {showStyle && (
        <div className="mine-sheet-backdrop" onClick={() => setShowStyle(false)}>
          <div className="mine-sheet" onClick={e => e.stopPropagation()}>
            <div className="bs-handle" />
            <div className="sheet-title">绘图风格</div>
            <div className="option-list">
              {STYLE_OPTIONS.map(o => (
                <button
                  key={o.key}
                  className={`option-row ${drawStyle === o.key ? 'active' : ''}`}
                  onClick={() => persistStyle(o.key)}
                >
                  <div className="option-label">{o.label}</div>
                  <div className="option-desc">{o.desc}</div>
                </button>
              ))}
            </div>
            {drawStyle === 'custom' && (
              <input
                className="custom-prompt"
                placeholder="描述你想要的画面感..."
                value={customDraw}
                onChange={e => {
                  setCustomDraw(e.target.value)
                  setUserPreference(userId, 'customDraw', e.target.value)
                }}
              />
            )}
          </div>
        </div>
      )}

      <NaggingSheet open={showNagging} onClose={() => setShowNagging(false)} />
    </div>
  )
}
