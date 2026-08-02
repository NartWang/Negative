import { useState, useCallback } from 'react'

/**
 * Optimistic-update helper. Holds an array of items; mutations apply locally first,
 * then call an async commit. On failure, rolls back and surfaces the error.
 */
export interface OptimisticController<T> {
  items: T[]
  set: (items: T[]) => void
  commit: (
    apply: (prev: T[]) => T[],
    request: () => Promise<unknown>,
  ) => Promise<void>
}

export function useOptimistic<T>(initial: T[] = []): OptimisticController<T> {
  const [items, setItems] = useState<T[]>(initial)

  const commit = useCallback(
    async (
      apply: (prev: T[]) => T[],
      request: () => Promise<unknown>,
    ) => {
      let snapshot: T[] = []
      setItems(prev => {
        snapshot = prev
        return apply(prev)
      })
      try {
        await request()
      } catch (err) {
        setItems(snapshot)
        throw err
      }
    },
    [],
  )

  return { items, set: setItems, commit }
}
