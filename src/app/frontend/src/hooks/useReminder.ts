import { useEffect } from 'react'
import { getLocalDateStr } from '../utils/date'

export function useReminder() {
  useEffect(() => {
    const check = () => {
      const reminderTime = localStorage.getItem('reminderTime') || '21:00'
      const now = new Date()
      const [h, m] = reminderTime.split(':').map(Number)
      const isTime = now.getHours() === h && now.getMinutes() === m

      if (isTime) {
        const lastReminder = localStorage.getItem('lastReminderDate')
        const today = getLocalDateStr(now)
        if (lastReminder !== today) {
          localStorage.setItem('lastReminderDate', today)
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('知己', { body: '今天还没生成日记哦，来记录一下吧 ✨' })
          } else if ('Notification' in window && Notification.permission !== 'denied') {
            Notification.requestPermission()
          }
        }
      }
    }

    const interval = setInterval(check, 60000)
    check()
    return () => clearInterval(interval)
  }, [])
}
