import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import We from './index'
import { roomsApi } from '../../api/client'
import type { Room, RoomFeed, RoomPost, RoomTemperatures } from '../../types'

const authState = vi.hoisted(() => ({ nickname: '小满' }))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 1,
      nickname: authState.nickname,
      avatar_url: null,
      signature: null,
      created_at: '2026-08-01T08:00:00Z',
    },
  }),
}))

const room: Room = {
  id: 'room-pair',
  status: 'active',
  state: 'paired',
  waiting: false,
  created_at: '2026-08-01T08:00:00Z',
  members: [
    { id: 1, nickname: '小满', avatar_url: null, role: 'owner', slot: 1 },
    { id: 2, nickname: '妈妈', avatar_url: null, role: 'member', slot: 2 },
  ],
  partner: { id: 2, nickname: '妈妈', avatar_url: null, role: 'member', slot: 2 },
}

vi.mock('../../contexts/RoomContext', () => ({
  useRoom: () => ({ room }),
}))

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    roomsApi: {
      ...actual.roomsApi,
      feed: vi.fn(),
      createNote: vi.fn(),
      likePost: vi.fn(),
      unlikePost: vi.fn(),
      createComment: vi.fn(),
      withdrawPost: vi.fn(),
      temperatures: vi.fn(),
      publishTemperature: vi.fn(),
      revokeTemperature: vi.fn(),
    },
  }
})

const note = (overrides: Partial<RoomPost> = {}): RoomPost => ({
  id: 'post-1',
  source_type: 'note',
  author: { nickname: '小满', avatar_url: null },
  mine: true,
  snapshot: { type: 'note', body: '第一条动态' },
  media_urls: [],
  published_at: '2026-08-03T10:00:00Z',
  like_count: 0,
  liked_by_me: false,
  comment_count: 0,
  comments_truncated: false,
  comments: [],
  ...overrides,
})

const temperatures = (overrides: Partial<RoomTemperatures> = {}): RoomTemperatures => ({
  own: {
    status: 'available',
    snapshot: { date: '2026-08-03', score: 82, label: '温暖', color: '#b86b52', nickname: '小满' },
  },
  partner: { status: 'unavailable' },
  ...overrides,
})

function feed(items: RoomPost[]): RoomFeed {
  return { items, next_cursor: null }
}

function installDefaults(items: RoomPost[] = [note()]) {
  vi.mocked(roomsApi.feed).mockResolvedValue(feed(items))
  vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures())
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

describe('feed-first 我们 page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.nickname = '小满'
    room.partner!.nickname = '妈妈'
    room.members[1].nickname = '妈妈'
  })

  test('renders the feed in exactly the order returned by the server', async () => {
    installDefaults([
      note({ id: 'latest', snapshot: { type: 'note', body: '服务端第一条' } }),
      note({ id: 'older', snapshot: { type: 'note', body: '服务端第二条' } }),
    ])

    render(<We currentDate="2026-08-03" />)

    const articles = await screen.findAllByRole('article')
    expect(articles).toHaveLength(2)
    expect(articles[0]).toHaveTextContent('服务端第一条')
    expect(articles[1]).toHaveTextContent('服务端第二条')
    expect(roomsApi.feed).toHaveBeenCalledWith(room.id)
  })

  test('lets the second account explicitly refresh for newly shared activity', async () => {
    vi.mocked(roomsApi.feed)
      .mockResolvedValueOnce(feed([]))
      .mockResolvedValueOnce(feed([note({ snapshot: { type: 'note', body: '刚刚发来的消息' } })]))
    vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures())
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    await screen.findByText('这里还很安静')
    await user.click(screen.getByRole('button', { name: '刷新动态' }))

    expect(await screen.findByText('刚刚发来的消息')).toBeInTheDocument()
    expect(roomsApi.feed).toHaveBeenCalledTimes(2)
  })

  test('appends the next server page using its opaque cursor without reordering it', async () => {
    vi.mocked(roomsApi.feed)
      .mockResolvedValueOnce({ items: [note({ id: 'page-1', snapshot: { type: 'note', body: '第一页' } })], next_cursor: 'opaque-cursor' })
      .mockResolvedValueOnce({ items: [note({ id: 'page-2', snapshot: { type: 'note', body: '第二页' } })], next_cursor: null })
    vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures())
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    await user.click(await screen.findByRole('button', { name: '加载更早动态' }))

    expect(roomsApi.feed).toHaveBeenNthCalledWith(2, room.id, 'opaque-cursor')
    const articles = await screen.findAllByRole('article')
    expect(articles[0]).toHaveTextContent('第一页')
    expect(articles[1]).toHaveTextContent('第二页')
    expect(screen.queryByRole('button', { name: '加载更早动态' })).not.toBeInTheDocument()
  })

  test('ignores an older page that resolves after a fresh feed replaces its generation', async () => {
    const staleOlder = deferred<RoomFeed>()
    vi.mocked(roomsApi.feed)
      .mockResolvedValueOnce({
        items: [note({ id: 'old-first', snapshot: { type: 'note', body: '旧第一页' } })],
        next_cursor: 'old-cursor',
      })
      .mockImplementationOnce(() => staleOlder.promise)
      .mockResolvedValueOnce({
        items: [note({ id: 'fresh-first', snapshot: { type: 'note', body: '刷新后的第一页' } })],
        next_cursor: 'fresh-cursor',
      })
      .mockResolvedValueOnce({
        items: [note({ id: 'fresh-older', snapshot: { type: 'note', body: '刷新后的第二页' } })],
        next_cursor: null,
      })
    vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures())
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    await user.click(await screen.findByRole('button', { name: '加载更早动态' }))
    await user.click(screen.getByRole('button', { name: '刷新动态' }))
    expect(await screen.findByText('刷新后的第一页')).toBeInTheDocument()

    const freshOlderButton = screen.getByRole('button', { name: '加载更早动态' })
    expect(freshOlderButton).toBeEnabled()
    await user.click(freshOlderButton)
    expect(roomsApi.feed).toHaveBeenNthCalledWith(4, room.id, 'fresh-cursor')
    expect(await screen.findByText('刷新后的第二页')).toBeInTheDocument()

    staleOlder.resolve({
      items: [note({ id: 'stale', snapshot: { type: 'note', body: '不该出现的旧分页' } })],
      next_cursor: 'stale-cursor',
    })
    await waitFor(() => expect(screen.queryByText('不该出现的旧分页')).not.toBeInTheDocument())
  })

  test('posts a text note as the signed-in writer and puts the server response first', async () => {
    installDefaults([])
    vi.mocked(roomsApi.createNote).mockResolvedValue(note({
      id: 'new-note',
      snapshot: { type: 'note', body: '今天也想告诉你' },
    }))
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    await user.type(await screen.findByLabelText('写一条共享动态'), '  今天也想告诉你  ')
    await user.click(screen.getByRole('button', { name: '发布到我们' }))

    expect(roomsApi.createNote).toHaveBeenCalledWith(room.id, '今天也想告诉你')
    expect(await screen.findByText('今天也想告诉你')).toBeInTheDocument()
    expect(screen.getByText('由 小满 发布')).toBeInTheDocument()
    expect(screen.getByLabelText('写一条共享动态')).toHaveValue('')
  })

  test('preserves note edits typed while the submitted note is in flight', async () => {
    installDefaults([])
    const pending = deferred<RoomPost>()
    vi.mocked(roomsApi.createNote).mockImplementation(() => pending.promise)
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    const editor = await screen.findByLabelText('写一条共享动态')
    await user.type(editor, '先发这一句')
    await user.click(screen.getByRole('button', { name: '发布到我们' }))
    await user.type(editor, '，下一句先留着')
    pending.resolve(note({ id: 'sent', snapshot: { type: 'note', body: '先发这一句' } }))

    expect(await screen.findByText('先发这一句')).toBeInTheDocument()
    expect(editor).toHaveValue('先发这一句，下一句先留着')
  })

  test('switches between my and partner temperature without changing the writer', async () => {
    installDefaults([])
    vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures({
      partner: {
        status: 'available',
        snapshot: { date: '2026-08-03', score: 64, label: '温热', color: '#678b7a', nickname: '妈妈' },
      },
    }))
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    expect(await screen.findByText('82')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '看妈妈的温度' }))

    expect(screen.getByText('64')).toBeInTheDocument()
    expect(screen.getByText('妈妈的温度')).toBeInTheDocument()
    expect(screen.getByText('由 小满 发布')).toBeInTheDocument()
    expect(roomsApi.temperatures).toHaveBeenCalledWith(room.id, '2026-08-03')
  })

  test('shows a calm unavailable state for a partner who has not shared', async () => {
    installDefaults([])
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    await screen.findByText('82')
    await user.click(screen.getByRole('button', { name: '看妈妈的温度' }))

    expect(screen.getByText('妈妈今天还没有分享温度')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '发布今天的温度' })).not.toBeInTheDocument()
  })

  test('publishes and revokes only my temperature snapshot', async () => {
    installDefaults([])
    vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures({
      own: { status: 'unavailable' },
    }))
    vi.mocked(roomsApi.publishTemperature).mockResolvedValue({
      date: '2026-08-03', score: 76, label: '温暖', color: '#b86b52', nickname: '小满',
    })
    vi.mocked(roomsApi.revokeTemperature).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    await user.click(await screen.findByRole('button', { name: '发布今天的温度' }))
    expect(roomsApi.publishTemperature).toHaveBeenCalledWith(room.id, '2026-08-03')
    expect(await screen.findByText('76')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '撤回我的温度' }))
    expect(roomsApi.revokeTemperature).toHaveBeenCalledWith(room.id, '2026-08-03')
    expect(await screen.findByText('你的温度还没有分享')).toBeInTheDocument()
  })

  test('uses PUT and DELETE like operations and follows the returned idempotent state', async () => {
    installDefaults([note()])
    vi.mocked(roomsApi.likePost).mockResolvedValue({ liked: true, like_count: 1 })
    vi.mocked(roomsApi.unlikePost).mockResolvedValue({ liked: false, like_count: 0 })
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    const article = (await screen.findAllByRole('article'))[0]
    await user.click(within(article).getByRole('button', { name: '赞' }))
    expect(roomsApi.likePost).toHaveBeenCalledWith(room.id, 'post-1')
    expect(within(article).getByRole('button', { name: '取消赞' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(within(article).getByRole('button', { name: '取消赞' }))
    expect(roomsApi.unlikePost).toHaveBeenCalledWith(room.id, 'post-1')
    expect(within(article).getByRole('button', { name: '赞' })).toHaveAttribute('aria-pressed', 'false')
  })

  test('submits a comment with a stable client request id and appends the response', async () => {
    installDefaults([note()])
    vi.mocked(roomsApi.createComment).mockResolvedValue({
      id: 'comment-1',
      author: { nickname: '小满', avatar_url: null },
      body: '我也记得',
      created_at: '2026-08-03T10:02:00Z',
      mine: true,
    })
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    const article = (await screen.findAllByRole('article'))[0]
    await user.type(within(article).getByLabelText('评论第一条动态'), '我也记得')
    await user.click(within(article).getByRole('button', { name: '发送评论' }))

    await waitFor(() => expect(roomsApi.createComment).toHaveBeenCalledOnce())
    const [, postId, payload] = vi.mocked(roomsApi.createComment).mock.calls[0]
    expect(postId).toBe('post-1')
    expect(payload.body).toBe('我也记得')
    expect(payload.client_request_id).toMatch(/^[a-zA-Z0-9-]{8,}$/)
    expect(within(article).getByText('我也记得')).toBeInTheDocument()
  })

  test('preserves comment edits typed while the submitted comment is in flight', async () => {
    installDefaults([note()])
    const pending = deferred<Awaited<ReturnType<typeof roomsApi.createComment>>>()
    vi.mocked(roomsApi.createComment).mockImplementation(() => pending.promise)
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    const article = (await screen.findAllByRole('article'))[0]
    const editor = within(article).getByLabelText('评论第一条动态')
    await user.type(editor, '先回应')
    await user.click(within(article).getByRole('button', { name: '发送评论' }))
    await user.type(editor, '，再补一句')
    pending.resolve({
      id: 'sent-comment',
      author: { nickname: '小满', avatar_url: null },
      body: '先回应',
      created_at: '2026-08-03T10:03:00Z',
      mine: true,
    })

    expect(await within(article).findByText('先回应')).toBeInTheDocument()
    expect(editor).toHaveValue('先回应，再补一句')
  })

  test('withdraws my post and never exposes a private-source link on a partner post', async () => {
    const ownDiary = note({
      id: 'mine',
      source_type: 'diary',
      source_id: 9,
      snapshot: { type: 'diary', date: '2026-08-02', text: '我的日记', emotion_mode: null, images: [] },
    })
    const partnerDiary = note({
      id: 'partner',
      source_type: 'diary',
      mine: false,
      author: { nickname: '妈妈', avatar_url: null },
      source_id: undefined,
      snapshot: { type: 'diary', date: '2026-08-01', text: '对方日记', emotion_mode: null, images: [] },
    })
    installDefaults([ownDiary, partnerDiary])
    vi.mocked(roomsApi.withdrawPost).mockResolvedValue(undefined)
    const openDiary = vi.fn()
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" onOpenDiary={openDiary} />)

    const articles = await screen.findAllByRole('article')
    expect(within(articles[0]).getByRole('button', { name: '查看我的原记录' })).toBeInTheDocument()
    expect(within(articles[1]).queryByRole('button', { name: /原记录/ })).not.toBeInTheDocument()
    expect(within(articles[1]).queryByRole('button', { name: '撤回' })).not.toBeInTheDocument()

    await user.click(within(articles[0]).getByRole('button', { name: '撤回' }))
    expect(roomsApi.withdrawPost).toHaveBeenCalledWith(room.id, 'mine')
    expect(await screen.findByText('对方日记')).toBeInTheDocument()
    expect(screen.queryByText('我的日记')).not.toBeInTheDocument()
  })

  test('offers retry and empty states instead of a blank feed', async () => {
    vi.mocked(roomsApi.feed)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(feed([]))
    vi.mocked(roomsApi.temperatures).mockResolvedValue(temperatures())
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时没有读到共享动态')
    await user.click(screen.getByRole('button', { name: '重新读取动态' }))
    expect(await screen.findByText('这里还很安静')).toBeInTheDocument()
  })

  test('keeps every long unbroken room nickname wrap-safe at the 320px breakpoint', async () => {
    const longWriter = 'WriterNicknameWithoutAnyBreakOpportunity123456789'
    const longPartner = 'PartnerNicknameWithoutAnyBreakOpportunity987654321'
    authState.nickname = longWriter
    room.partner!.nickname = longPartner
    room.members[1].nickname = longPartner
    installDefaults([note({
      mine: false,
      author: { nickname: longPartner, avatar_url: null },
    })])
    const user = userEvent.setup()
    render(<We currentDate="2026-08-03" />)

    const heading = await screen.findByRole('heading', { name: `${longWriter} 与 ${longPartner}` })
    const composerWriter = screen.getByText(`由 ${longWriter} 发布`)
    const temperatureButton = screen.getByRole('button', { name: `看${longPartner}的温度` })
    const article = (await screen.findAllByRole('article'))[0]
    const author = within(article).getByText(longPartner)
    expect(heading).toHaveStyle({ minWidth: '0', overflowWrap: 'anywhere' })
    expect(composerWriter).toHaveStyle({ minWidth: '0', overflowWrap: 'anywhere' })
    expect(temperatureButton).toHaveStyle({ minWidth: '0', overflowWrap: 'anywhere' })
    expect(author).toHaveStyle({ minWidth: '0', overflowWrap: 'anywhere' })

    await user.click(temperatureButton)
    const unavailable = screen.getByText(`${longPartner}今天还没有分享温度`)
    expect(unavailable).toHaveStyle({ minWidth: '0', overflowWrap: 'anywhere' })
  })
})
