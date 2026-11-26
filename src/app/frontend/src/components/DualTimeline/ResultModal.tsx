import type { DualTimelineComic } from '../../types'
import Modal from '../Modal'
import './style.css'

interface Props {
  comic: DualTimelineComic | null
  onClose: () => void
  onRetry: () => void
  onShare: () => void
  onDelete: () => void
}

export default function ResultModal({ comic, onClose, onRetry, onShare, onDelete }: Props) {
  if (!comic) return null
  return (
    <Modal open={true} onClose={onClose} title={comic.caption || '同一天的两面'}>
      <img className="dt-result-img" src={comic.url} alt={comic.caption || ''} />
      <div className="dt-result-meta">{comic.date}</div>
      <div className="dt-result-actions">
        <button className="dt-btn dt-btn-secondary" onClick={onRetry}>🔄 重新生成</button>
        <button className="dt-btn dt-btn-secondary" onClick={onShare}>📤 分享</button>
        <button className="dt-btn dt-btn-danger" onClick={onDelete}>🗑 删除</button>
      </div>
    </Modal>
  )
}
