import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { getLocalDateStr, addDays as addDaysFn } from '../utils/date'

interface DateContextValue {
  currentDate: string
  setCurrentDate: (date: string) => void
  goToday: () => void
  shift: (delta: number) => void
  isToday: boolean
}

const DateContext = createContext<DateContextValue | null>(null)

export function DateProvider({ children }: { children: ReactNode }) {
  const [currentDate, setCurrentDate] = useState(getLocalDateStr())
  const goToday = useCallback(() => setCurrentDate(getLocalDateStr()), [])
  const shift = useCallback((delta: number) => {
    setCurrentDate(prev => addDaysFn(prev, delta))
  }, [])
  return (
    <DateContext.Provider
      value={{
        currentDate,
        setCurrentDate,
        goToday,
        shift,
        isToday: currentDate === getLocalDateStr(),
      }}
    >
      {children}
    </DateContext.Provider>
  )
}

export function useCurrentDate(): DateContextValue {
  const ctx = useContext(DateContext)
  if (!ctx) throw new Error('useCurrentDate must be used inside DateProvider')
  return ctx
}
