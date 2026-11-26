import { useState } from 'react'
import { storyApi } from '../../api/client'
import type { ResonanceFeedItem } from '../../types'
import BottomSheet from '../../components/BottomSheet'

interface Props {
  open: boolean
  work: ResonanceFeedItem
  onClose: () => void
  onVisibility: () => void
  onUnpublished: () => void
}

export default function PostMenu({ open, work, onClose, onVisibility, onUnpublished }: Props) {
  const [confirming, setConfirming] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const unpublish = async () => {
    if (removing) return
    setRemoving(true)
    setError(null)
    try {
      await storyApi.unpublish(work.id)
      onUnpublished()
    } catch {
      setError('取消发布失败，请重试')
    } finally {
      setRemoving(false)
    }
  }

  const close = () => {
    setConfirming(false)
    setError(null)
    onClose()
  }

  return (
    <BottomSheet open={open} onClose={removing ? () => undefined : close} title="更多操作">
      <div className="post-menu" role="dialog" aria-label="更多操作">
        {!confirming && (
          <>
            <button type="button" className="post-menu-item" onClick={onVisibility}>
              可见范围
            </button>
            <button
              type="button"
              className="post-menu-item danger"
              onClick={() => setConfirming(true)}
            >
              取消发布
            </button>
          </>
        )}
        {confirming && (
          <div className="post-menu-confirm">
            <p>取消发布后，「{work.title}」会从所有人的回响里移除，但原作品仍留在「故事」。确定吗？</p>
            {error && <div className="post-menu-error" role="alert">{error}</div>}
            <div className="post-menu-actions">
              <button type="button" onClick={() => setConfirming(false)} disabled={removing}>
                再想想
              </button>
              <button
                type="button"
                className="danger"
                onClick={unpublish}
                disabled={removing}
              >
                {removing ? '正在取消…' : '确认取消发布'}
              </button>
            </div>
          </div>
        )}
      </div>
    </BottomSheet>
  )
}
