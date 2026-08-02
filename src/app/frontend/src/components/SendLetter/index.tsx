import { useState, useEffect } from 'react'
import { shareApi, emailApi } from '../../api/client'
import type { EmailConfig } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import { useUser } from '../../contexts/UserContext'
import BottomSheet from '../BottomSheet'
import './style.css'

interface Props {
  type: 'diary' | 'comic' | 'dual_timeline'
  id: number
  title: string
  body: string
  onSent?: (sentAt: string) => void
  className?: string
}

export const EMAIL_KEY = 'zhiji.email.to'
export const SHARE_BASE_URL = '/api'

export default function SendLetter({ type, id, title, body, onSent, className }: Props) {
  const toast = useToast()
  const { currentUserId } = useUser()
  const [open, setOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [shareUrl, setShareUrl] = useState<string | null>(null)
  const [emailTo, setEmailTo] = useState(localStorage.getItem(EMAIL_KEY) || '')
  const [emailConfig, setEmailConfig] = useState<EmailConfig | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    emailApi.config().then(setEmailConfig).catch(() => {})
  }, [])

  const handleOpen = () => {
    setShareUrl(null)
    setCopied(false)
    setOpen(true)
  }

  const createShare = async () => {
    if (shareUrl) return
    setSending(true)
    try {
      const res = await shareApi.create({ type, id, user_id: currentUserId })
      const fullUrl = `${window.location.origin}${SHARE_BASE_URL}/s/${res.share_code}`
      setShareUrl(fullUrl)
    } catch (e: any) {
      toast.error(e?.message ?? '生成分享链接失败')
    } finally {
      setSending(false)
    }
  }

  const copyLink = async () => {
    if (!shareUrl) {
      await createShare()
    }
    if (shareUrl) {
      try {
        await navigator.clipboard.writeText(shareUrl)
        setCopied(true)
        toast.success('链接已复制，发给家人吧 ✨')
        setTimeout(() => setCopied(false), 3000)
      } catch {
        toast.error('复制失败，请手动复制')
      }
    }
  }

  const sendEmail = async () => {
    const to = emailTo.trim()
    if (!to) {
      toast.error('请先输入收件人邮箱')
      return
    }
    localStorage.setItem(EMAIL_KEY, to)

    setSending(true)
    try {
      // 先生成分享链接用于邮件
      let url = shareUrl
      if (!url) {
        const res = await shareApi.create({ type, id, user_id: currentUserId })
        url = `${window.location.origin}${SHARE_BASE_URL}/s/${res.share_code}`
        setShareUrl(url)
      }

      await emailApi.send({
        to,
        subject: title,
        body,
        share_url: url,
      })
      toast.success('邮件已发送 ✨')
      onSent?.(new Date().toISOString())
      setOpen(false)
    } catch (e: any) {
      toast.error(e?.message ?? '邮件发送失败')
    } finally {
      setSending(false)
    }
  }

  const previewLines = body.split('\n').slice(0, 3).join('\n')
  const truncated = body.split('\n').length > 3

  return (
    <>
      <button
        className={`send-letter-btn pressable ${className ?? ''}`}
        onClick={handleOpen}
        disabled={sending}
        type="button"
      >
        📨 寄给家人
      </button>

      <BottomSheet open={open} onClose={() => !sending && setOpen(false)} title="寄给家人">
        <div className="sl-preview-title">{title}</div>
        <pre className="sl-preview-body">{previewLines}{truncated ? '\n…' : ''}</pre>

        {/* 方式一：分享链接 */}
        <div className="sl-section">
          <div className="sl-section-label">方式一：复制链接发给家人</div>
          {shareUrl ? (
            <div className="sl-share-link">
              <input
                className="sl-share-input"
                value={shareUrl}
                readOnly
                onClick={e => (e.target as HTMLInputElement).select()}
              />
              <button
                className="sl-btn sl-btn-primary sl-btn-sm"
                onClick={copyLink}
                disabled={sending}
              >
                {copied ? '已复制 ✓' : '复制'}
              </button>
            </div>
          ) : (
            <button
              className="sl-btn sl-btn-primary"
              style={{ width: '100%' }}
              onClick={createShare}
              disabled={sending}
            >
              {sending ? '生成中…' : '🔗 生成分享链接'}
            </button>
          )}
          <div className="sl-tip" style={{ marginTop: 6 }}>家人打开链接后可以回应心情 ❤️</div>
        </div>

        {/* 方式二：邮件 */}
        <div className="sl-divider" />
        <div className="sl-section">
          <div className="sl-section-label">方式二：发送邮件</div>
          {emailConfig && !emailConfig.configured ? (
            <div className="sl-tip" style={{ background: 'rgba(255,200,100,0.15)', padding: '8px 12px', borderRadius: 8 }}>
              邮件服务暂未配置，请先在「我的 → 家书设置」中配置 SMTP
            </div>
          ) : (
            <>
              <input
                className="sl-email-input"
                type="email"
                placeholder="家人的邮箱地址"
                value={emailTo}
                onChange={e => setEmailTo(e.target.value)}
              />
              <button
                className="sl-btn sl-btn-primary"
                style={{ width: '100%', marginTop: 8 }}
                onClick={sendEmail}
                disabled={sending || !emailTo.trim()}
              >
                {sending ? '发送中…' : '📧 发送邮件'}
              </button>
            </>
          )}
        </div>
      </BottomSheet>
    </>
  )
}