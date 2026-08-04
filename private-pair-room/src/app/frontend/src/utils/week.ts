import { getLocalDateStr, addDays } from './date'

/** Monday of the week containing `dateStr`. ISO weekday: Mon=1. */
export function weekStartOf(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`)
  const dow = d.getDay()                         // Sun=0..Sat=6
  const back = dow === 0 ? 6 : dow - 1           // distance back to Monday
  return addDays(dateStr, -back)
}

export function thisWeekRange(): { start: string; end: string } {
  const today = getLocalDateStr()
  return { start: weekStartOf(today), end: today }
}

export function previousWeekRange(): { start: string; end: string } {
  const today = getLocalDateStr()
  const lastWeekAnchor = addDays(today, -7)
  const start = weekStartOf(lastWeekAnchor)
  const end = addDays(start, 6)
  return { start, end }
}
