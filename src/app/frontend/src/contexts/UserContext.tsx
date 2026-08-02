import { createContext, useContext, useState, useEffect, useCallback, useMemo, ReactNode } from 'react'
import type { User } from '../types'

const STORAGE_KEY = 'zhiji.currentUserId'

interface UserContextValue {
  currentUserId: number
  setCurrentUserId: (id: number) => void
  users: User[]
  currentUser: User | null
  refresh: () => Promise<void>
}

const UserContext = createContext<UserContextValue | null>(null)

function readStoredUserId(): number {
  const raw = localStorage.getItem(STORAGE_KEY)
  const n = raw ? Number(raw) : 1
  return Number.isFinite(n) && n > 0 ? n : 1
}

// Global mirror so non-React code (api/client.ts) can read the active user.
let activeUserId = readStoredUserId()
export function getActiveUserId(): number {
  return activeUserId
}

export function UserProvider({ children }: { children: ReactNode }) {
  const [currentUserId, setCurrentUserIdState] = useState<number>(readStoredUserId())
  const [users, setUsers] = useState<User[]>([])

  const refresh = useCallback(async () => {
    const res = await fetch('/api/users')
    if (!res.ok) return
    const data: User[] = await res.json()
    setUsers(data)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const setCurrentUserId = useCallback((id: number) => {
    setCurrentUserIdState(id)
    activeUserId = id
    localStorage.setItem(STORAGE_KEY, String(id))
  }, [])

  const currentUser = useMemo(
    () => users.find(u => u.id === currentUserId) ?? null,
    [users, currentUserId],
  )

  const value = useMemo<UserContextValue>(() => ({
    currentUserId, setCurrentUserId, users, currentUser, refresh,
  }), [currentUserId, setCurrentUserId, users, currentUser, refresh])

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>
}

export function useUser(): UserContextValue {
  const ctx = useContext(UserContext)
  if (!ctx) throw new Error('useUser must be used inside UserProvider')
  return ctx
}
