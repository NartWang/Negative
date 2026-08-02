import type { DualTimelineComic } from '../../types'
import Modal from '../Modal'
import SendLetter from '../SendLetter'
import './style.css'

interface Props {
  comic: DualTimelineComic | null
  onClose: () => void
  onRetry: () => void
  onShare: () => void
  onDelete: () => void
  onSent?: (id: number, sentAt: string) => void
}

export default function ResultModal({ comic, onClose, onRetry, onShare, onDelete, onSent }: Props) {
  if (!comic) return null
  const title = `🖼 ${comic.date} 双人画`
  const body =
    (comic.caption || '同一天，两个世界，在同一张画里相遇。') +
    '\n\n在 App 里看完整内容 ✨'
  return (
    <Modal open={true} onClose={onClose} title={comic.caption || '同一天的两面'}>
      <img className="dt-result-img" src={comic.url} alt={comic.caption || ''} />
      <div className="dt-result-meta">{comic.date}</div>
      <div className="dt-result-actions">
        <SendLetter
          type="dual_timeline"
          id={comic.id}
          title={title}
          body={body}
          onSent={(sentAt) => onSent?.(comic.id, sentAt)}
        />
        <button className="dt-btn dt-btn-secondary" onClick={onRetry}>🔄 重新生成</button>
        <button className="dt-btn dt-btn-secondary" onClick={onShare}>📤 分享</button>
        <button className="dt-btn dt-btn-danger" onClick={onDelete}>🗑 删除</button>
      </div>
    </Modal>
  )
}
