import { useCallback, useEffect, useState } from 'react'
import { ApiError, storyApi } from '../../api/client'
import type { PublishedStoryAsset, PublishedStoryDetail as Detail } from '../../types'
import InlineComments from './InlineComments'
import { ArrowLeft, Heart } from '../../components/Icon'

interface Props {
  workId: number
  onBack: () => void
  onWorkGone: () => void
}

function DetailAvatar({ nickname, url }: { nickname: string; url: string | null }) {
  const [broken, setBroken] = useState(false)
  if (url && !broken) {
    return (
      <img
        className="resonance-avatar"
        src={url}
        alt={nickname}
        onError={() => setBroken(true)}
      />
    )
  }
  return (
    <span className="resonance-avatar resonance-avatar-fallback" aria-hidden="true">
      {nickname.slice(0, 1) || '故'}
    </span>
  )
}

function DetailAsset({ asset, title }: { asset: PublishedStoryAsset; title: string }) {
  const [broken, setBroken] = useState(false)
  if (asset.asset_type === 'text' && asset.text) {
    return <p className="resonance-detail-text">{asset.text}</p>
  }
  if (!asset.url) return null
  if (broken) {
    return <span className="resonance-media-placeholder">媒体暂时加载不出来</span>
  }
  return <img src={asset.url} alt={title} onError={() => setBroken(true)} />
}

export default function PublishedStoryDetail({ workId, onBack, onWorkGone }: Props) {
  const [item, setItem] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [likedByMe, setLikedByMe] = useState(false)
  const [liking, setLiking] = useState(false)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    storyApi.publishedWork(workId)
      .then(result => {
        if (cancelled) return
        setItem(result)
        setLikedByMe(result.mine ? false : result.liked_by_me)
      })
      .catch(err => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          onWorkGone()
          return
        }
        setError('这个故事暂时打不开')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [workId, onWorkGone])

  useEffect(() => load(), [load])

  const toggleLike = async () => {
    if (!item || item.mine || liking) return
    const next = !likedByMe
    setLikedByMe(next)
    setLiking(true)
    try {
      if (next) await storyApi.like(item.id)
      else await storyApi.unlike(item.id)
    } catch (err) {
      setLikedByMe(!next)
      if (err instanceof ApiError && err.status === 404) onWorkGone()
    } finally {
      setLiking(false)
    }
  }

  if (loading) {
    return (
      <main className="resonance-detail">
        <button type="button" className="resonance-back" onClick={onBack} aria-label="返回回响">
          <ArrowLeft />
        </button>
        <div className="resonance-state" role="status">正在读取故事…</div>
      </main>
    )
  }
  if (error || !item) {
    return (
      <main className="resonance-detail">
        <button type="button" className="resonance-back" onClick={onBack} aria-label="返回回响">
          <ArrowLeft />
        </button>
        <div className="resonance-state" role="alert">
          <p>{error ?? '这个故事已不可见'}</p>
          {error && <button type="button" onClick={load}>重试</button>}
          <button type="button" onClick={onBack}>回到回响</button>
        </div>
      </main>
    )
  }

  return (
    <main className="resonance-detail">
      <header className="resonance-detail-head">
        <button type="button" className="resonance-back" onClick={onBack} aria-label="返回回响">
          <ArrowLeft />
        </button>
        <DetailAvatar nickname={item.owner.nickname} url={item.owner.avatar_url} />
        <div className="resonance-detail-meta">
          <span>{item.mine ? '我' : item.owner.nickname}</span>
          <time dateTime={item.published_at}>
            {new Date(item.published_at).toLocaleDateString('zh-CN')}
          </time>
        </div>
      </header>
      <h1>{item.title}</h1>
      <div className="resonance-detail-assets">
        {item.assets.map(asset => (
          <DetailAsset key={asset.id} asset={asset} title={item.title} />
        ))}
      </div>
      {!item.mine && (
        <button
          type="button"
          className={`resonance-like ${likedByMe ? 'liked' : ''}`}
          aria-pressed={likedByMe}
          aria-label={likedByMe ? '取消赞' : '点赞'}
          disabled={liking}
          onClick={toggleLike}
        >
          <Heart />
          {likedByMe ? '已赞' : '点赞'}
        </button>
      )}
      {item.mine && item.likes.length > 0 && (
        <span className="resonance-likes">
          点赞：{item.likes.map(person => person.nickname).join('、')}
        </span>
      )}
      <InlineComments item={item} onWorkGone={onWorkGone} />
    </main>
  )
}
