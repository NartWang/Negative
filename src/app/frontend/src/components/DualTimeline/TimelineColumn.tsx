import type { TimelineEvent } from '../../types'
import EventCard from './EventCard'
import './style.css'

interface Props {
  title: string
  side: 'left' | 'right'
  events: TimelineEvent[]
  selectedIds: Set<string>
  onToggle: (event: TimelineEvent) => void
  canSelectMore: boolean
}

export function eventKey(side: 'a' | 'b', e: TimelineEvent): string {
  return `${side}:${e.type}:${e.id}`
}

export default function TimelineColumn({ title, side, events, selectedIds, onToggle, canSelectMore }: Props) {
  const sideKey: 'a' | 'b' = side === 'left' ? 'a' : 'b'
  return (
    <div className={`dt-col dt-col-${side}`}>
      <div className="dt-col-header">👤 {title}</div>
      <div className="dt-col-list">
        {events.length === 0 ? (
          <div className="dt-col-empty">这天还没有记录</div>
        ) : events.map(e => {
          const k = eventKey(sideKey, e)
          const selected = selectedIds.has(k)
          return (
            <EventCard
              key={k}
              event={e}
              selected={selected}
              onToggle={() => onToggle(e)}
              disabled={!canSelectMore}
            />
          )
        })}
      </div>
    </div>
  )
}
