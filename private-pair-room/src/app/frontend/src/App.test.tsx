import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import { RoomProvider, useRoom } from './contexts/RoomContext'

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
  logoutSessionExpired?: boolean
  exportSessionExpired?: boolean
} = {}) {
  let room = options.room ?? null
  let roomReads = 0
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

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toHaveFocus()
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
  })

  test('registration keeps the authenticated identity and opens pair onboarding', async () => {
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

    expect(await screen.findByRole('heading', { name: '把两个人的日常，放进同一个房间' })).toHaveFocus()
    expect(screen.getByText(`你好，${me.nickname}`)).toBeInTheDocument()
    expect(screen.queryByText('切换用户')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/users')).toBe(false)
  })

  test('room creation issues a share code and enters the waiting state', async () => {
    installFetch({ profile: me, room: null, createdRoom: waitingRoom })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '创建我们的房间' }))

    expect(await screen.findByRole('heading', { name: '等你一起' })).toHaveFocus()
    expect(screen.getByText('ABCD-EFGH-JKMP-QRST')).toBeInTheDocument()
    expect(screen.getByText('轻触复制 · 24 小时有效')).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('房间里只有你们两个人')).toBeInTheDocument()
  })

  test('joining with a share code opens the paired main navigation', async () => {
    const fetchMock = installFetch({ profile: me, room: null, joinedRoom: pairedRoom })
    const user = userEvent.setup()
    render(<App />)

    const input = await screen.findByLabelText('分享码')
    await user.type(input, 'ABCD-EFGH-JKMP-QRST{Enter}')

    const nav = await screen.findByRole('navigation', { name: '主导航' })
    expect(nav).toHaveTextContent('我们')
    expect(nav).toHaveTextContent('记录')
    expect(nav).toHaveTextContent('回忆')
    expect(nav).toHaveTextContent('我的')
    const joinCall = fetchMock.mock.calls.find(([request]) => pathOf(request) === '/api/room-invites/join')
    expect(joinCall?.[1]).toEqual(expect.objectContaining({ credentials: 'same-origin' }))
    expect(JSON.parse(String(joinCall?.[1]?.body))).toEqual({ code: 'ABCD-EFGH-JKMP-QRST' })
  })

  test('a paired account has no identity switcher or users request', async () => {
    const fetchMock = installFetch({ profile: me, room: pairedRoom })
    render(<App />)

    expect(await screen.findByRole('navigation', { name: '主导航' })).toBeInTheDocument()
    expect(screen.queryByText('切换用户')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /用户/ })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === '/api/users')).toBe(false)
  })

  test('preferences are isolated by authenticated account', async () => {
    localStorage.setItem('zhiji:user:9:emotionMode', 'custom')
    localStorage.setItem('zhiji:user:9:customEmotion', 'ALICE_PRIVATE_PROMPT')
    localStorage.setItem(`zhiji:user:${me.id}:emotionMode`, 'poetic')
    localStorage.setItem(`zhiji:user:${me.id}:drawStyle`, 'watercolor')
    localStorage.setItem(`zhiji:user:${me.id}:reminderTime`, '08:45')
    installFetch({ profile: me, room: pairedRoom })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '我的' }))

    expect(await screen.findByText('诗意文艺')).toBeInTheDocument()
    expect(screen.getByText('水彩日记')).toBeInTheDocument()
    expect(screen.getByDisplayValue('08:45')).toHaveAttribute('type', 'time')
    expect(screen.queryByDisplayValue('ALICE_PRIVATE_PROMPT')).not.toBeInTheDocument()
  })

  test('logout clears the account state and returns to auth', async () => {
    const fetchMock = installFetch({ profile: me, room: pairedRoom })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '我的' }))
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

  test('room bootstrap failures are visible instead of silently opening onboarding', async () => {
    installFetch({ profile: me, roomFailure: true })
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取房间状态')
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()
  })

  test('a protected room 401 clears identity and returns to auth', async () => {
    installFetch({ profile: me, room: waitingRoom, roomSessionExpires: true })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '刷新房间状态' }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '等你一起' })).not.toBeInTheDocument()
  })

  test('logout still clears local identity when the server session already expired', async () => {
    installFetch({ profile: me, room: pairedRoom, logoutSessionExpired: true })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '我的' }))
    await user.click(await screen.findByRole('button', { name: '退出登录' }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
  })

  test('a protected export 401 also converges to the auth screen', async () => {
    installFetch({ profile: me, room: pairedRoom, exportSessionExpired: true })
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '我的' }))
    await user.click(await screen.findByRole('button', { name: /导出全部日记为 PDF/ }))

    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeInTheDocument()
  })

  test('a delayed retry stays in retrying state until room identity resolves', async () => {
    const retry = deferred<Response>()
    let roomReads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input)
      if (path === '/api/me') return jsonResponse(me)
      if (path === '/api/rooms/current') {
        roomReads += 1
        if (roomReads === 1) return jsonResponse({ detail: 'unavailable' }, 503)
        return retry.promise
      }
      return jsonResponse({ detail: `unexpected ${methodOf(input, init)} ${path}` }, 404)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '重试' }))

    expect(await screen.findByText('正在重试房间状态…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '创建我们的房间' })).not.toBeInTheDocument()
    retry.resolve(jsonResponse(null))
    expect(await screen.findByRole('button', { name: '创建我们的房间' })).toBeInTheDocument()
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
