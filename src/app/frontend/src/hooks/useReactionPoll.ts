import { useState, useEffect, useCallback } from 'react'
import { shareApi } from '../api/client'
import { useUser } from '../contexts/UserContext'

/**
 * Poll for unseen reactions every 30 seconds.
 * Returns the count of unseen reactions and a markSeen function.
 */
export function useReactionPoll() {
  const { currentUserId } = useUser()
  const [unseenCount, setUnseenCount] = useState(0)

  const check = useCallback(async () => {
    try {
      const res = await shareApi.unseenReactions(currentUserId)
      setUnseenCount(res.unseen_count)
    } catch {
      // silently ignore
    }
  }, [currentUserId])

  useEffect(() => {
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [check])

  const markSeen = useCallback(async () => {
    try {
      await shareApi.markSeen(currentUserId)
      setUnseenCount(0)
    } catch {
      // silently ignore
    }
  }, [currentUserId])

  return { unseenCount, markSeen }
}