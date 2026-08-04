import { useCallback, useEffect, useRef, useState } from 'react'
import type { WeeklyComic } from '../../types'
import { roomsApi } from '../../api/client'
import { useRoom } from '../../contexts/RoomContext'
import { useToast } from '../../contexts/ToastContext'
import Modal from '../Modal'
import PublishSheet from '../PublishSheet'
import './style.css'

interface Props {
  comic: WeeklyComic | null
  onClose: () => void
  onRetry: () => void
  onShare: () => void
  onDelete: () => void
}

export default function ResultModal({ comic, onClose, onRetry, onShare, onDelete }: Props) {
  const { room } = useRoom()
  const toast = useToast()
  const [showPublish, setShowPublish] = useState(false)
  const publishButtonRef = useRef<HTMLButtonElement>(null)
  const restorePublishFocus = useCallback(() => {
    publishButtonRef.current?.focus()
  }, [])
  useEffect(() => setShowPublish(false), [comic?.id])
  if (!comic) return null

  const publish = async () => {
    if (!room || room.state !== 'paired') throw new Error('双人房间尚未就绪')
    await roomsApi.publishComic(room.id, comic.id)
    toast.success(`已发布给${room.partner?.nickname ?? '对方'}`)
  }

  return (
    <>
      {!showPublish && <Modal open={true} onClose={onClose} title={comic.caption || '本周漫画'}>
        <img className="wc-result-img" src={comic.url} alt={comic.caption || ''} />
        <div className="wc-result-meta">
          {comic.week_start} — {comic.week_end}
        </div>
        <div className="wc-result-actions">
          <button ref={publishButtonRef} className="wc-btn wc-btn-primary" onClick={() => setShowPublish(true)}>
            发布给{room?.partner?.nickname ?? '对方'}
          </button>
          <button className="wc-btn wc-btn-secondary" onClick={onRetry}>重新生成</button>
          <button className="wc-btn wc-btn-secondary" onClick={onShare}>保存分享</button>
          <button className="wc-btn wc-btn-danger" onClick={onDelete}>删除</button>
        </div>
      </Modal>}
      <PublishSheet
        open={showPublish}
        kind="weekly_comic"
        title={`${comic.week_start} — ${comic.week_end}`}
        summary={comic.caption || '这一周，我把日子折叠成一张画。'}
        images={[{ id: comic.id, url: comic.url, alt: comic.caption || '本周漫画' }]}
        onClose={() => setShowPublish(false)}
        onConfirm={publish}
        onRestoreFocus={restorePublishFocus}
      />
    </>
  )
}
