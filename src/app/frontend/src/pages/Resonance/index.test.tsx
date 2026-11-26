import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import Resonance from './index'
import { storyApi } from '../../api/client'
import type { ResonanceFeedItem } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      resonanceFeed: vi.fn(),
      collections: vi.fn(),
      collection: vi.fn(),
      publishedWork: vi.fn(),
      interactions: vi.fn(),
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
}

const mineItem = (overrides = {}): ResonanceFeedItem => ({
  ...base,
  id: 1,
  title: '我的发布',
  published_at: '2026-08-08T09:00:00+00:00',
  owner: { id: 1, nickname: '我', avatar_url: null },
  mine: true,
  audience_count: 0,
  likes: [],
  comments: [],
  ...overrides,
})

const viewerItem = (overrides = {}): ResonanceFeedItem => ({
  ...base,
  id: 2,
  title: '阿禾的发布',
  published_at: '2026-08-09T09:00:00+00:00',
  owner: { id: 8, nickname: '阿禾', avatar_url: null },
  mine: false,
  liked_by_me: false,
  comments: [],
  ...overrides,
})

function renderPage() {
  const onOpenOwnStoryWork = vi.fn()
  const onGoStories = vi.fn()
  render(<Resonance onOpenOwnStoryWork={onOpenOwnStoryWork} onGoStories={onGoStories} />)
  return { onOpenOwnStoryWork, onGoStories }
}

describe('Resonance page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storyApi.resonanceFeed).mockResolvedValue({ items: [], next_cursor: null })
    vi.mocked(storyApi.collections).mockResolvedValue({ items: [], next_cursor: null })
    vi.mocked(storyApi.interactions).mockResolvedValue({ items: [] })
  })

  test('dynamic only renders my published cards', async () => {
    vi.mocked(storyApi.resonanceFeed).mockResolvedValue({
      items: [viewerItem(), mineItem()],
      next_cursor: null,
    })
    renderPage()

    expect(await screen.findByRole('heading', { name: '回响' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '动态' })).toHaveAttribute('aria-selected', 'true')
    const cards = await screen.findAllByRole('article')
    expect(cards).toHaveLength(1)
    expect(cards[0]).toHaveTextContent('我')
    expect(screen.queryByText('阿禾')).not.toBeInTheDocument()
  })

  test('empty feed shows guidance copy', async () => {
    const user = userEvent.setup()
    const { onGoStories } = renderPage()
    expect(await screen.findByText('还没有发布故事')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '去故事看看' }))
    expect(onGoStories).toHaveBeenCalled()
  })

  test('interaction summary locates an older feed item without opening safe detail', async () => {
    vi.mocked(storyApi.resonanceFeed)
      .mockResolvedValueOnce({
        items: [mineItem({ id: 10, title: '首屏故事' })],
        next_cursor: 'c1',
      })
      .mockResolvedValueOnce({
        items: [mineItem({ id: 10, title: '首屏故事' })],
        next_cursor: 'c1',
      })
      .mockResolvedValueOnce({
        items: [mineItem({ id: 11, title: '第二页故事' })],
        next_cursor: 'c2',
      })
      .mockResolvedValueOnce({
        items: [mineItem({ id: 12, title: '目标故事' })],
        next_cursor: null,
      })
    vi.mocked(storyApi.interactions).mockResolvedValue({
      items: [
        {
          kind: 'comment',
          work_id: 12,
          work_title: '目标故事',
          actor: { id: 8, nickname: '阿禾', avatar_url: null },
          body: '我看到了',
          created_at: '2026-08-09T10:00:00+00:00',
        },
      ],
    })
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('首屏故事')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '互动汇总' }))
    await user.click(await screen.findByRole('button', { name: /目标故事/ }))

    await waitFor(() => {
      const articles = screen.getAllByRole('article')
      expect(articles.some(article => article.textContent?.includes('目标故事'))).toBe(true)
    })
    expect(storyApi.resonanceFeed).toHaveBeenCalledWith(null, 50)
    expect(storyApi.resonanceFeed).toHaveBeenCalledWith('c1', 50)
    expect(storyApi.resonanceFeed).toHaveBeenCalledWith('c2', 50)
    expect(storyApi.publishedWork).not.toHaveBeenCalled()
  })

  test('feed failure shows a retry', async () => {
    vi.mocked(storyApi.resonanceFeed).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('动态暂时加载不出来')
    vi.mocked(storyApi.resonanceFeed).mockResolvedValue({ items: [], next_cursor: null })
    await user.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() =>
      expect(screen.queryByRole('alert')).not.toBeInTheDocument(),
    )
  })

  test('clicking my card opens the owner story work route', async () => {
    vi.mocked(storyApi.resonanceFeed).mockResolvedValue({
      items: [mineItem()],
      next_cursor: null,
    })
    const user = userEvent.setup()
    const { onOpenOwnStoryWork } = renderPage()

    const card = await screen.findByRole('article')
    await user.click(card.querySelector('.resonance-card-body') as HTMLElement)
    expect(onOpenOwnStoryWork).toHaveBeenCalledWith(1)
    expect(storyApi.publishedWork).not.toHaveBeenCalled()
  })

  test('stories received from other people stay out of my dynamic', async () => {
    vi.mocked(storyApi.resonanceFeed).mockResolvedValue({
      items: [viewerItem()],
      next_cursor: null,
    })
    renderPage()

    expect(await screen.findByText('还没有发布故事')).toBeInTheDocument()
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
    expect(storyApi.publishedWork).not.toHaveBeenCalled()
  })

  test('collections tab shows 他们的故事 and hides the old copy', async () => {
    vi.mocked(storyApi.collections).mockResolvedValue({
      items: [
        {
          owner: { id: 8, nickname: '阿禾', avatar_url: '/characters/main/p02.webp' },
          story_count: 18,
          latest_published_at: '2026-08-09T09:00:00+00:00',
          latest_work: {
            id: 20,
            title: '雨后散步',
            style: 'watercolor',
            assets: [{ id: 1, ordinal: 0, asset_type: 'text', url: null, asset_id: null, text: '路灯下面有一小片水光' }],
          },
        },
      ],
      next_cursor: null,
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('tab', { name: '收录' }))
    expect(await screen.findByRole('heading', { name: '他们的故事' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /阿禾的故事/ })).toHaveTextContent('阿禾的故事')
    expect(screen.getByRole('img', { name: '阿禾' })).toHaveAttribute('src', '/characters/main/p02.webp')
    expect(screen.queryByText('18 个故事')).not.toBeInTheDocument()
    expect(screen.getByText(/水彩风/)).toBeInTheDocument()
    expect(screen.getByText('雨后散步')).toBeInTheDocument()
    expect(screen.queryByText('关心的人的故事本')).not.toBeInTheDocument()
  })

  test('collection detail 404 returns to people list with an unavailable notice', async () => {
    vi.mocked(storyApi.collections).mockResolvedValue({
      items: [
        {
          owner: { id: 8, nickname: '阿禾', avatar_url: null },
          story_count: 1,
          latest_published_at: '2026-08-09T09:00:00+00:00',
          latest_work: null,
        },
      ],
      next_cursor: null,
    })
    const { ApiError } = await import('../../api/client')
    vi.mocked(storyApi.collection).mockRejectedValue(new ApiError(404, 'not found'))
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('tab', { name: '收录' }))
    await user.click(await screen.findByRole('button', { name: /阿禾的故事/ }))

    expect(await screen.findByRole('heading', { name: '他们的故事' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('这个故事已不可见')
    expect(screen.getByRole('button', { name: /阿禾的故事/ })).toBeInTheDocument()
  })

  test('empty collections show the guidance copy', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('tab', { name: '收录' }))
    expect(await screen.findByText('别人发给你看的故事会出现在这里')).toBeInTheDocument()
  })

  test('opening a person loads their works desc and supports asc reload', async () => {
    vi.mocked(storyApi.collections).mockResolvedValue({
      items: [
        {
          owner: { id: 8, nickname: '阿禾', avatar_url: null },
          story_count: 2,
          latest_published_at: '2026-08-09T09:00:00+00:00',
          latest_work: null,
        },
      ],
      next_cursor: null,
    })
    vi.mocked(storyApi.collection).mockResolvedValue({
      owner: { id: 8, nickname: '阿禾', avatar_url: null },
      items: [viewerItem()],
      next_cursor: null,
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('tab', { name: '收录' }))
    await user.click(await screen.findByRole('button', { name: /阿禾的故事/ }))

    await waitFor(() =>
      expect(storyApi.collection).toHaveBeenCalledWith(8, { order: 'desc', cursor: null }),
    )
    expect(await screen.findByRole('heading', { name: '阿禾的故事' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '从最早开始' }))
    await waitFor(() =>
      expect(storyApi.collection).toHaveBeenCalledWith(8, { order: 'asc', cursor: null }),
    )
  })

  test('clicking a collected work opens only the safe published detail', async () => {
    vi.mocked(storyApi.collections).mockResolvedValue({
      items: [
        {
          owner: { id: 8, nickname: '阿禾', avatar_url: null },
          story_count: 1,
          latest_published_at: '2026-08-09T09:00:00+00:00',
          latest_work: null,
        },
      ],
      next_cursor: null,
    })
    vi.mocked(storyApi.collection).mockResolvedValue({
      owner: { id: 8, nickname: '阿禾', avatar_url: null },
      items: [viewerItem()],
      next_cursor: null,
    })
    vi.mocked(storyApi.publishedWork).mockResolvedValue(viewerItem())
    const user = userEvent.setup()
    const { onOpenOwnStoryWork } = renderPage()

    await user.click(screen.getByRole('tab', { name: '收录' }))
    await user.click(await screen.findByRole('button', { name: /阿禾的故事/ }))
    await user.click(await screen.findByRole('button', { name: /阿禾的发布/ }))

    await waitFor(() => expect(storyApi.publishedWork).toHaveBeenCalledWith(2))
    expect(onOpenOwnStoryWork).not.toHaveBeenCalled()
  })
})
