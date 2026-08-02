import type { DiaryImage } from '../../types'
import './style.css'

interface Props {
  candidates: DiaryImage[]
  kept: number[]
  onToggle: (id: number) => void
}

export default function ImageCandidates({ candidates, kept, onToggle }: Props) {
  if (candidates.length === 0) return null
  return (
    <div className="img-candidates">
      {candidates.map(img => {
        const active = kept.includes(img.id)
        return (
          <button
            key={img.id}
            className={`ic-tile ${active ? 'active' : ''}`}
            onClick={() => onToggle(img.id)}
          >
            <img src={img.url} alt="候选图" />
            <span className="ic-tick">{active ? '✓' : ''}</span>
          </button>
        )
      })}
    </div>
  )
}
