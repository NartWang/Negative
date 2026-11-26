import { useState } from 'react'
import { storyApi } from '../../api/client'
import type { ResonanceFeedItem, WorkComment } from '../../types'
import { Send } from '../../components/Icon'

interface Props {
  item: ResonanceFeedItem
  onWorkGone: () => void
}

function newRequestId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export default function InlineComments({ item, onWorkGone }: Props) {
  const [comments, setComments] = useState<WorkComment[]>(item.comments)
  const [draft, setDraft] = useState('')
  const [requestId, setRequestId] = useState(newRequestId)
  const [replyTo, setReplyTo] = useState<WorkComment | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async () => {
    const body = draft.trim()
    if (!body || sending) return
    if (item.mine && !replyTo) {
      setError('先选择一条评论回复')
      return
    }
    setSending(true)
    setError(null)
    try {
      const comment = await storyApi.addComment(item.id, {
        client_request_id: requestId,
        body,
        viewer_user_id: item.mine ? replyTo?.viewer_user_id ?? null : null,
      })
      setComments(current =>
        current.some(existing => existing.id === comment.id)
          ? current
          : [...current, comment],
      )
      setDraft('')
      setRequestId(newRequestId())
      setReplyTo(null)
    } catch (err) {
      if (err instanceof Error && 'status' in err && (err as { status: number }).status === 404) {
        onWorkGone()
        return
      }
      // keep draft + requestId so a retry does not duplicate
      setError('评论没发出去，请重试')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="resonance-comments">
      {comments.length > 0 && (
        <ul className="resonance-comment-list">
          {comments.map(comment => (
            <li key={comment.id}>
              <span className="resonance-comment-author">
                {comment.author.id === item.owner.id && item.mine
                  ? '我'
                  : comment.author.nickname}
              </span>
              {comment.author_user_id !== comment.viewer_user_id && (
                <span className="resonance-comment-reply"> 回复 {comment.viewer.nickname}</span>
              )}
              <span className="resonance-comment-body">：{comment.body}</span>
              {item.mine && comment.author_user_id !== item.owner.id && (
                <button
                  type="button"
                  className="resonance-comment-reply-button"
                  onClick={() => setReplyTo(comment)}
                >
                  回复
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="resonance-composer">
        {replyTo && (
          <span className="resonance-composer-reply">
            回复 {replyTo.author.nickname}
            <button type="button" aria-label="取消回复" onClick={() => setReplyTo(null)}>×</button>
          </span>
        )}
        <div className="resonance-composer-row">
          <input
            value={draft}
            aria-label={item.mine ? '回复评论' : '评论'}
            placeholder={item.mine ? '回复…' : '评论…'}
            onChange={event => setDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') void send()
            }}
          />
          <button
            type="button"
            aria-label="发送评论"
            disabled={!draft.trim() || sending || (item.mine && !replyTo)}
            onClick={() => void send()}
          >
            <Send />
          </button>
        </div>
        {error && <span className="resonance-inline-error" role="alert">{error}</span>}
      </div>
    </div>
  )
}
