import type { Fragment } from '../types'

export const RECORD_TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/

export function recordClockTime(value?: string | null): string {
  if (!value) return ''
  const timestamp = value.replace(' ', 'T')
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)
    ? timestamp
    : `${timestamp}Z`
  const parsed = new Date(normalized)
  if (Number.isNaN(parsed.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(parsed)
}

export function currentShanghaiClock(now = new Date()): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(now)
}

export function fragmentClockTime(
  fragment: Pick<Fragment, 'record_time' | 'created_at'>,
): string {
  return fragment.record_time && RECORD_TIME_PATTERN.test(fragment.record_time)
    ? fragment.record_time
    : recordClockTime(fragment.created_at)
}

export function readableClockTime(value: string): string {
  if (!RECORD_TIME_PATTERN.test(value)) return value
  const [hourText, minute] = value.split(':')
  const hour = Number(hourText)
  const period = hour < 5 ? '凌晨'
    : hour < 9 ? '早上'
      : hour < 12 ? '上午'
        : hour < 14 ? '中午'
          : hour < 18 ? '下午'
            : '晚上'
  const twelveHour = hour % 12 || 12
  return `${period} ${twelveHour}:${minute}`
}
