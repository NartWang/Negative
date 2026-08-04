import { useEffect, useState } from 'react'
import { transformApi } from '../../api/client'
import type { NaggingItem, NaggingCards } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import './style.css'

interface Props {
  open: boolean
  onClose: () => void
}

const KIND_LABEL: Record<string, string> = {
  health_article: '养生文',
  checkin: '日常关心',
  matchmaking: '催相亲',
  anti_fraud: '防诈骗',
  sleep_nag: '催早睡',
}

const KIND_EMOJI: Record<string, string> = {
  health_article: '🥬',
  checkin: '🍚',
  matchmaking: '💑',
  anti_fraud: '⚠️',
  sleep_nag: '😴',
}

const CARD_META: { key: keyof NaggingCards; label: string; desc: string; emoji: string }[] = [
  { key: 'help_request', label: '担心 → 求助', desc: '让对方感到被需要', emoji: '🆘' },
  { key: 'co_challenge', label: '说教 → 协同', desc: '一起做一件事', emoji: '🤝' },
  { key: 'warm_echo', label: '直接共情', desc: '温暖回应 + 一个具体细节', emoji: '💗' },
]

export default function NaggingSheet({ open, onClose }: Props) {
  const toast = useToast()
  const [inbox, setInbox] = useState<NaggingItem[] | null>(null)
  const [selected, setSelected] = useState<NaggingItem | null>(null)
  const [cards, setCards] = useState<NaggingCards | null>(null)
  const [loadingCards, setLoadingCards] = useState(false)

  useEffect(() => {
    if (!open) return
    transformApi.inbox()
      .then(setInbox)
      .catch(() => toast.error('加载对方的话失败'))
  }, [open, toast])

  // Reset transient state on close
  useEffect(() => {
    if (!open) {
      setSelected(null)
      setCards(null)
    }
  }, [open])

  const pickNag = async (item: NaggingItem) => {
    setSelected(item)
    setCards(null)
    setLoadingCards(true)
    try {
      const res = await transformApi.transform({ nag_id: item.id, relation: item.from })
      setCards(res.cards)
    } catch (e: any) {
      toast.error(e?.message ?? 'AI 转化失败')
      setSelected(null)
    } finally {
      setLoadingCards(false)
    }
  }

  const back = () => {
    setSelected(null)
    setCards(null)
  }

  if (!open) return null

  return (
    <div className="nag-backdrop" onClick={onClose}>
      <div className="nag-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="bs-handle" />

        {!selected ? (
          <>
            <div className="nag-title">化解对方的牵挂</div>
            <p className="nag-sub">
              对方不是要说教，只是不会表达。挑一条，让 AI 帮你把"焦虑"翻译成"被需要"。
            </p>
            {!inbox ? (
              <div className="nag-loading">加载中…</div>
            ) : inbox.length === 0 ? (
              <div className="nag-empty">对方最近没有发什么 ✨</div>
            ) : (
              <div className="nag-list">
                {inbox.map((it) => (
                  <button
                    key={it.id}
                    className="nag-item pressable"
                    onClick={() => pickNag(it)}
                  >
                    <span className="nag-emoji">{KIND_EMOJI[it.kind] ?? '💬'}</span>
                    <div className="nag-item-body">
                      <div className="nag-item-meta">
                        <span className="nag-item-from">{it.from}</span>
                        <span className="nag-item-kind">{KIND_LABEL[it.kind] ?? it.kind}</span>
                      </div>
                      <div className="nag-item-text">{it.text}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <button className="nag-back" onClick={back}>← 换一条</button>
            <div className="nag-quote">
              <span className="nag-emoji">{KIND_EMOJI[selected.kind] ?? '💬'}</span>
              <span>{selected.text}</span>
            </div>

            {loadingCards && <div className="nag-loading">✨ AI 正在化解中…</div>}

            {cards && (
              <div className="nag-cards">
                {CARD_META.map((meta) => (
                  <div key={meta.key} className="nag-card">
                    <div className="nag-card-head">
                      <span className="nag-card-emoji">{meta.emoji}</span>
                      <div>
                        <div className="nag-card-label">{meta.label}</div>
                        <div className="nag-card-desc">{meta.desc}</div>
                      </div>
                    </div>
                    <div className="nag-card-text">{cards[meta.key]}</div>
                    <div className="nag-card-actions">
                      <button
                        className="nag-card-btn nag-card-btn-secondary"
                        onClick={() => {
                          navigator.clipboard?.writeText(cards[meta.key])
                          toast.success('已复制')
                        }}
                      >📋 复制</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
