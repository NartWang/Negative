import { useEffect, useState } from 'react'
import { profileApi, statsApi, exportApi, emailApi, shareApi } from '../../api/client'
import type { Profile, Stats, EmotionMode, DrawStyle, EmailConfig } from '../../types'
import { useToast } from '../../contexts/ToastContext'
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

export default function Mine() {
  const toast = useToast()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [emotionMode, setEmotionMode] = useState<EmotionMode>(
    (localStorage.getItem('emotionMode') as EmotionMode) || 'warm'
  )
  const [drawStyle, setDrawStyle] = useState<DrawStyle>(
    (localStorage.getItem('drawStyle') as DrawStyle) || 'ghibli'
  )
  const [reminderTime, setReminderTime] = useState(localStorage.getItem('reminderTime') || '21:00')
  const [showEmotion, setShowEmotion] = useState(false)
  const [showStyle, setShowStyle] = useState(false)
  const [customEmotion, setCustomEmotion] = useState(localStorage.getItem('customEmotion') || '')
  const [customDraw, setCustomDraw] = useState(localStorage.getItem('customDraw') || '')

  const EMAIL_TO_KEY = 'zhiji.email.to'

  // v3.7: 邮件配置 + 回应通知
  const [showEmail, setShowEmail] = useState(false)
  const [showNagging, setShowNagging] = useState(false)
  const [emailConfig, setEmailConfig] = useState<EmailConfig | null>(null)
  const [emailTo, setEmailTo] = useState(localStorage.getItem(EMAIL_TO_KEY) || '')
  const [unseenReactions, setUnseenReactions] = useState(0)

  useEffect(() => {
    profileApi.get().then(setProfile).catch(() => toast.error('加载资料失败'))
    statsApi.get().then(setStats).catch(() => {})
    emailApi.config().then(setEmailConfig).catch(() => {})
    loadUnseenReactions()
  }, [toast])

  const loadUnseenReactions = () => {
    shareApi.unseenReactions().then(r => setUnseenReactions(r.unseen_count)).catch(() => {})
  }

  const persistEmotion = (m: EmotionMode) => {
    setEmotionMode(m); localStorage.setItem('emotionMode', m); setShowEmotion(false)
  }
  const persistStyle = (s: DrawStyle) => {
    setDrawStyle(s); localStorage.setItem('drawStyle', s); setShowStyle(false)
  }
  const persistReminder = (t: string) => {
    setReminderTime(t); localStorage.setItem('reminderTime', t)
  }

  const saveEmailTo = () => {
    const v = emailTo.trim()
    localStorage.setItem(EMAIL_TO_KEY, v)
    setShowEmail(false)
    toast.success('邮件设置已保存')
  }

  const handleMarkSeen = async () => {
    await shareApi.markSeen()
    setUnseenReactions(0)
  }

  const exportPdf = async () => {
    toast.info('正在准备 PDF...')
    try {
      const res = await fetch(exportApi.pdfUrl(), { method: 'POST' })
      if (!res.ok) {
        let detail = '导出失败'
        try { detail = (await res.json()).detail ?? detail } catch {}
        toast.error(detail)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'zhiji-diaries.pdf'; a.click()
      URL.revokeObjectURL(url)
      toast.success('PDF 已下载')
    } catch {
      toast.error('导出失败')
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
          <button className="cell pressable" onClick={() => setShowEmail(true)}>
            <span className="cell-icon">📧</span>
            <span className="cell-label">家书设置</span>
            <span className="cell-value">{emailConfig?.configured ? '邮件已配置 ✓' : '未配置'}</span>
            <span className="cell-chev">›</span>
          </button>
          {unseenReactions > 0 && (
            <button className="cell pressable" onClick={handleMarkSeen}>
              <span className="cell-icon">💌</span>
              <span className="cell-label">家人回应了你</span>
              <span className="cell-value" style={{ background: '#FF6B6B', color: '#fff', borderRadius: 10, padding: '2px 8px', fontSize: 12 }}>{unseenReactions} 条新回应</span>
              <span className="cell-chev">›</span>
            </button>
          )}
          <button className="cell pressable" onClick={() => setShowNagging(true)}>
            <span className="cell-icon">💌</span>
            <span className="cell-label">化解妈妈的牵挂</span>
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
                onChange={e => { setCustomEmotion(e.target.value); localStorage.setItem('customEmotion', e.target.value) }}
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
                onChange={e => { setCustomDraw(e.target.value); localStorage.setItem('customDraw', e.target.value) }}
              />
            )}
          </div>
        </div>
      )}

      {showEmail && (
        <div className="mine-sheet-backdrop" onClick={() => setShowEmail(false)}>
          <div className="mine-sheet" onClick={e => e.stopPropagation()}>
            <div className="bs-handle" />
            <div className="sheet-title">📧 家书设置</div>
            {emailConfig && !emailConfig.configured ? (
              <>
                <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, margin: '0 0 12px' }}>
                  邮件服务未配置。<br/>
                  请在服务器 <code>.env</code> 中设置 SMTP 相关变量：<br/>
                  <code>SMTP_HOST</code> / <code>SMTP_PORT</code> / <code>SMTP_USER</code> / <code>SMTP_PASSWORD</code>
                </p>
                <div className="sl-tip" style={{ background: 'rgba(255,200,100,0.15)', padding: '8px 12px', borderRadius: 8, marginBottom: 12 }}>
                  以 QQ 邮箱为例：登录 QQ 邮箱 → 设置 → 账户 → 开启 SMTP 服务 → 获取授权码
                </div>
              </>
            ) : (
              <>
                <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, margin: '0 0 12px' }}>
                  邮件服务已配置 {emailConfig?.from_addr ? `(${emailConfig.from_addr})` : ''}<br/>
                  输入家人的邮箱地址，之后寄家书时可直接发送邮件。
                </p>
                <input
                  className="sl-email-input"
                  type="email"
                  placeholder="家人的邮箱地址"
                  value={emailTo}
                  onChange={e => setEmailTo(e.target.value)}
                  style={{ marginBottom: 12 }}
                />
              </>
            )}
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                className="cell pressable"
                style={{ flex: 1, justifyContent: 'center', padding: '10px 14px', borderRadius: 12 }}
                onClick={() => setShowEmail(false)}
              >取消</button>
              <button
                className="cell pressable"
                style={{ flex: 1, justifyContent: 'center', padding: '10px 14px', borderRadius: 12, background: '#B8D4C2', color: '#2D4738' }}
                onClick={saveEmailTo}
              >保存</button>
            </div>
          </div>
        </div>
      )}

      <NaggingSheet open={showNagging} onClose={() => setShowNagging(false)} />
    </div>
  )
}
