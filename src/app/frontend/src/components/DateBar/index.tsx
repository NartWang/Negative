import { useCurrentDate } from '../../contexts/DateContext'
import { parseLocalDate, weekdayLabel } from '../../utils/date'
import './style.css'

export default function DateBar() {
  const { currentDate, shift, goToday, isToday } = useCurrentDate()
  const d = parseLocalDate(currentDate)
  return (
    <header className="date-bar">
      <button className="date-arrow" onClick={() => shift(-1)} aria-label="前一天">
        ‹
      </button>
      <div className="date-center">
        <div className="date-text">{currentDate}</div>
        <div className="date-week">{weekdayLabel(d)}</div>
      </div>
      <button className="date-arrow" onClick={() => shift(1)} aria-label="后一天">
        ›
      </button>
      {!isToday && (
        <button className="date-today-btn" onClick={goToday}>回到今天</button>
      )}
      <div className="date-bar-spacer" />
    </header>
  )
}
