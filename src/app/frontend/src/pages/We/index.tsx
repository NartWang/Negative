import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { roomsApi } from '../../api/client'
import RoomPost from '../../components/RoomPost'
import RoomTemperature from '../../components/RoomTemperature'
import { useAuth } from '../../contexts/AuthContext'
import { useRoom } from '../../contexts/RoomContext'
import type { RoomPost as RoomPostType, RoomTemperatures } from '../../types'
import './style.css'

interface WeProps {
  currentDate?: string
  onOpenDiary?: (date: string) => void
}

function localDate(): string {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

const EMPTY_TEMPERATURES: RoomTemperatures = {
  own: { status: 'unavailable' },
  partner: { status: 'unavailable' },
}

export default function We({ currentDate = localDate(), onOpenDiary }: WeProps) {
  const { user } = useAuth()
  const { room } = useRoom()
  const [posts, setPosts] = useState<RoomPostType[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [olderBusy, setOlderBusy] = useState(false)
  const [olderError, setOlderError] = useState<string | null>(null)
  const [feedState, setFeedState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [note, setNote] = useState('')
  const [noteBusy, setNoteBusy] = useState(false)
  const [noteError, setNoteError] = useState<string | null>(null)
  const [temperatures, setTemperatures] = useState<RoomTemperatures>(EMPTY_TEMPERATURES)
  const [temperatureState, setTemperatureState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [temperatureSubject, setTemperatureSubject] = useState<'own' | 'partner'>('own')
  const [temperatureBusy, setTemperatureBusy] = useState(false)
  const [temperatureError, setTemperatureError] = useState<string | null>(null)
  const feedGenerationRef = useRef(0)

  const roomId = room?.id
  const partnerName = room?.partner?.nickname ?? '对方'

  const loadFeed = useCallback(async () => {
    if (!roomId) return
    const generation = feedGenerationRef.current + 1
    feedGenerationRef.current = generation
    setOlderBusy(false)
    setOlderError(null)
    setFeedState('loading')
    try {
      const result = await roomsApi.feed(roomId)
      if (feedGenerationRef.current !== generation) return
      setPosts(result.items)
      setNextCursor(result.next_cursor)
      setOlderError(null)
      setFeedState('ready')
    } catch {
      if (feedGenerationRef.current === generation) setFeedState('error')
    }
  }, [roomId])

  const loadTemperatures = useCallback(async () => {
    if (!roomId) return
    setTemperatureState('loading')
    setTemperatureError(null)
    try {
      const result = await roomsApi.temperatures(roomId, currentDate)
      setTemperatures(result)
      setTemperatureState('ready')
    } catch {
      setTemperatureState('error')
    }
  }, [roomId, currentDate])

  useEffect(() => {
    void loadFeed()
    void loadTemperatures()
  }, [loadFeed, loadTemperatures])

  if (!user || !roomId || !room?.partner) return null

  const publishNote = async (event: FormEvent) => {
    event.preventDefault()
    const submittedValue = note
    const body = note.trim()
    if (!body || noteBusy) return
    setNoteBusy(true)
    setNoteError(null)
    try {
      const created = await roomsApi.createNote(roomId, body)
      setPosts(current => [created, ...current.filter(item => item.id !== created.id)])
      setNote(current => current === submittedValue ? '' : current)
      setFeedState('ready')
    } catch {
      setNoteError('这条动态暂时没有发出，内容已为你保留')
    } finally {
      setNoteBusy(false)
    }
  }

  const toggleLike = async (post: RoomPostType) => {
    const result = post.liked_by_me
      ? await roomsApi.unlikePost(roomId, post.id)
      : await roomsApi.likePost(roomId, post.id)
    setPosts(current => current.map(item => item.id === post.id
      ? { ...item, liked_by_me: result.liked, like_count: result.like_count }
      : item))
  }

  const addComment = async (postId: string, body: string, requestId: string) => {
    const created = await roomsApi.createComment(roomId, postId, {
      client_request_id: requestId,
      body,
    })
    setPosts(current => current.map(item => {
      if (item.id !== postId || item.comments.some(comment => comment.id === created.id)) return item
      return {
        ...item,
        comments: [...item.comments, created],
        comment_count: item.comment_count + 1,
      }
    }))
  }

  const withdrawPost = async (postId: string) => {
    await roomsApi.withdrawPost(roomId, postId)
    setPosts(current => current.filter(item => item.id !== postId))
  }

  const loadOlder = async () => {
    if (!nextCursor || olderBusy) return
    const generation = feedGenerationRef.current
    const cursor = nextCursor
    setOlderBusy(true)
    setOlderError(null)
    try {
      const result = await roomsApi.feed(roomId, cursor)
      if (feedGenerationRef.current !== generation) return
      setPosts(current => {
        const existing = new Set(current.map(item => item.id))
        return [...current, ...result.items.filter(item => !existing.has(item.id))]
      })
      setNextCursor(result.next_cursor)
    } catch {
      if (feedGenerationRef.current === generation) {
        setOlderError('较早的动态暂时没有加载出来')
      }
    } finally {
      if (feedGenerationRef.current === generation) setOlderBusy(false)
    }
  }

  const publishTemperature = async () => {
    if (temperatureBusy) return
    setTemperatureBusy(true)
    setTemperatureError(null)
    try {
      const snapshot = await roomsApi.publishTemperature(roomId, currentDate)
      setTemperatures(current => ({ ...current, own: { status: 'available', snapshot } }))
    } catch {
      setTemperatureError('今天的温度暂时无法发布')
    } finally {
      setTemperatureBusy(false)
    }
  }

  const revokeTemperature = async () => {
    if (temperatureBusy) return
    setTemperatureBusy(true)
    setTemperatureError(null)
    try {
      await roomsApi.revokeTemperature(roomId, currentDate)
      setTemperatures(current => ({ ...current, own: { status: 'unavailable' } }))
    } catch {
      setTemperatureError('暂时无法撤回温度')
    } finally {
      setTemperatureBusy(false)
    }
  }

  return (
    <main className="we-page">
      <header className="we-header">
        <div>
          <p className="we-kicker">只属于两个人的房间</p>
          <h1 style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{user.nickname}<span>与</span>{partnerName}</h1>
        </div>
        <span className="we-room-mark" aria-hidden="true">我们</span>
      </header>

      <form className="we-composer" onSubmit={publishNote}>
        <div className="we-composer-title">
          <div>
            <p>此刻想说</p>
            <strong style={{ minWidth: 0, overflowWrap: 'anywhere' }}>由 {user.nickname} 发布</strong>
          </div>
          <span>对方可见</span>
        </div>
        <label className="visually-hidden" htmlFor="room-note">写一条共享动态</label>
        <textarea
          id="room-note"
          rows={3}
          maxLength={10_000}
          value={note}
          placeholder={`写给${partnerName}，或记下这一刻…`}
          onChange={event => setNote(event.target.value)}
        />
        <div className="we-composer-footer">
          <small>仅发布这里写下的内容，不会自动分享私人记录</small>
          <button type="submit" disabled={!note.trim() || noteBusy}>
            {noteBusy ? '发布中…' : '发布到我们'}
          </button>
        </div>
        {noteError && <p className="we-inline-error" role="alert">{noteError}</p>}
      </form>

      <div className="we-temperature-wrap">
        {temperatureState === 'loading' && <p className="we-quiet-status" role="status">正在读取今天的温度…</p>}
        {temperatureState === 'error' && (
          <div className="we-quiet-status" role="alert">
            <span>暂时没有读到温度</span>
            <button type="button" onClick={() => void loadTemperatures()}>重试</button>
          </div>
        )}
        {temperatureState === 'ready' && (
          <RoomTemperature
            temperatures={temperatures}
            subject={temperatureSubject}
            partnerName={partnerName}
            busy={temperatureBusy}
            onSubjectChange={setTemperatureSubject}
            onPublish={publishTemperature}
            onRevoke={revokeTemperature}
          />
        )}
        {temperatureError && <p className="we-inline-error" role="alert">{temperatureError}</p>}
      </div>

      <section className="we-feed" aria-labelledby="we-feed-title">
        <div className="we-feed-heading">
          <div>
            <p>共同发生</p>
            <h2 id="we-feed-title">我们的动态</h2>
          </div>
          <div className="we-feed-tools">
            <span>{posts.length > 0 ? `${posts.length} 则` : '从此刻开始'}</span>
            <button
              type="button"
              aria-label="刷新动态"
              disabled={feedState === 'loading'}
              onClick={() => void loadFeed()}
            >{feedState === 'loading' ? '刷新中' : '刷新'}</button>
          </div>
        </div>

        {feedState === 'loading' && <p className="we-feed-state" role="status">正在展开你们的动态…</p>}
        {feedState === 'error' && (
          <div className="we-feed-state error" role="alert">
            <strong>暂时没有读到共享动态</strong>
            <span>私人记录没有受到影响。</span>
            <button type="button" onClick={() => void loadFeed()}>重新读取动态</button>
          </div>
        )}
        {feedState === 'ready' && posts.length === 0 && (
          <div className="we-feed-state empty">
            <span className="empty-mark" aria-hidden="true">两人帖</span>
            <strong>这里还很安静</strong>
            <p>发一条文字，或之后从日记和漫画中主动分享。</p>
          </div>
        )}
        {feedState === 'ready' && posts.map(post => (
          <RoomPost
            key={post.id}
            post={post}
            onLike={toggleLike}
            onComment={addComment}
            onWithdraw={withdrawPost}
            onOpenDiary={onOpenDiary}
          />
        ))}
        {feedState === 'ready' && nextCursor && (
          <button className="we-load-older" type="button" disabled={olderBusy} onClick={() => void loadOlder()}>
            {olderBusy ? '正在加载…' : '加载更早动态'}
          </button>
        )}
        {olderError && <p className="we-inline-error" role="alert">{olderError}</p>}
      </section>
    </main>
  )
}
