import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { ApiError, authApi, subscribeUnauthorized } from '../api/client'
import type { AuthProfile } from '../types'

type AuthStatus = 'loading' | 'ready'

interface AuthContextValue {
  user: AuthProfile | null
  status: AuthStatus
  bootstrapError: string | null
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, nickname: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthProfile | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [bootstrapError, setBootstrapError] = useState<string | null>(null)

  useEffect(() => subscribeUnauthorized(() => {
    setBootstrapError(null)
    setStatus('ready')
    setUser(null)
  }), [])

  useEffect(() => {
    let active = true
    authApi.me()
      .then(profile => {
        if (active) setUser(profile)
      })
      .catch(error => {
        if (!active) return
        if (!(error instanceof ApiError) || error.status !== 401) {
          setBootstrapError('暂时无法连接服务，请稍后重试')
        }
        setUser(null)
      })
      .finally(() => {
        if (active) setStatus('ready')
      })
    return () => { active = false }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const profile = await authApi.login({ username, password })
    setBootstrapError(null)
    setUser(profile)
  }, [])

  const register = useCallback(async (username: string, password: string, nickname: string) => {
    const profile = await authApi.register({ username, password, nickname })
    setBootstrapError(null)
    setUser(profile)
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
      setUser(null)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null)
        return
      }
      throw error
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    status,
    bootstrapError,
    login,
    register,
    logout,
  }), [user, status, bootstrapError, login, register, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
