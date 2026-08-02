import type { WeeklyComic } from '../../types'
import { formatSent } from '../../utils/sentBadge'
import './style.css'

interface Props {
  comics: WeeklyComic[]
  onOpen: (c: WeeklyComic) => void
}

export default function Thumbnails({ comics, onOpen }: Props) {
  if (comics.length === 0) return null
  return (
    <div className="wc-thumbs-scroll">
      {comics.map(c => {
        const sent = formatSent(c.last_sent_at)
        return (
          <button key={c.id} className="wc-thumb pressable" onClick={() => onOpen(c)}>
            <div className="wc-thumb-img-wrap">
              <img src={c.url} alt={c.caption || ''} />
              {sent && <div className="wc-thumb-sent">{sent}</div>}
            </div>
            <div className="wc-thumb-caption">{c.caption || '本周漫画'}</div>
            <div className="wc-thumb-range">{c.week_start.slice(5)} ~ {c.week_end.slice(5)}</div>
          </button>
        )
      })}
    </div>
  )
}
