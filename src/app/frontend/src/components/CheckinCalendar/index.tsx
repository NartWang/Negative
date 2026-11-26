import { useState, useEffect } from 'react'
import { streaksApi } from '../../api/client'
import type { StreakInfo } from '../../types'
import { useCurrentDate } from '../../contexts/DateContext'
import { getLocalDateStr, parseLocalDate } from '../../utils/date'
import './style.css'

function getMonthDays(year: number, month: number): (Date | null)[] {
  const firstDay = new Date(year, month, 1)
  const lastDay = new Date(year, month + 1, 0)
  const startWeekday = firstDay.getDay()
  const totalDays = lastDay.getDate()
  const cells: (Date | null)[] = []
  for (let i = 0; i < startWeekday; i++) cells.push(null)
  for (let d = 1; d <= totalDays; d++) cells.push(new Date(year, month, d))
  return cells
}

const fmt = (d: Date) => getLocalDateStr(d)

interface Props {
  onSelectDate?: (date: string) => void
  markerMode?: 'all' | 'fragments'
  selectedDate?: string
}

export default function CheckinCalendar({ onSelectDate, markerMode = 'all', selectedDate }: Props) {
  const { currentDate, setCurrentDate } = useCurrentDate()
  const [info, setInfo] = useState<StreakInfo | null>(null)
  const activeDate = selectedDate ?? currentDate
  const initial = parseLocalDate(activeDate)
  const [year, setYear] = useState(initial.getFullYear())
  const [month, setMonth] = useState(initial.getMonth())

  useEffect(() => { streaksApi.get().then(setInfo).catch(() => {}) }, [activeDate])

  useEffect(() => {
    const next = parseLocalDate(activeDate)
    setYear(next.getFullYear())
    setMonth(next.getMonth())
  }, [activeDate])

  const days = getMonthDays(year, month)
  const todayStr = getLocalDateStr(new Date())
  const calendarData = info?.calendar_data || {}

  const prev = () => { if (month === 0) { setYear(year - 1); setMonth(11) } else setMonth(month - 1) }
  const next = () => { if (month === 11) { setYear(year + 1); setMonth(0) } else setMonth(month + 1) }

  return (
    <div className="checkin-calendar">
      <div className="cal-header">
        <button onClick={prev} aria-label="上一月">‹</button>
        <span className="cal-title">{year} 年 {month + 1} 月</span>
        <button onClick={next} aria-label="下一月">›</button>
      </div>
      <div className="cal-weekdays">
        {['日','一','二','三','四','五','六'].map(d => (
          <div key={d} className="cal-weekday">{d}</div>
        ))}
      </div>
      <div className="cal-grid">
        {days.map((d, i) => {
          if (!d) return <div key={i} className="cal-cell empty" />
          const ds = fmt(d)
          const entry = calendarData[ds]
          const hasRecord = markerMode === 'fragments'
            ? !!(entry && entry.has_fragment)
            : !!(entry && (entry.has_schedule || entry.has_fragment))
          const isToday = ds === todayStr
          const isSelected = ds === activeDate
          return (
            <button
              key={i}
              className={[
                'cal-cell',
                hasRecord ? 'has-record' : '',
                isToday ? 'is-today' : '',
                isSelected ? 'is-selected' : '',
              ].filter(Boolean).join(' ')}
              onClick={() => {
                setCurrentDate(ds)
                onSelectDate?.(ds)
              }}
            >
              <span className="cal-day">{d.getDate()}</span>
              {hasRecord && <span className="cal-tick">✓</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
