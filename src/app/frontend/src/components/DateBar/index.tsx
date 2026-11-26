import { useState } from 'react'
import { BookOpen } from 'lucide-react'
import { useCurrentDate } from '../../contexts/DateContext'
import { parseLocalDate, weekdayLabel } from '../../utils/date'
import BottomSheet from '../BottomSheet'
import CheckinCalendar from '../CheckinCalendar'
import './style.css'

interface Props {
  onOpenNotebook?: () => void
}

export default function DateBar({ onOpenNotebook }: Props) {
  const { currentDate, shift, goToday, isToday } = useCurrentDate()
  const [calendarOpen, setCalendarOpen] = useState(false)
  const d = parseLocalDate(currentDate)
  return (
    <header className="date-bar">
      <div className="date-bar-grid">
        <div className="date-bar-side" aria-hidden="true" />
        <div className="date-bar-center">
          <button className="date-arrow" onClick={() => shift(-1)} aria-label="前一天">
            ‹
          </button>
          <button
            className="date-center"
            onClick={() => setCalendarOpen(true)}
            aria-label="选择日期"
          >
            <span className="date-text">{currentDate}</span>
            <span className="date-week">{weekdayLabel(d)}</span>
          </button>
          <button className="date-arrow" onClick={() => shift(1)} aria-label="后一天">
            ›
          </button>
        </div>
        <div className="date-bar-side">
          {onOpenNotebook && (
            <button
              className="date-notebook-btn"
              onClick={onOpenNotebook}
              aria-label="打开故事"
            >
              <BookOpen size={23} />
              <span className="date-notebook-text">故事</span>
            </button>
          )}
        </div>
      </div>
      {!isToday && (
        <div className="date-bar-below">
          <button className="date-today-btn" onClick={goToday}>回到今天</button>
        </div>
      )}
      <BottomSheet
        open={calendarOpen}
        onClose={() => setCalendarOpen(false)}
        title="选择日期"
      >
        <CheckinCalendar
          markerMode="fragments"
          onSelectDate={() => setCalendarOpen(false)}
        />
      </BottomSheet>
    </header>
  )
}
