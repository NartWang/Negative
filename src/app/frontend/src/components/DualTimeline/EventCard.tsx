import type { TimelineEvent } from '../../types'
import './style.css'

interface Props {
  event: TimelineEvent
  selected: boolean
  onToggle: () => void
  disabled?: boolean
}

const MOOD_LABEL: Record<string, string> = {
  happy: '开心', warm: '温暖', calm: '平静', sad: '低落',
}

export default function EventCard({ event, selected, onToggle, disabled }: Props) {
  const title = event.type === 'schedule'
    ? (event.title || '(无标题)')
    : (event.content || '(空)')

  const meta: string[] = []
  if (event.type === 'schedule' && event.completed) meta.push('完成')
  if (event.type === 'schedule' && event.feeling) meta.push(event.feeling)
  if (event.type === 'fragment' && event.mood_tag) {
    meta.push(MOOD_LABEL[event.mood_tag] || event.mood_tag)
  }

  return (
    <button
      className={`dt-event ${selected ? 'selected' : ''} ${disabled && !selected ? 'disabled' : ''}`}
      onClick={onToggle}
      disabled={disabled && !selected}
    >
      <span className={`dt-event-check ${selected ? 'on' : ''}`}>{selected ? '✓' : ''}</span>
      <div className="dt-event-body">
        <div className="dt-event-head">
          <span className="dt-event-time">{event.time}</span>
          <span className="dt-event-kind">{event.type === 'schedule' ? '日程' : '碎片'}</span>
        </div>
        <div className="dt-event-title">{title}</div>
        {meta.length > 0 && <div className="dt-event-meta">{meta.join(' · ')}</div>}
      </div>
    </button>
  )
}
