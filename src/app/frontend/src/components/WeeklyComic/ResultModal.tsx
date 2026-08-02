import type { WeeklyComic } from '../../types'
import Modal from '../Modal'
import SendLetter from '../SendLetter'
import './style.css'

interface Props {
  comic: WeeklyComic | null
  onClose: () => void
  onRetry: () => void
  onShare: () => void
  onDelete: () => void
  onSent?: (id: number, sentAt: string) => void
}

export default function ResultModal({ comic, onClose, onRetry, onShare, onDelete, onSent }: Props) {
  if (!comic) return null
  const title = `🖼 ${comic.week_start} ~ ${comic.week_end} 的一周漫画`
  const body =
    (comic.caption || '这一周，我把日子缝成了一张画。') +
    '\n\n在 App 里看完整漫画 ✨'
  return (
    <Modal open={true} onClose={onClose} title={comic.caption || '本周漫画'}>
      <img className="wc-result-img" src={comic.url} alt={comic.caption || ''} />
      <div className="wc-result-meta">
        {comic.week_start} — {comic.week_end}
      </div>
      <div className="wc-result-actions">
        <SendLetter
          type="comic"
          id={comic.id}
          title={title}
          body={body}
          onSent={(sentAt) => onSent?.(comic.id, sentAt)}
        />
        <button className="wc-btn wc-btn-secondary" onClick={onRetry}>🔄 重新生成</button>
        <button className="wc-btn wc-btn-secondary" onClick={onShare}>📤 分享</button>
        <button className="wc-btn wc-btn-danger" onClick={onDelete}>🗑 删除</button>
      </div>
    </Modal>
  )
}
