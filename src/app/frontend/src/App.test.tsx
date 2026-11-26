import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import { RoomProvider, useRoom } from './contexts/RoomContext'
import type { CompletedPicturebook, StoryChapter, StoryDayDetail, WeeklyComic } from './types'

type Profile = {
  id: number
  nickname: string
  avatar_url: string | null
  signature: string | null
  created_at: string
}

type Room = {
  id: string
  status: 'active'
  state: 'waiting' | 'paired'
  waiting: boolean
  created_at: string
  members: Array<{
    id: number
    nickname: string
    avatar_url: string | null
    role: 'owner' | 'member'
    slot: 1 | 2
  }>
  partner: null | {
    id: number
    nickname: string
    avatar_url: string | null
    role: 'owner' | 'member'
    slot: 1 | 2
  }
}

type DiaryListItem = {
  id: number
  date: string
  text: string
  draft_text?: string
  status: 'draft' | 'confirmed'
  source: 'manual' | 'ai' | 'hybrid'
  images: Array<{ id: number; url: string; kept: 0 | 1 }>
}

type ScheduleListItem = {
  id: number
  date: string
  time: string | null
  title: string
  completed: boolean
  feeling: string | null
  created_at: string
}

type FragmentListItem = {
  id: number
  date: string
  content: string | null
  photo_url: string | null
  photo_asset_id?: string | null
  photo_description: string | null
  mood_tag: string | null
  record_time: string | null
  created_at: string
}

type StoryWorkItem = {
  id: number
  owner_user_id: number
  source_diary_id: number
  title: string
  medium: 'picture_book' | 'comic' | 'motion_comic' | 'weekly'
  narrative_mode: string
  style: string
  selected_segments: string[]
  forbidden_content: string | null
  status: 'draft' | 'ready' | 'published' | 'failed'
  assets: Array<{ id: number; asset_type: 'text' | 'image' | 'video'; text: string | null; url: string | null }>
  created_at: string
  updated_at: string
}

type ResonanceFeedItem = {
  id: number
  title: string
  medium: 'picture_book' | 'comic' | 'motion_comic' | 'weekly'
  narrative_mode: string
  style: string
  published_at: string
  mine: boolean
  owner: { id: number; nickname: string; avatar_url: string | null }
  assets: Array<{ id: number; asset_type: 'text' | 'image' | 'video'; text: string | null; url: string | null }>
  comments: unknown[]
  liked_by_me?: boolean
  likes?: unknown[]
  audience_count?: number
}

const me: Profile = {
  id: 7,
  nickname: '小满',
  avatar_url: null,
  signature: '',
  created_at: '2026-08-03T08:00:00+00:00',
}

const waitingRoom: Room = {
  id: '1e3a1a7a-45ba-4c89-b57e-73fb7cae37b8',
  status: 'active',
  state: 'waiting',
  waiting: true,
  created_at: '2026-08-03T08:01:00+00:00',
  members: [{
    id: me.id,
    nickname: me.nickname,
    avatar_url: null,
    role: 'owner',
    slot: 1,
  }],
  partner: null,
}

const pairedRoom: Room = {
  ...waitingRoom,
  state: 'paired',
  waiting: false,
  members: [
    waitingRoom.members[0],
    { id: 9, nickname: '阿禾', avatar_url: null, role: 'member', slot: 2 },
  ],
  partner: { id: 9, nickname: '阿禾', avatar_url: null, role: 'member', slot: 2 },
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function emptyResponse(status = 204): Response {
  return new Response(null, { status })
}

function pathOf(input: RequestInfo | URL): string {
  if (input instanceof Request) return new URL(input.url, window.location.origin).pathname
  return new URL(String(input), window.location.origin).pathname
}

function methodOf(input: RequestInfo | URL, init?: RequestInit): string {
  if (input instanceof Request) return input.method.toUpperCase()
  return (init?.method ?? 'GET').toUpperCase()
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function installFetch(options: {
  profile?: Profile
  room?: Room | null
  registerProfile?: Profile
  createdRoom?: Room
  joinedRoom?: Room
  loginFailure?: boolean
  roomFailure?: boolean
  roomSessionExpires?: boolean
  publicationsSessionExpired?: boolean
  publicationFailureOnce?: boolean
  logoutSessionExpired?: boolean
  exportSessionExpired?: boolean
  storyChaptersSessionExpired?: boolean
  schedules?: ScheduleListItem[]
  fragments?: FragmentListItem[]
  diaries?: DiaryListItem[]
  notebookIndex?: { items: Array<{ diary_id: number; date: string }>; total: number }
  notebookDetails?: Record<number, DiaryListItem>
  storyWorks?: StoryWorkItem[]
  storyChapters?: StoryChapter[]
  storyDayDetails?: Record<string, StoryDayDetail>
  diaryGetResponse?: Promise<Response>
  storyDraftCount?: number
  picturebooks?: CompletedPicturebook[]
  weeklyComics?: WeeklyComic[]
  publications?: ResonanceFeedItem[]
  filmPicturebooks?: unknown
  filmMotionComics?: unknown
  filmPicturebookDetails?: Record<string, unknown>
  filmMotionComicDetails?: Record<number, unknown>
  unfinishedPicturebooks?: unknown[]
  unfinishedMotionComics?: unknown[]
  picturebookRetry?: (jobId: number) => Response
  videoRetry?: (videoJobId: number) => Response
} = {}) {
  let room = options.room ?? null
  const schedules = options.schedules ?? []
  const fragments = options.fragments ?? []
  let diaries = options.diaries ?? []
  let storyWorks = options.storyWorks ?? []
  const storyChapters = options.storyChapters ?? []
  const storyDayDetails = options.storyDayDetails ?? {}
  const storyDraftCount = options.storyDraftCount ?? diaries.filter(item =>
    item.status === 'draft' && (item.draft_text || item.text).trim()
  ).length
  const publications = options.publications ?? []
  let roomReads = 0
  let publicationReads = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(input)
    const method = methodOf(input, init)

    if (path === '/api/me' && method === 'GET') {
      return options.profile
        ? jsonResponse(options.profile)
        : jsonResponse({ detail: 'authentication required' }, 401)
    }
    if (path === '/api/auth/register' && method === 'POST') {
      return jsonResponse(options.registerProfile ?? me, 201)
    }
    if (path === '/api/auth/login' && method === 'POST') {
      return options.loginFailure
        ? jsonResponse({ detail: 'invalid credentials' }, 401)
        : jsonResponse(options.profile ?? me)
    }
    if (path === '/api/auth/session' && method === 'DELETE') {
      if (options.logoutSessionExpired) {
        return jsonResponse({ detail: 'authentication required' }, 401)
      }
      return emptyResponse()
    }
    if (path === '/api/rooms/current' && method === 'GET') {
      roomReads += 1
      if (options.roomSessionExpires && roomReads > 1) {
        return jsonResponse({ detail: 'authentication required' }, 401)
      }
      if (options.roomFailure) {
        return jsonResponse({ detail: 'room service unavailable' }, 503)
      }
      return jsonResponse(room)
    }
    if (path === `/api/rooms/${waitingRoom.id}/feed` && method === 'GET') {
      return jsonResponse({ items: [], next_cursor: null })
    }
    if (path === `/api/rooms/${waitingRoom.id}/temperatures` && method === 'GET') {
      return jsonResponse({
        own: { status: 'unavailable' },
        partner: { status: 'unavailable' },
      })
    }
    if (path === '/api/rooms' && method === 'POST') {
      room = options.createdRoom ?? waitingRoom
      return jsonResponse(room, 201)
    }
    if (path === `/api/rooms/${waitingRoom.id}/invites` && method === 'POST') {
      return jsonResponse({
        code: 'ABCD-EFGH-JKMP-QRST',
        expires_at: '2026-08-04T08:01:00+00:00',
      }, 201)
    }
    if (path === '/api/room-invites/join' && method === 'POST') {
      room = options.joinedRoom ?? pairedRoom
      return jsonResponse(room)
    }
    if (path === `/api/rooms/${waitingRoom.id}/leave` && method === 'POST') {
      room = null
      return emptyResponse()
    }
    if (path === '/api/schedules' && method === 'GET') return jsonResponse(schedules)
    if (path === '/api/fragments' && method === 'GET') return jsonResponse(fragments)
    if (path === '/api/streaks' && method === 'GET') {
      return jsonResponse({ current_streak: 0, calendar_data: {} })
    }
    if (path === '/api/thermometer' && method === 'GET') {
      return jsonResponse({
        score: 0,
        label: '凉',
        color: '#9CC5E0',
        comment: '还没有足够记录',
        quant_score: 0,
        ai_score: 0,
        inputs: {
          fragments_count: 0,
          schedules_total: 0,
          schedules_completed: 0,
          consecutive_days: 0,
        },
      })
    }
    if (path === '/api/diary' && method === 'GET') {
      if (options.diaryGetResponse) return options.diaryGetResponse
      return jsonResponse(null)
    }
    if (path === '/api/diary' && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}'))
      const created: DiaryListItem = {
        id: 800 + diaries.length,
        date: body.date,
        text: '',
        draft_text: '',
        status: 'draft',
        source: 'manual',
        images: [],
      }
      diaries = [created, ...diaries]
      return jsonResponse(created, 201)
    }
    if (path === '/api/diary/list' && method === 'GET') return jsonResponse(diaries)
    if (path === '/api/diary/notebook/index' && method === 'GET') {
      return jsonResponse(options.notebookIndex ?? { items: [], total: 0 })
    }
    const notebookDetailMatch = path.match(/^\/api\/diary\/notebook\/(\d+)$/)
    if (notebookDetailMatch && method === 'GET') {
      const id = Number(notebookDetailMatch[1])
      const detail = options.notebookDetails?.[id]
      return detail
        ? jsonResponse(detail)
        : jsonResponse({ detail: 'notebook diary not found' }, 404)
    }
    const diaryAiFillMatch = path.match(/^\/api\/diary\/(\d+)\/ai-fill$/)
    if (diaryAiFillMatch && method === 'POST') {
      const id = Number(diaryAiFillMatch[1])
      const existing = diaries.find(item => item.id === id)
      const updated: DiaryListItem = {
        id,
        date: existing?.date ?? '2026-08-08',
        text: 'AI 生成的日记',
        draft_text: 'AI 生成的日记',
        status: existing?.status ?? 'draft',
        source: 'ai',
        images: existing?.images ?? [],
      }
      diaries = diaries.some(item => item.id === id)
        ? diaries.map(item => item.id === id ? updated : item)
        : [updated, ...diaries]
      return jsonResponse(updated)
    }
    const diaryPathMatch = path.match(/^\/api\/diary\/(\d+)$/)
    if (diaryPathMatch && method === 'PUT') {
      const id = Number(diaryPathMatch[1])
      const body = JSON.parse(String(init?.body ?? '{}'))
      const existing = diaries.find(item => item.id === id)
      const updated: DiaryListItem = {
        id,
        date: existing?.date ?? '2026-08-08',
        text: body.text ?? existing?.text ?? '',
        draft_text: body.draft_text ?? existing?.draft_text ?? '',
        status: body.status ?? existing?.status ?? 'draft',
        source: existing?.source ?? 'manual',
        images: existing?.images ?? [],
      }
      diaries = diaries.some(item => item.id === id)
        ? diaries.map(item => item.id === id ? updated : item)
        : [updated, ...diaries]
      return jsonResponse(updated)
    }
    if (diaryPathMatch && method === 'DELETE') {
      const id = Number(diaryPathMatch[1])
      diaries = diaries.filter(item => item.id !== id)
      return emptyResponse()
    }
    if (path === '/api/weekly-comic/list' && method === 'GET') return jsonResponse(options.weeklyComics ?? [])
    if (path === '/api/story/chapters' && method === 'GET') {
      if (options.storyChaptersSessionExpired) {
        return jsonResponse({ detail: 'authentication required' }, 401)
      }
      return jsonResponse({ items: storyChapters, draft_count: storyDraftCount })
    }
    if (path === '/api/story/picturebooks' && method === 'GET') {
      return jsonResponse({ items: options.picturebooks ?? [] })
    }
    if (path === '/api/film-folder/picturebooks' && method === 'GET') {
      if (options.storyChaptersSessionExpired) {
        return jsonResponse({ detail: 'authentication required' }, 401)
      }
      return jsonResponse(options.filmPicturebooks ?? {
        active_generation: null, unfinished_count: 0, items: [],
      })
    }
    if (path === '/api/film-folder/motion-comics' && method === 'GET') {
      return jsonResponse(options.filmMotionComics ?? {
        active_generation: null, unfinished_count: 0, items: [],
      })
    }
    if (path === '/api/film-folder/time-stories' && method === 'GET') {
      return jsonResponse({ items: [] })
    }
    if (path === '/api/film-folder/picturebooks/unfinished' && method === 'GET') {
      return jsonResponse({ items: options.unfinishedPicturebooks ?? [] })
    }
    if (path === '/api/film-folder/motion-comics/unfinished' && method === 'GET') {
      return jsonResponse({ items: options.unfinishedMotionComics ?? [] })
    }
    const picturebookRetryMatch = path.match(/^\/api\/picturebook\/(\d+)\/retry$/)
    if (picturebookRetryMatch && method === 'POST') {
      return options.picturebookRetry
        ? options.picturebookRetry(Number(picturebookRetryMatch[1]))
        : jsonResponse({ id: Number(picturebookRetryMatch[1]), status: 'running' })
    }
    const videoRetryMatch = path.match(/^\/api\/picturebook-video\/(\d+)\/retry$/)
    if (videoRetryMatch && method === 'POST') {
      return options.videoRetry
        ? options.videoRetry(Number(videoRetryMatch[1]))
        : jsonResponse({ id: Number(videoRetryMatch[1]), status: 'running' })
    }
    const filmPicturebookMatch = path.match(
      /^\/api\/film-folder\/picturebooks\/(canonical_work|historical_job)\/(\d+)$/,
    )
    if (filmPicturebookMatch && method === 'GET') {
      const detail = options.filmPicturebookDetails?.[
        `${filmPicturebookMatch[1]}-${filmPicturebookMatch[2]}`
      ]
      return detail
        ? jsonResponse(detail)
        : jsonResponse({ detail: 'picturebook not found' }, 404)
    }
    const filmMotionMatch = path.match(/^\/api\/film-folder\/motion-comics\/(\d+)$/)
    if (filmMotionMatch && method === 'GET') {
      const detail = options.filmMotionComicDetails?.[Number(filmMotionMatch[1])]
      return detail
        ? jsonResponse(detail)
        : jsonResponse({ detail: 'motion comic not found' }, 404)
    }
    const storyDayMatch = path.match(/^\/api\/story\/days\/([^/]+)$/)
    if (storyDayMatch && method === 'GET') {
      const date = decodeURIComponent(storyDayMatch[1])
      const detail = storyDayDetails[date]
      return detail ? jsonResponse(detail) : jsonResponse({ detail: 'story day not found' }, 404)
    }
    if (path === '/api/story/works' && method === 'GET') return jsonResponse(storyWorks)
    if (path === '/api/story/works' && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}'))
      const diary = diaries.find(item => item.id === body.source_diary_id)
      const created: StoryWorkItem = {
        id: 900 + storyWorks.length,
        owner_user_id: me.id,
        source_diary_id: body.source_diary_id,
        title: body.title || `${diary?.date ?? '今天'} 的故事`,
        medium: body.medium,
        narrative_mode: body.narrative_mode,
        style: body.style,
        selected_segments: body.selected_segments,
        forbidden_content: body.forbidden_content ?? null,
        status: 'ready',
        assets: [{ id: 1, asset_type: 'text', text: body.selected_segments?.[0] ?? diary?.text ?? '', url: null }],
        created_at: '2026-08-06T08:00:00Z',
        updated_at: '2026-08-06T08:00:00Z',
      }
      storyWorks = [created, ...storyWorks]
      return jsonResponse(created, 201)
    }
    const storyWorkMatch = path.match(/^\/api\/story\/works\/(\d+)$/)
    if (storyWorkMatch && method === 'DELETE') {
      const id = Number(storyWorkMatch[1])
      storyWorks = storyWorks.filter(item => item.id !== id)
      return emptyResponse()
    }
    if (storyWorkMatch && method === 'GET') {
      return jsonResponse({ detail: 'story work not found' }, 404)
    }
    if (path === '/api/generation/slots' && method === 'GET') {
      return jsonResponse({ slots: [] })
    }
    const draftMatch = path.match(/^\/api\/story\/drafts\/(\d+)\/picturebook$/)
    if (draftMatch && (method === 'POST' || method === 'GET')) {
      return jsonResponse({ detail: 'draft picturebook not found' }, 404)
    }
    if (path === '/api/story/drafts' && method === 'GET') {
      return jsonResponse({ items: [] })
    }
    const storyAudienceMatch = path.match(/^\/api\/story\/works\/(\d+)\/audience$/)
    if (storyAudienceMatch && method === 'GET') {
      return jsonResponse({ items: [] })
    }
    if (storyAudienceMatch && method === 'PUT') {
      return jsonResponse({ items: [] })
    }
    if (path === '/api/story/feed' && method === 'GET') {
      publicationReads += 1
      if (options.publicationsSessionExpired) {
        return jsonResponse({ detail: 'authentication required' }, 401)
      }
      if (options.publicationFailureOnce && publicationReads === 1) {
        return jsonResponse({ detail: 'publication feed unavailable' }, 503)
      }
      return jsonResponse({ items: publications, next_cursor: null })
    }
    if (path === '/api/subscriptions/following' && method === 'GET') return jsonResponse([])
    if (path === '/api/subscriptions/audience' && method === 'GET') return jsonResponse([])
    if (path === '/api/character-profile' && method === 'GET') {
      return jsonResponse({
        user_id: me.id,
        source_photo_url: null,
        reference_image_url: null,
        character_description: '',
        nickname: '',
        display_action: null,
        source_type: '',
        version: 0,
        created_at: null,
        updated_at: null,
      })
    }
    if (path === '/api/profile' && method === 'GET') return jsonResponse(me)
    if (path === '/api/stats' && method === 'GET') {
      return jsonResponse({
        diary_count: 0,
        fragment_count: 0,
        longest_streak: 0,
        month_checkins: 0,
        month_days: 31,
      })
    }
    if (path === '/api/export/pdf' && method === 'POST' && options.exportSessionExpired) {
      return jsonResponse({ detail: 'authentication required' }, 401)
    }
    return jsonResponse({ detail: `unexpected ${method} ${path}` }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('application identity and room states', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    sessionStorage.setItem('zhiji.splash_shown', '1')
    vi.restoreAllMocks()
  })

  test('/me 401 opens the account screen', async () => {
    installFetch()
    render(<App />)

    const heading = await screen.findByRole('heading', { name: '欢迎回来' })
    await waitFor(() => expect(heading).toHaveFocus())
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
  })

  test('an authenticated user without a room enters the personal app', async () => {
    installFetch({ profile: me, room: null })
    render(<App />)

    const nav = await screen.findByRole('navigation', { name: '主导航' })
    expect(nav).toHaveTextContent('记录')
    expect(nav).toHaveTextContent('底片夹')
    expect(nav).toHaveTextContent('回响')
    expect(nav).toHaveTextContent('我的')
    expect(screen.queryByRole('heading', { name: '回响' })).not.toBeInTheDocument()
  })

  test('an account with no room can open the complete main navigation', async () => {
    const fetchMock = installFetch({ profile: me, room: null })
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('navigation', { name: '主导航' })

    await user.click(screen.getByRole('button', { name: '底片夹' }))
    expect(screen.getByRole('button', { name: '底片夹' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(screen.queryByText(/双时间线/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '回响' }))
    expect(screen.getByRole('button', { name: '回响' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '回响' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '我的' }))
    expect(screen.getByRole('button', { name: '我的' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '角色设置' })).toBeInTheDocument()
    expect(screen.queryByText('最长连续')).not.toBeInTheDocument()
    expect(screen.queryByText('本月打卡')).not.toBeInTheDocument()
    expect(screen.queryByText('化解对方的牵挂')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '记录' }))
    expect(screen.getByRole('button', { name: '记录' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('heading', { name: '今天的日程' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '随手记' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '已记下' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '记录，只属于我' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '打卡' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('选择心情')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/streaks')).toBe(false)
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/thermometer')).toBe(false)
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/stats')).toBe(false)
  })

  test('Film folder groups picturebooks by month from the collection API', async () => {
    const fetchMock = installFetch({
      profile: me,
      room: null,
      filmPicturebooks: {
        active_generation: null,
        unfinished_count: 0,
        items: [
          {
            id: 42,
            source_kind: 'canonical_work',
            work_kind: 'daily_picturebook',
            title: '八月的晚霞',
            display_start_date: '2026-08-05',
            display_end_date: '2026-08-05',
            cover_url: null,
            completed_at: '2026-08-05T13:00:00Z',
          },
          {
            id: 40,
            source_kind: 'canonical_work',
            work_kind: 'time_story',
            title: '七月的长线',
            display_start_date: '2026-07-01',
            display_end_date: '2026-07-29',
            cover_url: null,
            completed_at: '2026-07-29T13:00:00Z',
          },
        ],
      },
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))

    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '2026年8月' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '2026年7月' })).toBeInTheDocument()
    expect(screen.getByText('八月的晚霞')).toBeInTheDocument()
    expect(screen.getByText('七月的长线')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input) === '/api/film-folder/picturebooks' && methodOf(input, init) === 'GET'
    )).toBe(true)
    // 新版主入口不再读取旧章节列表。
    expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input) === '/api/story/chapters' && methodOf(input, init) === 'GET'
    )).toBe(false)
  })

  test('Film folder opens a picturebook card in the reader and returns', async () => {
    const fetchMock = installFetch({
      profile: me,
      room: null,
      filmPicturebooks: {
        active_generation: null,
        unfinished_count: 0,
        items: [{
          id: 42,
          source_kind: 'canonical_work',
          work_kind: 'daily_picturebook',
          title: '照片和随记的一天',
          display_start_date: '2026-08-05',
          display_end_date: '2026-08-05',
          cover_url: null,
          completed_at: '2026-08-05T13:00:00Z',
        }],
      },
      filmPicturebookDetails: {
        'canonical_work-42': {
          id: 42,
          source_kind: 'canonical_work',
          work_kind: 'daily_picturebook',
          title: '照片和随记的一天',
          display_start_date: '2026-08-05',
          display_end_date: '2026-08-05',
          cover_url: 'https://example.test/book-cover.jpg',
          completed_at: '2026-08-05T13:00:00Z',
          pages: [
            { page_index: 0, caption: '封面', image_url: 'https://example.test/book-cover.jpg' },
            { page_index: 1, caption: '整理照片', image_url: 'https://example.test/book-page.jpg' },
          ],
        },
      },
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('button', { name: /打开《照片和随记的一天》/ }))

    expect(await screen.findByRole('region', { name: '照片和随记的一天' })).toBeInTheDocument()
    expect(screen.getAllByText('封面').length).toBeGreaterThan(0)
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input) === '/api/film-folder/picturebooks/canonical_work/42'
      && methodOf(input, init) === 'GET'
    )).toBe(true)

    await user.click(screen.getByRole('button', { name: '返回底片夹' }))
    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })

  test('Film folder opens a motion comic card in the read-only player', async () => {
    const fetchMock = installFetch({
      profile: me,
      room: null,
      filmMotionComics: {
        active_generation: null,
        unfinished_count: 0,
        items: [{
          id: 501,
          source_kind: 'video_job',
          work_kind: null,
          title: '晚霞漫剧',
          display_start_date: '2026-08-08',
          display_end_date: '2026-08-08',
          cover_url: null,
          completed_at: '2026-08-09T09:00:00Z',
          video_url: '/api/picturebook-video/501/file',
        }],
      },
      filmMotionComicDetails: {
        501: {
          id: 501,
          title: '晚霞漫剧',
          display_start_date: '2026-08-08',
          display_end_date: '2026-08-08',
          cover_url: null,
          completed_at: '2026-08-09T09:00:00Z',
          duration_seconds: 12,
          video_url: '/api/picturebook-video/501/file',
        },
      },
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('tab', { name: '漫剧' }))
    await user.click(await screen.findByRole('button', { name: /打开《晚霞漫剧》/ }))

    const player = await screen.findByLabelText('晚霞漫剧的视频')
    expect(player).toBeInTheDocument()
    // 只读播放页不暴露生成或重试入口。
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /生成/ })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      methodOf(input, init) !== 'GET' && pathOf(input).startsWith('/api/picturebook-video')
    )).toBe(false)
  })

  test('Film folder has no draft box or global create menu; picturebook entry opens the choice sheet', async () => {
    installFetch({ profile: me, room: null })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /草稿箱/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建故事' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '生成绘本' }))
    const sheet = await screen.findByRole('dialog', { name: '生成绘本' })
    expect(within(sheet).getByRole('button', { name: '当日绘本' })).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: '时光故事' })).toBeInTheDocument()
  })

  test('one source-confirm click enters the editor loading boundary', async () => {
    const diaryRead = deferred<Response>()
    const fetchMock = installFetch({
      profile: me,
      room: null,
      diaryGetResponse: diaryRead.promise,
      fragments: [{
        id: 21,
        date: '2026-08-08',
        content: '中午阳光很软',
        photo_url: null,
        photo_asset_id: null,
        photo_description: null,
        mood_tag: null,
        record_time: '14:32',
        created_at: '2026-08-08T06:32:00Z',
      }],
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '记录' }))
    await user.click(await screen.findByRole('button', { name: /生成今日日记|打开 .* 的日记/ }))
    await user.click(await screen.findByRole('button', { name: '用 1 条素材生成' }))

    // Single click: sheet exits, editor loading shows immediately, one diary GET
    expect(screen.queryByText('选择生成素材')).not.toBeInTheDocument()
    expect(await screen.findByText('加载中…')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([input]) =>
      pathOf(input) === '/api/diary' && methodOf(input) === 'GET'
    )).toHaveLength(1)

    // Resolve: editor appears; create happens at most once
    diaryRead.resolve(jsonResponse(null))
    expect(await screen.findByRole('button', { name: '完成日记' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([input, init]) =>
      pathOf(input) === '/api/diary' && methodOf(input, init) === 'POST'
    ).length).toBeLessThanOrEqual(1)
  })

  test('Diary editor clears selected record sources after switching dates', async () => {
    const fetchMock = installFetch({
      profile: me,
      room: null,
      fragments: [{
        id: 201,
        date: '2026-08-08',
        content: '桥边的光',
        photo_url: null,
        photo_asset_id: null,
        photo_description: null,
        mood_tag: null,
        record_time: null,
        created_at: '2026-08-08T02:00:00Z',
      }],
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '记录' }))
    await user.click(await screen.findByRole('button', { name: /生成今日日记|打开 .* 的日记/ }))
    await user.click(await screen.findByRole('button', { name: '用 1 条素材生成' }))
    expect(await screen.findByRole('button', { name: '完成日记' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '前一天' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input, init]) =>
      pathOf(input) === '/api/diary' && methodOf(input, init) === 'POST'
    ).length).toBeGreaterThanOrEqual(2))
    await user.click(await screen.findByRole('button', { name: '一键生成' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input).match(/^\/api\/diary\/\d+\/ai-fill$/) && methodOf(input, init) === 'POST'
    )).toBe(true))
    const aiFillCall = fetchMock.mock.calls.find(([input, init]) =>
      pathOf(input).match(/^\/api\/diary\/\d+\/ai-fill$/) && methodOf(input, init) === 'POST'
    )
    const body = JSON.parse(String(aiFillCall?.[1]?.body ?? '{}'))
    expect(body).toEqual({ emotion_mode: 'real' })
  })

  test('Film folder picturebook sheet opens the daily picturebook wizard', async () => {
    installFetch({
      profile: me,
      room: null,
      diaries: [{
        id: 42,
        date: '2026-08-08',
        text: '第一段。\n\n第二段。',
        status: 'confirmed',
        source: 'manual',
        images: [],
      }],
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('button', { name: '生成绘本' }))
    await user.click(await screen.findByRole('button', { name: '当日绘本' }))

    expect(await screen.findByRole('heading', { name: '当日绘本' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
  })

  test('Film folder motion comic entry opens the preparation wizard', async () => {
    const picturebook: CompletedPicturebook = {
      source_kind: 'canonical_work',
      source_id: 91,
      title: '这一周的绘本',
      source_start_date: '2026-08-03',
      source_end_date: '2026-08-08',
      start_date: '2026-08-03',
      end_date: '2026-08-08',
      date: '2026-08-08',
      style: 'watercolor',
      cover_url: '/characters/main/p01.webp',
      total_pages: 9,
      ready_pages: 9,
      pages: Array.from({ length: 9 }, (_, index) => ({
        page_index: index,
        image_url: `/characters/main/p0${(index % 8) + 1}.webp`,
        caption: index === 0 ? '封面' : `正文第 ${index} 页`,
      })),
    }
    const fetchMock = installFetch({
      profile: me,
      room: null,
      picturebooks: [picturebook],
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('tab', { name: '漫剧' }))
    await user.click(await screen.findByRole('button', { name: '生成 AI 漫剧' }))

    expect(await screen.findByRole('heading', { name: '漫剧准备' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /这一周的绘本/ })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      methodOf(input, init) !== 'GET'
      && pathOf(input).startsWith('/api/picturebook-video')
    )).toBe(false)
  })

  test('Film folder continue entry opens the unfinished list for the current medium', async () => {
    installFetch({
      profile: me,
      room: null,
      filmPicturebooks: {
        active_generation: null,
        unfinished_count: 2,
        items: [],
      },
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('button', { name: '继续创作（2）' }))

    expect(await screen.findByRole('heading', { name: '继续创作绘本' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
  })

  test('an authenticated user defaults to the personal space tab', async () => {
    installFetch({ profile: me, room: pairedRoom })
    render(<App />)

    const mineTab = await screen.findByRole('button', { name: '我的' })
    expect(mineTab).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '今天的日程' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '记录，只属于我' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '打卡' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /小满.*阿禾/ })).not.toBeInTheDocument()
  })

  test('registration keeps the authenticated identity and opens the personal space tab', async () => {
    const fetchMock = installFetch({ registerProfile: me })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '注册新账号' }))
    const passwordInput = screen.getByLabelText('密码')
    expect(passwordInput).toHaveAttribute('minlength', '8')
    expect(screen.getByText('至少 8 个字符')).toBeInTheDocument()
    await user.type(screen.getByLabelText('用户名'), 'xiaoman')
    await user.type(screen.getByLabelText('昵称'), me.nickname)
    await user.type(passwordInput, 'correct horse battery')
    await user.click(screen.getByRole('button', { name: '创建账号' }))

    const nav = await screen.findByRole('navigation', { name: '主导航' })
    expect(nav).toHaveTextContent('记录')
    expect(nav).toHaveTextContent('底片夹')
    expect(nav).toHaveTextContent('回响')
    expect(nav).toHaveTextContent('我的')
    expect(screen.getByRole('button', { name: '我的' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '记录，只属于我' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '回响' })).not.toBeInTheDocument()
    expect(screen.queryByText('切换用户')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/users')).toBe(false)
  })

  test('Resonance no longer starts from legacy room creation', async () => {
    const fetchMock = installFetch({ profile: me, room: null, publications: [] })
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('navigation', { name: '主导航' })
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '回响' }))
    expect(await screen.findByText('还没有发布或收到故事')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()
    expect(screen.queryByText('ABCD-EFGH-JKMP-QRST')).not.toBeInTheDocument()
    expect(screen.queryByText(/原始温度/)).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input) === '/api/rooms' && methodOf(input, init) === 'POST'
    )).toBe(false)
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/rooms/current')).toBe(false)
  })

  test('Resonance does not expose legacy share-code join', async () => {
    const fetchMock = installFetch({ profile: me, room: null, joinedRoom: pairedRoom })
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('navigation', { name: '主导航' })
    expect(screen.queryByLabelText('分享码')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '回响' }))
    expect(await screen.findByText('还没有发布或收到故事')).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: '主导航' })
    expect(nav).toHaveTextContent('回响')
    expect(nav).toHaveTextContent('记录')
    expect(nav).toHaveTextContent('底片夹')
    expect(nav).toHaveTextContent('我的')
    expect(screen.queryByLabelText('分享码')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([request]) => pathOf(request) === '/api/room-invites/join')).toBe(false)
  })

  test('a paired account defaults to the personal space and has no identity switcher or users request', async () => {
    const fetchMock = installFetch({ profile: me, room: pairedRoom })
    render(<App />)

    expect(await screen.findByRole('navigation', { name: '主导航' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '我的' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '记录，只属于我' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /小满.*阿禾/ })).not.toBeInTheDocument()
    expect(screen.queryByText('切换用户')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /用户/ })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/users')).toBe(false)
  })

  test('preferences are isolated by authenticated account', async () => {
    localStorage.setItem('zhiji:user:9:emotionMode', 'real')
    localStorage.setItem('zhiji:user:9:customEmotion', 'ALICE_PRIVATE_PROMPT')
    localStorage.setItem(`zhiji:user:${me.id}:emotionMode`, 'poetic')
    localStorage.setItem(`zhiji:user:${me.id}:drawStyle`, 'watercolor')
    installFetch({ profile: me, room: pairedRoom })
    render(<App />)

    // The personal space no longer exposes preference or profile editing at all.
    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /我的创作偏好/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编辑我的资料/ })).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('08:45')).not.toBeInTheDocument()
    expect(screen.queryByText('日记提醒时间')).not.toBeInTheDocument()
    // Another account's private prompt must never leak into this session.
    expect(screen.queryByDisplayValue('ALICE_PRIVATE_PROMPT')).not.toBeInTheDocument()
  })

  test('Mine centres on the character and keeps the rest behind setting rows', async () => {
    installFetch({ profile: me, room: null })
    render(<App />)

    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '还没有小主角' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '角色设置' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /选一位小主角/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /关注与粉丝/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /账号/ })).toBeInTheDocument()
    // Relationship lists are one level deeper now, not on the surface.
    expect(screen.queryByText('看见我的人')).not.toBeInTheDocument()
  })

  test('Resonance is a visible-work publishing space, not a direct chat room', async () => {
    const fetchMock = installFetch({ profile: me, roomFailure: true, publications: [] })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '回响' }))

    expect(await screen.findByRole('heading', { name: '回响' })).toBeInTheDocument()
    expect(await screen.findByText('还没有发布或收到故事')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '写一条共享动态' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '发布到我们' })).not.toBeInTheDocument()
    expect(screen.queryByText('状态窗')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/rooms/current')).toBe(false)
  })

  test('logout clears the account state and returns to auth', async () => {
    const fetchMock = installFetch({ profile: me, room: pairedRoom })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /账号/ }))
    await user.click(await screen.findByRole('button', { name: '退出登录' }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) =>
        pathOf(input) === '/api/auth/session' && methodOf(input, init) === 'DELETE'
      )).toBe(true)
    })
  })

  test('authentication errors are visible and keep the submitted mode', async () => {
    const fetchMock = installFetch({ loginFailure: true })
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('用户名'), 'missing')
    await user.type(screen.getByLabelText('密码'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('用户名或密码不正确')
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([input]) => pathOf(input) === '/api/me')).toHaveLength(1)
    expect(fetchMock.mock.calls.filter(([input]) => pathOf(input) === '/api/auth/login')).toHaveLength(1)
  })

  test('legacy room bootstrap failures no longer affect the main app', async () => {
    const fetchMock = installFetch({ profile: me, roomFailure: true, publications: [] })
    const user = userEvent.setup()
    render(<App />)

    const nav = await screen.findByRole('navigation', { name: '主导航' })
    expect(nav).toHaveTextContent('记录')
    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '记录，只属于我' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '回响' }))
    expect(await screen.findByText('还没有发布或收到故事')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/rooms/current')).toBe(false)

    await user.click(screen.getByRole('button', { name: '记录' }))
    expect(screen.getByRole('heading', { name: '随手记' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '已记下' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  test('a protected story feed 401 clears identity and returns to auth', async () => {
    installFetch({ profile: me, publicationsSessionExpired: true })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '回响' }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '回响' })).not.toBeInTheDocument()
  })

  test('logout still clears local identity when the server session already expired', async () => {
    installFetch({ profile: me, room: pairedRoom, logoutSessionExpired: true })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /账号/ }))
    await user.click(await screen.findByRole('button', { name: '退出登录' }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
  })

  test('a protected film folder request 401 also converges to the auth screen', async () => {
    installFetch({ profile: me, room: pairedRoom, storyChaptersSessionExpired: true })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '底片夹' }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '底片夹' })).not.toBeInTheDocument()
  })

  test('story feed retry resolves back to the empty publishing space', async () => {
    installFetch({ profile: me, publicationFailureOnce: true, publications: [] })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '回响' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('动态暂时加载不出来')
    await user.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('还没有发布或收到故事')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()
  })

  test('the record page opens the diary notebook and returns to the selected date fragments', async () => {
    installFetch({
      profile: me,
      room: null,
      fragments: [{
        id: 21,
        date: '2026-08-09',
        content: '桥边的光',
        photo_url: null,
        photo_asset_id: null,
        photo_description: null,
        mood_tag: null,
        record_time: '14:32',
        created_at: '2026-08-09T06:32:00Z',
      }],
      notebookIndex: {
        items: [{ diary_id: 31, date: '2026-08-09' }],
        total: 1,
      },
      notebookDetails: {
        31: {
          id: 31,
          date: '2026-08-09',
          text: '今天把桥边的光写进了日记。',
          status: 'confirmed',
          source: 'manual',
          images: [],
        },
      },
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '记录' }))
    expect(await screen.findByText('桥边的光')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '打开日记本' }))
    expect(await screen.findByRole('heading', { name: '我的日记本' })).toBeInTheDocument()
    expect(await screen.findByText('今天把桥边的光写进了日记。')).toBeInTheDocument()
    expect(screen.getByText('第 1 / 1 篇')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '返回记录页' }))
    expect(await screen.findByText('桥边的光')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '随手记' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })
})

function RoomRaceHarness() {
  const { room, status, leaveRoom } = useRoom()
  return (
    <div>
      <output aria-label="房间状态">{status}:{room?.state ?? 'none'}</output>
      <button type="button" onClick={() => { void leaveRoom() }}>离开</button>
    </div>
  )
}

test('a stale waiting-room poll cannot revive a room after leave', async () => {
  const stalePoll = deferred<Response>()
  let roomReads = 0
  let poll: (() => void) | null = null
  vi.spyOn(window, 'setInterval').mockImplementation(handler => {
    if (typeof handler === 'function') poll = () => handler()
    return 321
  })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(input)
    if (path === '/api/rooms/current') {
      roomReads += 1
      return roomReads === 1 ? jsonResponse(waitingRoom) : stalePoll.promise
    }
    if (path === `/api/rooms/${waitingRoom.id}/leave` && methodOf(input, init) === 'POST') {
      return emptyResponse()
    }
    return jsonResponse({ detail: 'unexpected request' }, 404)
  }))

  render(<RoomProvider><RoomRaceHarness /></RoomProvider>)
  expect(await screen.findByText('ready:waiting')).toBeInTheDocument()
  act(() => { poll?.() })
  fireEvent.click(screen.getByRole('button', { name: '离开' }))
  expect(await screen.findByText('ready:none')).toBeInTheDocument()

  await act(async () => { stalePoll.resolve(jsonResponse(waitingRoom)) })
  expect(screen.getByText('ready:none')).toBeInTheDocument()
})

describe('unfinished film folder recovery', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    sessionStorage.setItem('zhiji.splash_shown', '1')
    vi.restoreAllMocks()
  })

  const unfinishedPicturebook = {
    id: 9, job_id: 9, source_kind: 'historical_job', work_kind: null,
    title: '2026-08-07 绘本', display_start_date: '2026-08-07',
    display_end_date: '2026-08-07', error: '生成过程出错了，可以重试', updated_at: 't',
  }

  async function openUnfinishedPicturebooks(
    user: ReturnType<typeof userEvent.setup>,
    overrides: Parameters<typeof installFetch>[0] = {},
  ) {
    const fetchMock = installFetch({
      profile: me,
      room: null,
      filmPicturebooks: { active_generation: null, unfinished_count: 1, items: [] },
      unfinishedPicturebooks: [unfinishedPicturebook],
      ...overrides,
    })
    render(<App />)
    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('button', { name: '继续创作（1）' }))
    await screen.findByRole('heading', { name: '继续创作绘本' })
    return fetchMock
  }

  test('historical picturebook retry success returns to the film folder', async () => {
    const user = userEvent.setup()
    const fetchMock = await openUnfinishedPicturebooks(user)

    await user.click(await screen.findByRole('button', { name: '重试绘本' }))

    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input) === '/api/picturebook/9/retry' && methodOf(input, init) === 'POST'
    )).toBe(true)
  })

  test('a picturebook generation-slot 409 returns to the film folder without error feedback', async () => {
    const user = userEvent.setup()
    await openUnfinishedPicturebooks(user, {
      picturebookRetry: () => jsonResponse({
        detail: { detail: 'generation slot is occupied', category: 'picturebook', active_job_id: 77 },
      }, 409),
    })

    await user.click(await screen.findByRole('button', { name: '重试绘本' }))

    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(screen.queryByText('重试没能开始，请稍后再试')).not.toBeInTheDocument()
  })

  test('an unrelated 409 keeps the unfinished page and shows safe feedback', async () => {
    const user = userEvent.setup()
    await openUnfinishedPicturebooks(user, {
      picturebookRetry: () => jsonResponse({ detail: 'diary source is unavailable' }, 409),
    })

    await user.click(await screen.findByRole('button', { name: '重试绘本' }))

    expect(await screen.findByRole('heading', { name: '继续创作绘本' })).toBeInTheDocument()
    expect(await screen.findByText('重试没能开始，请稍后再试')).toBeInTheDocument()
    expect(screen.getByText('2026-08-07 绘本')).toBeInTheDocument()
  })

  test('a 503 retry failure keeps the unfinished page with safe feedback', async () => {
    const user = userEvent.setup()
    await openUnfinishedPicturebooks(user, {
      picturebookRetry: () => jsonResponse({ detail: 'upstream unavailable' }, 503),
    })

    await user.click(await screen.findByRole('button', { name: '重试绘本' }))

    expect(await screen.findByRole('heading', { name: '继续创作绘本' })).toBeInTheDocument()
    expect(await screen.findByText('重试没能开始，请稍后再试')).toBeInTheDocument()
  })

  const unfinishedMotion = {
    id: 4, source_kind: 'work', source_id: 42, title: '',
    video_job_id: 501, status: 'failed', error: '生成过程出错了，可以重试', updated_at: 't',
  }

  async function openUnfinishedMotion(
    user: ReturnType<typeof userEvent.setup>,
    overrides: Parameters<typeof installFetch>[0] = {},
  ) {
    const fetchMock = installFetch({
      profile: me,
      room: null,
      filmMotionComics: { active_generation: null, unfinished_count: 1, items: [] },
      unfinishedMotionComics: [unfinishedMotion],
      ...overrides,
    })
    render(<App />)
    await user.click(await screen.findByRole('button', { name: '底片夹' }))
    await user.click(await screen.findByRole('tab', { name: '漫剧' }))
    await user.click(await screen.findByRole('button', { name: '继续创作（1）' }))
    await screen.findByRole('heading', { name: '继续创作漫剧' })
    return fetchMock
  }

  test('motion retry success returns to the film folder', async () => {
    const user = userEvent.setup()
    const fetchMock = await openUnfinishedMotion(user)

    await user.click(await screen.findByRole('button', { name: '重试漫剧' }))

    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      pathOf(input) === '/api/picturebook-video/501/retry' && methodOf(input, init) === 'POST'
    )).toBe(true)
  })

  test('a motion generation-slot 409 returns to the film folder', async () => {
    const user = userEvent.setup()
    await openUnfinishedMotion(user, {
      videoRetry: () => jsonResponse({
        detail: { detail: 'generation slot is occupied', category: 'motion_comic', active_job_id: 88 },
      }, 409),
    })

    await user.click(await screen.findByRole('button', { name: '重试漫剧' }))

    expect(await screen.findByRole('heading', { name: '底片夹' })).toBeInTheDocument()
    expect(screen.queryByText('重试没能开始，请稍后再试')).not.toBeInTheDocument()
  })

  test('a motion retry 503 keeps the unfinished page with safe feedback', async () => {
    const user = userEvent.setup()
    await openUnfinishedMotion(user, {
      videoRetry: () => jsonResponse({ detail: 'upstream unavailable' }, 503),
    })

    await user.click(await screen.findByRole('button', { name: '重试漫剧' }))

    expect(await screen.findByRole('heading', { name: '继续创作漫剧' })).toBeInTheDocument()
    expect(await screen.findByText('重试没能开始，请稍后再试')).toBeInTheDocument()
    expect(screen.getByText('未命名漫剧')).toBeInTheDocument()
  })

  test('a motion draft opens the wizard instead of retrying', async () => {
    const user = userEvent.setup()
    const fetchMock = await openUnfinishedMotion(user, {
      unfinishedMotionComics: [{
        id: 3, source_kind: 'work', source_id: 42, title: '晚霞漫剧',
        video_job_id: null, status: 'draft', error: null, updated_at: 't',
      }],
    })

    await user.click(await screen.findByRole('button', { name: '继续编辑' }))

    expect(await screen.findByRole('heading', { name: '漫剧准备' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) =>
      methodOf(input, init) === 'POST' && pathOf(input).includes('/retry')
    )).toBe(false)
  })
})
