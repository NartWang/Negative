import { useState } from 'react'
import { storyApi } from '../../api/client'
import type { ResonanceFeedItem } from '../../types'
import InlineComments from './InlineComments'
import VisibilitySheet from '../../components/VisibilitySheet'
import { Heart, MoreHorizontal } from '../../components/Icon'
import PostMenu from './PostMenu'

interface Props {
  item: ResonanceFeedItem
  onOpenOwnStoryWork: (workId: number) => void
  onOpenPublishedDetail: (workId: number) => void
  onRemove: (workId: number, message?: string) => void
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function formatStyle(style: string): string {
  const normalized = style.trim().toLowerCase()
  const labels: Record<string, string> = {
    crayon: '蜡笔风',
    '蜡笔': '蜡笔风',
    watercolor: '水彩风',
    '水彩': '水彩风',
    sketch: '素描风',
    pencil: '素描风',
    '素描': '素描风',
    pixel: '像素风',
    'pixel-art': '像素风',
    '像素': '像素风',
  }
  return labels[normalized] ?? (style.endsWith('风') ? style : `${style}风`)
}

function Avatar({ nickname, url }: { nickname: string; url: string | null }) {
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

export default function PostCard({
  item,
  onOpenOwnStoryWork,
  onOpenPublishedDetail,
  onRemove,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [visibilityOpen, setVisibilityOpen] = useState(false)
  const [liking, setLiking] = useState(false)
  const [likedByMe, setLikedByMe] = useState(item.mine ? false : item.liked_by_me)
  const [likeError, setLikeError] = useState<string | null>(null)
  const [imageBroken, setImageBroken] = useState(false)

  const openCard = () => {
    if (item.mine) onOpenOwnStoryWork(item.id)
    else onOpenPublishedDetail(item.id)
  }

  const toggleLike = async () => {
    if (item.mine || liking) return
    const next = !likedByMe
    setLikedByMe(next)
    setLiking(true)
    setLikeError(null)
    try {
      if (next) await storyApi.like(item.id)
      else await storyApi.unlike(item.id)
    } catch (err) {
      setLikedByMe(!next)
      if (err instanceof Error && 'status' in err && (err as { status: number }).status === 404) {
        onRemove(item.id, '这个故事已不可见')
        return
      }
      setLikeError('点赞没成功，请重试')
    } finally {
      setLiking(false)
    }
  }

  const text = item.assets.find(asset => asset.asset_type === 'text' && asset.text)
  const image = item.assets.find(asset => asset.asset_type === 'image' && asset.url)

  return (
    <article
      className="resonance-card"
      aria-label={`${item.owner.nickname}的故事`}
      data-resonance-work-id={item.id}
      tabIndex={-1}
    >
      <header className="resonance-card-head">
        <Avatar nickname={item.owner.nickname} url={item.owner.avatar_url} />
        <div className="resonance-card-meta">
          <span className="resonance-card-author">{item.mine ? '我' : item.owner.nickname}</span>
          <time dateTime={item.published_at}>{formatTime(item.published_at)}</time>
        </div>
        {item.mine && (
          <button
            type="button"
            className="resonance-card-menu"
            aria-label="更多操作"
            onClick={() => setMenuOpen(true)}
          >
            <MoreHorizontal />
          </button>
        )}
      </header>

      <button type="button" className="resonance-card-body" onClick={openCard}>
        <h3>{item.title}</h3>
        {image?.url && !imageBroken && (
          <img
            className="resonance-card-image"
            src={image.url}
            alt={item.title}
            onError={() => setImageBroken(true)}
          />
        )}
        {image?.url && imageBroken && (
          <span className="resonance-media-placeholder">图片暂时加载不出来</span>
        )}
        {text?.text && <p className="resonance-card-text">{text.text}</p>}
        {item.style && (
          <span className="resonance-card-style">风格 · {formatStyle(item.style)}</span>
        )}
      </button>

      <footer className="resonance-card-foot">
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
        {likeError && <span className="resonance-inline-error" role="alert">{likeError}</span>}
      </footer>

      <InlineComments item={item} onWorkGone={() => onRemove(item.id, '这个故事已不可见')} />

      {item.mine && (
        <>
          <PostMenu
            open={menuOpen}
            work={item}
            onClose={() => setMenuOpen(false)}
            onVisibility={() => { setMenuOpen(false); setVisibilityOpen(true) }}
            onUnpublished={() => { setMenuOpen(false); onRemove(item.id) }}
          />
          <VisibilitySheet
            open={visibilityOpen}
            work={{
              id: item.id,
              owner_user_id: item.owner.id,
              source_diary_id: null,
              title: item.title,
              medium: item.medium,
              narrative_mode: item.narrative_mode,
              style: item.style,
              selected_segments: [],
              forbidden_content: null,
              status: 'published',
              assets: [],
              created_at: item.published_at,
              updated_at: item.published_at,
            }}
            onClose={() => setVisibilityOpen(false)}
          />
        </>
      )}
    </article>
  )
}
