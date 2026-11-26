import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, storyApi } from '../../api/client'
import type { ResonanceFeedItem, SubscriptionProfile } from '../../types'
import { ArrowLeft } from '../../components/Icon'

interface Props {
  ownerUserId: number
  onBack: () => void
  onOpenPublishedDetail: (workId: number) => void
  onCollectionGone?: () => void
}

export default function CollectionDetail({
  ownerUserId,
  onBack,
  onOpenPublishedDetail,
  onCollectionGone,
}: Props) {
  const [owner, setOwner] = useState<SubscriptionProfile | null>(null)
  const [items, setItems] = useState<ResonanceFeedItem[]>([])
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (nextOrder: 'asc' | 'desc', cursor: string | null, append: boolean) => {
      if (append) setLoadingMore(true)
      else setLoading(true)
      setError(null)
      try {
        const page = await storyApi.collection(ownerUserId, { order: nextOrder, cursor })
        setOwner(page.owner)
        setItems(current => (append ? [...current, ...page.items] : page.items))
        setNextCursor(page.next_cursor)
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setItems([])
          setOwner(null)
          setError('这个故事已不可见')
          onCollectionGone?.()
          return
        }
        setError('合集暂时加载不出来')
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [ownerUserId, onCollectionGone],
  )

  useEffect(() => {
    void load('desc', null, false)
  }, [load])

  const switchOrder = (nextOrder: 'asc' | 'desc') => {
    setOrder(nextOrder)
    setItems([])
    setNextCursor(null)
    void load(nextOrder, null, false)
  }

  const groups = useMemo(() => {
    const byYear = new Map<string, ResonanceFeedItem[]>()
    for (const item of items) {
      const year = new Date(item.published_at).getFullYear().toString()
      const bucket = byYear.get(year)
      if (bucket) bucket.push(item)
      else byYear.set(year, [item])
    }
    return [...byYear.entries()]
  }, [items])

  return (
    <section className="resonance-collection-detail" aria-labelledby="collection-detail-title">
      <header className="resonance-collection-detail-head">
        <button type="button" className="resonance-back" onClick={onBack} aria-label="返回他们的故事">
          <ArrowLeft />
        </button>
        <h2 id="collection-detail-title">{owner ? `${owner.nickname}的故事` : '他们的故事'}</h2>
        <button
          type="button"
          className="resonance-order-toggle"
          onClick={() => switchOrder(order === 'desc' ? 'asc' : 'desc')}
        >
          {order === 'desc' ? '从最早开始' : '从最新开始'}
        </button>
      </header>

      {loading && <div className="resonance-state" role="status">正在读取…</div>}
      {error && !loading && (
        <div className="resonance-state" role="alert">
          <p>{error}</p>
          <button type="button" onClick={onBack}>回到他们的故事</button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="resonance-collections-empty">这个合集暂时没有故事</p>
      )}

      {!loading && !error && groups.map(([year, works]) => (
        <div key={year} className="resonance-year-group">
          <h3>{year} 年</h3>
          <ul>
            {works.map(item => {
              const cover = item.assets.find(
                asset => asset.asset_type === 'image' && asset.url,
              )
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className="resonance-collection-work"
                    onClick={() => onOpenPublishedDetail(item.id)}
                  >
                    {cover?.url && <img src={cover.url} alt="" />}
                    <span>{item.title}</span>
                    <time dateTime={item.published_at}>
                      {new Date(item.published_at).toLocaleDateString('zh-CN')}
                    </time>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}

      {nextCursor && !loading && !error && (
        <button
          type="button"
          className="resonance-load-more"
          disabled={loadingMore}
          onClick={() => void load(order, nextCursor, true)}
        >
          {loadingMore ? '加载中…' : '加载更多'}
        </button>
      )}
    </section>
  )
}
