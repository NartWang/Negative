import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import PostCard from './PostCard'
import { storyApi } from '../../api/client'
import type { ResonanceFeedItem, WorkComment } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      like: vi.fn(),
      unlike: vi.fn(),
      addComment: vi.fn(),
      unpublish: vi.fn(),
      getAudience: vi.fn(),
      replaceAudience: vi.fn(),
    },
  }
})

const base = {
  medium: 'picture_book' as const,
  narrative_mode: 'true_record',
  style: 'watercolor',
  assets: [],
  published_at: '2026-08-09T09:00:00+00:00',
}

const comment = (overrides: Partial<WorkComment> = {}): WorkComment => ({
  id: 'c-1',
  work_id: 2,
  viewer_user_id: 9,
  author_user_id: 9,
  author: { id: 9, nickname: '我', avatar_url: null },
  viewer: { id: 9, nickname: '我', avatar_url: null },
  body: '这个画面好像电影',
  created_at: '2026-08-09T10:00:00+00:00',
  ...overrides,
})

const viewerCard = (overrides = {}): ResonanceFeedItem => ({
  ...base,
  id: 2,
  title: '阿禾的发布',
  owner: { id: 8, nickname: '阿禾', avatar_url: null },
  mine: false,
  liked_by_me: false,
  comments: [],
  ...overrides,
})

const mineCard = (overrides = {}): ResonanceFeedItem => ({
  ...base,
  id: 1,
  title: '我的发布',
  owner: { id: 1, nickname: '我', avatar_url: null },
  mine: true,
  audience_count: 2,
  likes: [],
  comments: [],
  ...overrides,
})

function renderCard(item: ResonanceFeedItem) {
  const props = {
    onOpenOwnStoryWork: vi.fn(),
    onOpenPublishedDetail: vi.fn(),
    onRemove: vi.fn(),
  }
  render(<PostCard item={item} {...props} />)
  return props
}

describe('PostCard viewer perspective', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('shows like and comment affordances, no owner menu or liker list', async () => {
    renderCard(viewerCard({ comments: [comment()] }))

    expect(screen.getByRole('button', { name: '点赞' })).toBeInTheDocument()
    expect(screen.getByLabelText('评论')).toBeInTheDocument()
    expect(screen.getByText(/这个画面好像电影/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '更多操作' })).not.toBeInTheDocument()
    expect(screen.queryByText(/点赞：/)).not.toBeInTheDocument()
  })

  test('like toggles optimistically and rolls back on failure', async () => {
    vi.mocked(storyApi.like).mockResolvedValue({ liked: true })
    const user = userEvent.setup()
    renderCard(viewerCard())

    await user.click(screen.getByRole('button', { name: '点赞' }))
    expect(await screen.findByRole('button', { name: '取消赞' })).toBeInTheDocument()

    vi.mocked(storyApi.unlike).mockRejectedValue(new Error('boom'))
    await user.click(screen.getByRole('button', { name: '取消赞' }))
    // rollback: still liked
    expect(await screen.findByRole('button', { name: '取消赞' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('点赞没成功，请重试')
  })
})

describe('PostCard owner perspective', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('shows liker names, all comments, and the overflow menu; no self-like', async () => {
    renderCard(
      mineCard({
        likes: [
          { id: 8, nickname: '阿禾', avatar_url: null },
          { id: 9, nickname: '妈妈', avatar_url: null },
        ],
        comments: [
          comment({
            id: 'c-1',
            author: { id: 8, nickname: '阿禾', avatar_url: null },
            viewer: { id: 8, nickname: '阿禾', avatar_url: null },
            author_user_id: 8,
            viewer_user_id: 8,
          }),
        ],
      }),
    )

    expect(screen.getByText('点赞：阿禾、妈妈')).toBeInTheDocument()
    expect(screen.getByText(/这个画面好像电影/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '更多操作' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '点赞' })).not.toBeInTheDocument()
  })

  test('the overflow menu offers visibility and unpublish with confirmation', async () => {
    vi.mocked(storyApi.unpublish).mockResolvedValue(undefined)
    const user = userEvent.setup()
    const { onRemove } = renderCard(mineCard())

    await user.click(screen.getByRole('button', { name: '更多操作' }))
    expect(await screen.findByRole('button', { name: '可见范围' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '取消发布' }))
    expect(screen.getByText(/会从所有人的回响里移除/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认取消发布' }))

    await waitFor(() => expect(storyApi.unpublish).toHaveBeenCalledWith(1))
    expect(onRemove).toHaveBeenCalledWith(1)
  })

  test('owner reply binds the comment viewer_user_id', async () => {
    const viewerComment = comment({
      id: 'c-9',
      author: { id: 8, nickname: '阿禾', avatar_url: null },
      viewer: { id: 8, nickname: '阿禾', avatar_url: null },
      author_user_id: 8,
      viewer_user_id: 8,
    })
    vi.mocked(storyApi.addComment).mockResolvedValue(
      comment({
        id: 'c-10',
        author: { id: 1, nickname: '我', avatar_url: null },
        viewer: { id: 8, nickname: '阿禾', avatar_url: null },
        author_user_id: 1,
        viewer_user_id: 8,
        body: '当时刚好走慢了一点',
      }),
    )
    const user = userEvent.setup()
    renderCard(mineCard({ comments: [viewerComment] }))

    await user.click(screen.getByRole('button', { name: '回复' }))
    await user.type(screen.getByLabelText('回复评论'), '当时刚好走慢了一点')
    await user.click(screen.getByRole('button', { name: '发送评论' }))

    await waitFor(() =>
      expect(storyApi.addComment).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ viewer_user_id: 8 }),
      ),
    )
  })

  test('owner cannot send a reply before choosing a viewer comment', async () => {
    const viewerComment = comment({
      id: 'c-9',
      author: { id: 8, nickname: '阿禾', avatar_url: null },
      viewer: { id: 8, nickname: '阿禾', avatar_url: null },
      author_user_id: 8,
      viewer_user_id: 8,
    })
    const user = userEvent.setup()
    renderCard(mineCard({ comments: [viewerComment] }))

    await user.type(screen.getByLabelText('回复评论'), '直接回复')
    expect(screen.getByRole('button', { name: '发送评论' })).toBeDisabled()
    expect(storyApi.addComment).not.toHaveBeenCalled()
  })

  test('image load failure keeps the card and shows a media placeholder', async () => {
    renderCard(viewerCard({
      assets: [{ id: 12, ordinal: 0, asset_type: 'image', url: '/api/media/broken', asset_id: 'broken', text: null }],
    }))

    const image = screen.getByRole('img', { name: '阿禾的发布' })
    fireEvent.error(image)

    expect(screen.getByText('图片暂时加载不出来')).toBeInTheDocument()
    expect(screen.getByRole('article')).toHaveTextContent('阿禾的发布')
  })
})

describe('InlineComments retry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('a failed comment keeps the draft and reuses the same request id on retry', async () => {
    vi.mocked(storyApi.addComment)
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(comment({ id: 'c-final', body: '真好' }))
    const user = userEvent.setup()
    renderCard(viewerCard())

    const input = screen.getByLabelText('评论')
    await user.type(input, '真好')
    await user.click(screen.getByRole('button', { name: '发送评论' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('评论没发出去，请重试')
    expect((input as HTMLInputElement).value).toBe('真好')

    const firstRequestId = vi.mocked(storyApi.addComment).mock.calls[0][1].client_request_id
    await user.click(screen.getByRole('button', { name: '发送评论' }))
    await waitFor(() =>
      expect(vi.mocked(storyApi.addComment).mock.calls).toHaveLength(2),
    )
    expect(vi.mocked(storyApi.addComment).mock.calls[1][1].client_request_id).toBe(firstRequestId)
    // success clears the draft
    await waitFor(() => expect((input as HTMLInputElement).value).toBe(''))
  })
})
