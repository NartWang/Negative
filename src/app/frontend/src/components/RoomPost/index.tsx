import { useRef, useState, type FormEvent } from 'react'
import type { RoomPost as RoomPostType } from '../../types'
import './style.css'

interface RoomPostProps {
  post: RoomPostType
  onLike: (post: RoomPostType) => Promise<void>
  onComment: (postId: string, body: string, requestId: string) => Promise<void>
  onWithdraw: (postId: string) => Promise<void>
  onOpenDiary?: (date: string) => void
}

function displayDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function requestId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `comment-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function preview(post: RoomPostType): string {
  if (post.snapshot.type === 'note') return post.snapshot.body.slice(0, 12)
  if (post.snapshot.type === 'diary') return post.snapshot.text.slice(0, 12) || '日记'
  return post.snapshot.caption?.slice(0, 12) || '周记漫画'
}

function PostBody({ post }: { post: RoomPostType }) {
  const snapshot = post.snapshot
  if (snapshot.type === 'note') {
    return <p className="room-post-note">{snapshot.body}</p>
  }
  if (snapshot.type === 'diary') {
    return (
      <div className="room-post-diary">
        <p className="room-post-eyebrow">{snapshot.date} · 日记</p>
        <p>{snapshot.text}</p>
        {snapshot.images.length > 0 && (
          <div className={`room-post-gallery room-post-gallery-${Math.min(snapshot.images.length, 3)}`}>
            {snapshot.images.map((image, index) => (
              <img key={`${image.url}-${index}`} src={image.url} alt={`日记配图 ${index + 1}`} loading="lazy" />
            ))}
          </div>
        )}
      </div>
    )
  }
  return (
    <div className="room-post-comic">
      <p className="room-post-eyebrow">{snapshot.week_start} — {snapshot.week_end} · 漫画周记</p>
      <img src={snapshot.image_url} alt="分享的漫画周记" loading="lazy" />
      {snapshot.caption && <p>{snapshot.caption}</p>}
    </div>
  )
}

export default function RoomPost({
  post, onLike, onComment, onWithdraw, onOpenDiary,
}: RoomPostProps) {
  const ownDiaryDate = post.mine && post.snapshot.type === 'diary'
    ? post.snapshot.date
    : null
  const [comment, setComment] = useState('')
  const [likeBusy, setLikeBusy] = useState(false)
  const [commentBusy, setCommentBusy] = useState(false)
  const [withdrawBusy, setWithdrawBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pendingComment = useRef<{ body: string; id: string } | null>(null)

  const toggleLike = async () => {
    if (likeBusy) return
    setLikeBusy(true)
    setError(null)
    try { await onLike(post) }
    catch { setError('点赞没有成功，请再试一次') }
    finally { setLikeBusy(false) }
  }

  const submitComment = async (event: FormEvent) => {
    event.preventDefault()
    const submittedValue = comment
    const body = comment.trim()
    if (!body || commentBusy) return
    if (!pendingComment.current || pendingComment.current.body !== body) {
      pendingComment.current = { body, id: requestId() }
    }
    setCommentBusy(true)
    setError(null)
    try {
      await onComment(post.id, body, pendingComment.current.id)
      pendingComment.current = null
      setComment(current => current === submittedValue ? '' : current)
    } catch {
      setError('评论没有发出，内容已为你保留')
    } finally {
      setCommentBusy(false)
    }
  }

  const withdraw = async () => {
    if (withdrawBusy) return
    setWithdrawBusy(true)
    setError(null)
    try { await onWithdraw(post.id) }
    catch {
      setError('暂时无法撤回这条动态')
      setWithdrawBusy(false)
    }
  }

  return (
    <article className={`room-post ${post.mine ? 'room-post-mine' : 'room-post-partner'}`}>
      <header className="room-post-header">
        <span className="room-post-avatar" aria-hidden="true">
          {post.author.avatar_url
            ? <img src={post.author.avatar_url} alt="" />
            : post.author.nickname.slice(0, 1)}
        </span>
        <div>
          <strong style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{post.author.nickname}</strong>
          <time dateTime={post.published_at}>{displayDate(post.published_at)}</time>
        </div>
        <span className="room-post-owner">{post.mine ? '我分享的' : '对方分享的'}</span>
      </header>

      <PostBody post={post} />

      <div className="room-post-actions" aria-label="动态操作">
        <button
          type="button"
          className={post.liked_by_me ? 'room-action liked' : 'room-action'}
          aria-label={post.liked_by_me ? '取消赞' : '赞'}
          aria-pressed={post.liked_by_me}
          disabled={likeBusy}
          onClick={toggleLike}
        >
          <span aria-hidden="true">{post.liked_by_me ? '♥' : '♡'} 赞 {post.like_count || ''}</span>
        </button>
        {post.source_type === 'diary' && ownDiaryDate && onOpenDiary && (
          <button type="button" className="room-action" onClick={() => onOpenDiary(ownDiaryDate)}>
            查看我的原记录
          </button>
        )}
        {post.mine && (
          <button type="button" className="room-action room-action-danger" disabled={withdrawBusy} onClick={withdraw}>
            {withdrawBusy ? '撤回中…' : '撤回'}
          </button>
        )}
      </div>

      {post.comments.length > 0 && (
        <ol className="room-comments" aria-label="评论">
          {post.comments.map(item => (
            <li key={item.id}>
              <strong>{item.author.nickname}</strong>
              <span>{item.body}</span>
            </li>
          ))}
        </ol>
      )}
      {post.comments_truncated && (
        <p className="room-comments-more">另有 {post.comment_count - post.comments.length} 条较早评论</p>
      )}

      <form className="room-comment-form" onSubmit={submitComment}>
        <label className="visually-hidden" htmlFor={`comment-${post.id}`}>评论{preview(post)}</label>
        <input
          id={`comment-${post.id}`}
          value={comment}
          maxLength={2000}
          placeholder="回应这一刻…"
          onChange={event => setComment(event.target.value)}
        />
        <button type="submit" disabled={!comment.trim() || commentBusy}>
          {commentBusy ? '发送中' : '发送评论'}
        </button>
      </form>
      {error && <p className="room-post-error" role="alert">{error}</p>}
    </article>
  )
}
