import { useEffect, useState } from 'react'
import { storyApi } from '../../api/client'
import type { InteractionSummaryItem } from '../../types'
import BottomSheet from '../../components/BottomSheet'

interface Props {
  open: boolean
  onClose: () => void
  onLocateWork: (workId: number) => void
}

export default function InteractionSummary({ open, onClose, onLocateWork }: Props) {
  const [items, setItems] = useState<InteractionSummaryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    storyApi.interactions()
      .then(result => {
        if (!cancelled) setItems(result.items)
      })
      .catch(() => {
        if (!cancelled) setError('互动汇总暂时加载不出来')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open])

  return (
    <BottomSheet open={open} onClose={onClose} title="互动汇总">
      <div className="interaction-summary" role="dialog" aria-label="互动汇总">
        {loading && <div className="resonance-state" role="status">正在读取…</div>}
        {error && (
          <div className="resonance-state" role="alert">
            <p>{error}</p>
          </div>
        )}
        {!loading && !error && items.length === 0 && (
          <p className="interaction-summary-empty">还没有收到点赞或评论</p>
        )}
        {!loading && !error && items.length > 0 && (
          <ul>
            {items.map((item, index) => (
              <li key={`${item.kind}-${item.work_id}-${index}`}>
                <button type="button" onClick={() => onLocateWork(item.work_id)}>
                  <span className="interaction-summary-actor">{item.actor.nickname}</span>
                  {item.kind === 'like' ? ' 点赞了' : ` 评论:${item.body}`}
                  <span className="interaction-summary-work">「{item.work_title}」</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </BottomSheet>
  )
}
