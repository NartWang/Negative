import type { DualTimelineComic } from '../../types'
import './style.css'

interface Props {
  comics: DualTimelineComic[]
  onOpen: (c: DualTimelineComic) => void
}

export default function Thumbnails({ comics, onOpen }: Props) {
  if (comics.length === 0) return null
  return (
    <div className="dt-thumbs-scroll">
      {comics.map(c => (
        <button key={c.id} className="dt-thumb pressable" onClick={() => onOpen(c)}>
          <img src={c.url} alt={c.caption || ''} />
          <div className="dt-thumb-caption">{c.caption || '同一天的两面'}</div>
          <div className="dt-thumb-date">{c.date.slice(5)}</div>
        </button>
      ))}
    </div>
  )
}
