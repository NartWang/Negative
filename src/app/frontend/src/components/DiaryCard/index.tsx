import type { Diary } from '../../types'
import './style.css'

const BADGES: Record<string, { label: string; cls: string }> = {
  ai:     { label: 'AI ✨', cls: 'ai' },
  hybrid: { label: 'AI+你', cls: 'hybrid' },
  manual: { label: '手写 ✍️', cls: 'manual' },
}

export default function DiaryCard({ diary, onClick }: { diary: Diary; onClick: () => void }) {
  const imageUrl = diary.images?.find(i => i.kept === 1)?.url ?? diary.images?.[0]?.url
  const badge = diary.status === 'draft'
    ? { label: '草稿 📝', cls: 'draft' }
    : (BADGES[diary.source] ?? BADGES.manual)
  const text = (diary.text || diary.draft_text || '').trim()
  const preview = text.length > 70 ? text.slice(0, 70) + '…' : (text || '（暂无内容）')

  return (
    <button className="diary-card pressable" onClick={onClick}>
      {imageUrl ? (
        <img src={imageUrl} alt="" className="diary-card-image" />
      ) : (
        <div className="diary-card-placeholder">📖</div>
      )}
      <div className="diary-card-info">
        <div className="diary-card-header">
          <span className="diary-card-date">{diary.date}</span>
          <span className={`diary-card-badge ${badge.cls}`}>{badge.label}</span>
        </div>
        <div className="diary-card-preview">{preview}</div>
      </div>
    </button>
  )
}
