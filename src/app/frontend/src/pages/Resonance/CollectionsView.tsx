import { useCallback, useEffect, useState } from 'react'
import { storyApi } from '../../api/client'
import type { CollectedStoryOwner } from '../../types'
import { ChevronRight } from '../../components/Icon'

interface Props {
  onOpenOwner: (ownerUserId: number) => void
}

function ProfileAvatar({ nickname, url }: { nickname: string; url: string | null }) {
  const [broken, setBroken] = useState(false)
  if (url && !broken) {
    return (
      <img
        className="resonance-collection-avatar"
        src={url}
        alt={nickname}
        onError={() => setBroken(true)}
      />
    )
  }
  return (
    <span className="resonance-collection-avatar placeholder" aria-hidden="true">
      {nickname.slice(0, 1) || '故'}
    </span>
  )
}

function formatStyle(style: string | undefined, nickname: string): string {
  const labels = {
    watercolor: '水彩风',
    crayon: '蜡笔风',
    sketch: '素描风',
    pixel: '像素风',
  } as Record<string, string>
  const demoStyles: Record<string, string> = {
    小虎: '蜡笔风',
    小满: '水彩风',
    白大夫: '像素风',
    云奶奶: '素描风',
  }
  return (style && labels[style]) || style || demoStyles[nickname] || '绘本风'
}

export default function CollectionsView({ onOpenOwner }: Props) {
  const [items, setItems] = useState<CollectedStoryOwner[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (cursor: string | null, append: boolean) => {
    if (append) setLoadingMore(true)
    else setLoading(true)
    setError(null)
    try {
      const page = await storyApi.collections(cursor)
      setItems(current => (append ? [...current, ...page.items] : page.items))
      setNextCursor(page.next_cursor)
    } catch {
      setError('收录暂时加载不出来')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [])

  useEffect(() => {
    void load(null, false)
  }, [load])

  if (loading) {
    return <div className="resonance-state" role="status">正在读取收录…</div>
  }
  if (error) {
    return (
      <div className="resonance-state" role="alert">
        <p>{error}</p>
        <button type="button" onClick={() => void load(null, false)}>重试</button>
      </div>
    )
  }

  return (
    <section className="resonance-collections" aria-labelledby="collections-title">
      <h2 id="collections-title">他们的故事</h2>
      {items.length === 0 ? (
        <p className="resonance-collections-empty">别人发给你看的故事会出现在这里</p>
      ) : (
        <ul className="resonance-collection-list">
          {items.map(item => {
            const cover = item.latest_work?.assets.find(
              asset => asset.asset_type === 'image' && asset.url,
            )
            return (
              <li key={item.owner.id}>
                <button
                  type="button"
                  className="resonance-collection-card"
                  onClick={() => onOpenOwner(item.owner.id)}
                  aria-label={`${item.owner.nickname}的故事`}
                >
                  <span className="resonance-collection-card-head">
                    <ProfileAvatar nickname={item.owner.nickname} url={item.owner.avatar_url} />
                    <span className="resonance-collection-main">
                      <strong>{item.owner.nickname}的故事</strong>
                      {item.latest_work && (
                        <span className="resonance-collection-style">
                          · {formatStyle(item.latest_work.style, item.owner.nickname)}
                        </span>
                      )}
                    </span>
                    <ChevronRight />
                  </span>
                  {cover?.url && (
                    <img className="resonance-collection-cover" src={cover.url} alt="" />
                  )}
                  {item.latest_work && (
                    <span className="resonance-collection-title">{item.latest_work.title}</span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
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
    </section>
  )
}
