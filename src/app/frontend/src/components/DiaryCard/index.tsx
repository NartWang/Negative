import type { Diary } from '../../types'
import './style.css'

const BADGES: Record<string, { label: string; cls: string }> = {
  ai:     { label: 'AI', cls: 'ai' },
  hybrid: { label: 'AI+你', cls: 'hybrid' },
  manual: { label: '手写', cls: 'manual' },
}

interface Props {
  diary: Diary
  onClick: () => void
  onDelete?: () => void
}

export default function DiaryCard({ diary, onClick, onDelete }: Props) {
  const imageUrl = diary.images?.find(i => i.kept === 1)?.url ?? diary.images?.[0]?.url
  const badge = diary.status === 'draft'
    ? { label: '草稿', cls: 'draft' }
    : (BADGES[diary.source] ?? BADGES.manual)
  const text = (diary.text || diary.draft_text || '').trim()
  const preview = text.length > 70 ? text.slice(0, 70) + '…' : (text || '（暂无内容）')

  return (
    <article className="diary-card">
      <button className="diary-card-main pressable" onClick={onClick}>
        {imageUrl ? (
          <img src={imageUrl} alt="" className="diary-card-image" />
        ) : (
          <div className="diary-card-placeholder">日记</div>
        )}
        <div className="diary-card-info">
          <div className="diary-card-header">
            <span className="diary-card-date">{diary.date}</span>
            <span className={`diary-card-badge ${badge.cls}`}>{badge.label}</span>
          </div>
          <div className="diary-card-preview">{preview}</div>
        </div>
      </button>
      {onDelete && (
        <button
          className="diary-card-delete"
          type="button"
          aria-label={`删除 ${diary.date}`}
          onClick={onDelete}
        >
          删除
        </button>
      )}
    </article>
  )
}
