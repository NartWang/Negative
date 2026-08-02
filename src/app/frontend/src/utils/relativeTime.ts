import { getLocalDateStr } from './date'

/**
 * Render a timestamp as relative time, e.g.:
 *  - within 60s → "刚刚"
 *  - same day → "14:32"
 *  - yesterday → "昨天 14:32"
 *  - otherwise → "5/20 14:32"
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ''
  // SQLite returns "YYYY-MM-DD HH:MM:SS" (UTC). Treat as UTC for parsing.
  const normalized = iso.includes('T') ? iso : iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z')
  const t = new Date(normalized)
  if (isNaN(t.getTime())) return ''

  const now = new Date()
  const diffSec = Math.floor((now.getTime() - t.getTime()) / 1000)
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`

  const today = getLocalDateStr(now)
  const dStr = getLocalDateStr(t)
  const hhmm = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`

  if (dStr === today) return hhmm

  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (dStr === getLocalDateStr(yesterday)) return `昨天 ${hhmm}`

  return `${t.getMonth() + 1}/${t.getDate()} ${hhmm}`
}
