import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from 'react'
import { storyApi } from '../../api/client'
import type { ResonanceFeedItem } from '../../types'
import PostCard from './PostCard'

export interface FeedViewHandle {
  loadUntilWork: (workId: number) => Promise<boolean>
}

interface Props {
  onOpenOwnStoryWork: (workId: number) => void
  onOpenPublishedDetail: (workId: number) => void
  onGoStories?: () => void
}

function focusWorkCard(workId: number): void {
  window.requestAnimationFrame(() => {
    const card = document.querySelector<HTMLElement>(
      `[data-resonance-work-id="${workId}"]`,
    )
    if (!card) return
    if (typeof card.scrollIntoView === 'function') {
      card.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
    card.focus()
  })
}

function mergeItems(
  current: ResonanceFeedItem[],
  incoming: ResonanceFeedItem[],
): ResonanceFeedItem[] {
  const seen = new Set(current.map(item => item.id))
  return [...current, ...incoming.filter(item => {
    if (seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })]
}

const FeedView = forwardRef<FeedViewHandle, Props>(function FeedView(
  { onOpenOwnStoryWork, onOpenPublishedDetail, onGoStories },
  ref,
) {
  const [items, setItems] = useState<ResonanceFeedItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)
  const [locateError, setLocateError] = useState<string | null>(null)

  const load = useCallback(async (cursor: string | null, append: boolean) => {
    if (append) setLoadingMore(true)
    else setLoading(true)
    setError(null)
    try {
      const page = await storyApi.resonanceFeed(cursor)
      const ownItems = page.items.filter(item => item.mine)
      setItems(current => (append ? mergeItems(current, ownItems) : ownItems))
      setNextCursor(page.next_cursor)
    } catch {
      setError('动态暂时加载不出来')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [])

  const loadUntilWork = useCallback(async (workId: number) => {
    setLocateError(null)
    if (items.some(item => item.id === workId)) {
      focusWorkCard(workId)
      return true
    }

    setLocating(true)
    const seenCursors = new Set<string>()
    let cursor: string | null = null
    let accumulated: ResonanceFeedItem[] = []

    try {
      for (;;) {
        const page = await storyApi.resonanceFeed(cursor, 50)
        accumulated = mergeItems(accumulated, page.items.filter(item => item.mine))
        setItems(accumulated)
        setNextCursor(page.next_cursor)

        if (accumulated.some(item => item.id === workId)) {
          setLocating(false)
          focusWorkCard(workId)
          return true
        }

        if (!page.next_cursor) {
          setLocating(false)
          setLocateError('这个故事已不可见')
          return false
        }

        if (seenCursors.has(page.next_cursor)) {
          setLocating(false)
          setLocateError('定位故事失败，请重试')
          return false
        }

        seenCursors.add(page.next_cursor)
        cursor = page.next_cursor
      }
    } catch {
      setLocating(false)
      setLocateError('定位故事失败，请重试')
      return false
    }
  }, [items])

  useImperativeHandle(ref, () => ({ loadUntilWork }), [loadUntilWork])

  useEffect(() => {
    void load(null, false)
  }, [load])

  const removeWork = useCallback((workId: number, message?: string) => {
    setItems(current => current.filter(item => item.id !== workId))
    if (message) setLocateError(message)
  }, [])

  if (loading) {
    return <div className="resonance-state" role="status">正在读取动态…</div>
  }
  if (error) {
    return (
      <div className="resonance-state" role="alert">
        <p>{error}</p>
        <button type="button" onClick={() => void load(null, false)}>重试</button>
      </div>
    )
  }
  const guidance = (
    <div className="resonance-empty resonance-empty-persistent">
        {locating && <span role="status">正在定位故事…</span>}
        {locateError && <span role="alert">{locateError}</span>}
        <p>还没有发布故事</p>
        <span>完成一个故事后，点「发布到回响」就会出现在这里。</span>
        {onGoStories && (
          <button type="button" onClick={onGoStories}>去故事看看</button>
        )}
    </div>
  )

  if (items.length === 0) return guidance

  return (
    <div className="resonance-feed-layout">
      {guidance}
      <h2 className="resonance-feed-section-title">我的底片</h2>
      <div className="resonance-feed resonance-feed-lowered">
      {locating && <div className="resonance-locate-state" role="status">正在定位故事…</div>}
      {locateError && <div className="resonance-locate-state" role="alert">{locateError}</div>}
      {items.map(item => (
        <PostCard
          key={item.id}
          item={item}
          onOpenOwnStoryWork={onOpenOwnStoryWork}
          onOpenPublishedDetail={onOpenPublishedDetail}
          onRemove={removeWork}
        />
      ))}
      {nextCursor && (
        <button
          type="button"
          className="resonance-load-more"
          disabled={loadingMore}
          onClick={() => void load(nextCursor, true)}
        >
          {loadingMore ? '加载中…' : '加载更多'}
        </button>
      )}
      </div>
    </div>
  )
})

export default FeedView
