import { useEffect, useState } from 'react'
import { storyApi } from '../../api/client'
import type { StoryWork, WorkAudience } from '../../types'
import BottomSheet from '../BottomSheet'
import './style.css'

interface Props {
  open: boolean
  work: StoryWork | null
  onClose: () => void
  onSaved?: (items: WorkAudience[]) => void
}

export default function VisibilitySheet({ open, work, onClose, onSaved }: Props) {
  const [items, setItems] = useState<WorkAudience[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !work) return
    let cancelled = false
    setLoading(true)
    setError(null)
    storyApi.getAudience(work.id)
      .then(result => {
        if (cancelled) return
        setItems(result.items)
        setSelectedIds(result.items.filter(item => item.selected).map(item => item.subscription_id))
      })
      .catch(() => {
        if (!cancelled) setError('暂时无法读取可见范围')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, work])

  const toggle = (id: number) => {
    setSelectedIds(current => current.includes(id)
      ? current.filter(item => item !== id)
      : [...current, id])
  }

  const save = async () => {
    if (!work || saving) return
    setSaving(true)
    setError(null)
    try {
      const result = await storyApi.replaceAudience(work.id, selectedIds)
      setItems(result.items)
      setSelectedIds(result.items.filter(item => item.selected).map(item => item.subscription_id))
      onSaved?.(result.items)
      onClose()
    } catch {
      setError('保存可见范围失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <BottomSheet open={open} onClose={saving ? () => undefined : onClose} title="可见范围">
      <div className="visibility-sheet">
        <p>选择谁可以在回响里看到「{work?.title ?? '作品'}」。不选择任何人时，作品仅自己可见。</p>
        {loading && <div className="visibility-state" role="status">正在读取…</div>}
        {!loading && items.length === 0 && (
          <div className="visibility-state">还没有可分享的人，可以先在「我的」里建立关系。</div>
        )}
        {!loading && items.map(item => (
          <label className="visibility-row" key={item.subscription_id}>
            <input
              type="checkbox"
              checked={selectedIds.includes(item.subscription_id)}
              onChange={() => toggle(item.subscription_id)}
            />
            <span>{item.subscriber.nickname}</span>
          </label>
        ))}
        {error && <div className="visibility-error" role="alert">{error}</div>}
        <button
          type="button"
          className="visibility-save"
          disabled={loading || saving}
          onClick={save}
        >
          {saving ? '保存中' : '保存可见范围'}
        </button>
      </div>
    </BottomSheet>
  )
}
