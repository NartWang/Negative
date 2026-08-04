import { createContext, useContext, useMemo, useRef, useState, useCallback, ReactNode } from 'react'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

interface ToastActions {
  show: (kind: ToastKind, message: string) => void
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
}

interface ToastStack {
  toasts: ToastItem[]
  dismiss: (id: number) => void
}

const ToastActionsContext = createContext<ToastActions | null>(null)
const ToastStackContext = createContext<ToastStack | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextIdRef = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // Actions hold no reactive deps — their identity is stable across renders.
  const actions = useMemo<ToastActions>(() => {
    const show = (kind: ToastKind, message: string) => {
      const id = nextIdRef.current++
      setToasts(prev => [...prev, { id, kind, message }])
      setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 2500)
    }
    return {
      show,
      success: (m: string) => show('success', m),
      error: (m: string) => show('error', m),
      info: (m: string) => show('info', m),
    }
  }, [])

  // Stack is reactive — only the <Toast/> renderer subscribes here.
  const stack = useMemo<ToastStack>(() => ({ toasts, dismiss }), [toasts, dismiss])

  return (
    <ToastActionsContext.Provider value={actions}>
      <ToastStackContext.Provider value={stack}>
        {children}
      </ToastStackContext.Provider>
    </ToastActionsContext.Provider>
  )
}

/** Stable reference — safe to put in useEffect / useCallback deps. */
export function useToast(): ToastActions {
  const ctx = useContext(ToastActionsContext)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx
}

/** Reactive — re-renders when toast list changes. Only <Toast/> should call this. */
export function useToastStack(): ToastStack {
  const ctx = useContext(ToastStackContext)
  if (!ctx) throw new Error('useToastStack must be used inside ToastProvider')
  return ctx
}
