export function getLocalDateStr(date: Date = new Date()): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const WEEKDAY_LABEL = ['日', '一', '二', '三', '四', '五', '六'] as const

export function weekdayLabel(date: Date): string {
  return `周${WEEKDAY_LABEL[date.getDay()]}`
}

export function parseLocalDate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}

export function addDays(s: string, delta: number): string {
  const d = parseLocalDate(s)
  d.setDate(d.getDate() + delta)
  return getLocalDateStr(d)
}
