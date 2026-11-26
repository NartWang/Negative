import { useEffect, useRef, useState } from 'react'
import { storyApi } from '../../api/client'
import type { PublicationWorkState, StoryWork, WorkAudience } from '../../types'
import BottomSheet from '../BottomSheet'
import './style.css'

interface Props {
  open: boolean
  work: StoryWork | null
  onClose: () => void
  onPublished: (state: PublicationWorkState) => void
}

export default function PublishSheet({ open, work, onClose, onPublished }: Props) {
  const [items, setItems] = useState<WorkAudience[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open || !work) return
    let cancelled = false
    setLoading(true)
    setError(null)
    storyApi.getAudience(work.id)
      .then(result => {
        if (cancelled) return
        setItems(result.items)
        // a ready work starts with nobody selected
        setSelectedIds([])
      })
      .catch(() => {
        if (!cancelled) setError('暂时无法读取可分享的人')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, work])

  const toggle = (id: number) => {
    setSelectedIds(current =>
      current.includes(id)
        ? current.filter(item => item !== id)
        : [...current, id])
  }

  const publish = async () => {
    if (!work || saving) return
    setSaving(true)
    setError(null)
    try {
      const result = await storyApi.publish(work.id, selectedIds)
      onPublished(result.work)
      onClose()
    } catch {
      setError('发布失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  const label = selectedIds.length === 0
    ? '发布 · 仅自己可见'
    : `发布 · ${selectedIds.length} 人可见`

  return (
    <BottomSheet open={open} onClose={saving ? () => undefined : onClose} title="发布到回响">
      <div className="publish-sheet">
        <p className="publish-hint">
          发布后，「{work?.title ?? '作品'}」会进入你的动态。选择谁也能看到它；不选择任何人时，只有你自己能看到。
        </p>
        <div className="publish-self" aria-label="作者本人固定可见">
          <span className="publish-self-name">我自己</span>
          <span className="publish-self-tag">始终可见</span>
        </div>
        {loading && <div className="publish-state" role="status">正在读取…</div>}
        {!loading && items.length === 0 && (
          <div className="publish-state">还没有关注了我的人，发布后只有你自己能看到。</div>
        )}
        {!loading && items.map(item => (
          <label className="publish-row" key={item.subscription_id}>
            <input
              type="checkbox"
              checked={selectedIds.includes(item.subscription_id)}
              onChange={() => toggle(item.subscription_id)}
            />
            <span>{item.subscriber.nickname}</span>
          </label>
        ))}
        {error && <div className="publish-error" role="alert">{error}</div>}
        <button
          type="button"
          className="publish-submit"
          ref={triggerRef}
          disabled={loading || saving}
          onClick={publish}
        >
          {saving ? '发布中' : label}
        </button>
      </div>
    </BottomSheet>
  )
}
