const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'
const isoDatePattern = /^\d{4}-\d{2}-\d{2}$/

function assertIsoDate(value: string): void {
  if (!isoDatePattern.test(value)) throw new Error('日期格式必须是 YYYY-MM-DD')
}

function dateParts(dateStr: string): { year: number; month: number; day: number } {
  assertIsoDate(dateStr)
  const [year, month, day] = dateStr.split('-').map(Number)
  return { year, month, day }
}

function utcDate(dateStr: string): Date {
  const { year, month, day } = dateParts(dateStr)
  return new Date(Date.UTC(year, month - 1, day))
}

function formatUtcDate(date: Date): string {
  return [
    String(date.getUTCFullYear()).padStart(4, '0'),
    String(date.getUTCMonth() + 1).padStart(2, '0'),
    String(date.getUTCDate()).padStart(2, '0'),
  ].join('-')
}

function addDateDays(dateStr: string, delta: number): string {
  const date = utcDate(dateStr)
  date.setUTCDate(date.getUTCDate() + delta)
  return formatUtcDate(date)
}

function shanghaiDateStr(date: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const lookup = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${lookup.year}-${lookup.month}-${lookup.day}`
}

/** Monday of the week containing `dateStr`. ISO weekday: Mon=1. */
export function weekStartOf(dateStr: string): string {
  const d = utcDate(dateStr)
  const dow = d.getUTCDay()                      // Sun=0..Sat=6
  const back = dow === 0 ? 6 : dow - 1           // distance back to Monday
  return addDateDays(dateStr, -back)
}

export function thisWeekRange(anchor: Date = new Date()): { start: string; end: string } {
  const today = shanghaiDateStr(anchor)
  const start = weekStartOf(today)
  return { start, end: addDateDays(start, 6) }
}

export function previousWeekRange(anchor: Date = new Date()): { start: string; end: string } {
  const today = shanghaiDateStr(anchor)
  const lastWeekAnchor = addDateDays(today, -7)
  const start = weekStartOf(lastWeekAnchor)
  const end = addDateDays(start, 6)
  return { start, end }
}

export function datesBetweenInclusive(start: string, end: string): string[] {
  assertIsoDate(start)
  assertIsoDate(end)
  if (start > end) return []
  const dates: string[] = []
  let cursor = start
  while (cursor <= end) {
    dates.push(cursor)
    cursor = addDateDays(cursor, 1)
  }
  return dates
}

export function customRange(start: string, end: string): { start: string; end: string } {
  assertIsoDate(start)
  assertIsoDate(end)
  if (start > end) throw new Error('开始日期不能晚于结束日期')
  if (datesBetweenInclusive(start, end).length > 31) {
    throw new Error('自选范围最长 31 天')
  }
  return { start, end }
}
