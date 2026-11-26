import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import PublishSheet from './index'
import { storyApi } from '../../api/client'
import type { PublicationResult, StoryWork, WorkAudience } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      getAudience: vi.fn(),
      publish: vi.fn(),
    },
  }
})

const work = (overrides: Partial<StoryWork> = {}): StoryWork => ({
  id: 42,
  owner_user_id: 1,
  source_diary_id: null,
  title: '我的一页',
  medium: 'picture_book',
  narrative_mode: 'true_record',
  style: 'watercolor',
  selected_segments: ['今天很好'],
  forbidden_content: null,
  status: 'ready',
  assets: [],
  created_at: '2026-08-04T08:00:00Z',
  updated_at: '2026-08-04T08:00:00Z',
  ...overrides,
})

const audience = (
  subscription_id: number,
  selected: boolean,
  nickname = '阿禾',
): WorkAudience => ({
  id: 100 + subscription_id,
  subscription_id,
  owner_user_id: 1,
  subscriber_user_id: 99,
  status: 'active',
  selected,
  created_at: '2026-08-04T08:00:00Z',
  subscriber: { id: 99, nickname, avatar_url: null },
})

const publication = (overrides: Partial<PublicationResult['work']> = {}): PublicationResult => ({
  work: {
    id: 42,
    status: 'published',
    published_at: '2026-08-09T10:00:00+00:00',
    unpublished_at: null,
    ...overrides,
  },
  audience: { items: [] },
})

function renderSheet(onPublished = vi.fn()) {
  const onClose = vi.fn()
  render(<PublishSheet open work={work()} onClose={onClose} onPublished={onPublished} />)
  return { onClose, onPublished }
}

describe('PublishSheet first publication', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storyApi.getAudience).mockResolvedValue({ items: [] })
    vi.mocked(storyApi.publish).mockResolvedValue(publication())
  })

  test('author is always visible; empty selection publishes as self-only', async () => {
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, false), audience(9, false, '小蓝')],
    })
    const user = userEvent.setup()
    const { onPublished, onClose } = renderSheet()

    expect(await screen.findByText('我自己')).toBeInTheDocument()
    const button = screen.getByRole('button', { name: '发布 · 仅自己可见' })
    expect(button).toBeEnabled()
    await user.click(button)

    await waitFor(() => expect(storyApi.publish).toHaveBeenCalledWith(42, []))
    expect(onPublished).toHaveBeenCalledWith(publication().work)
    expect(onClose).toHaveBeenCalled()
  })

  test('selecting people updates the label and publishes with those ids', async () => {
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, false), audience(9, false, '小蓝')],
    })
    const user = userEvent.setup()
    renderSheet()

    await user.click(await screen.findByText('阿禾'))
    await user.click(screen.getByText('小蓝'))
    const button = screen.getByRole('button', { name: '发布 · 2 人可见' })
    await user.click(button)

    await waitFor(() => expect(storyApi.publish).toHaveBeenCalledWith(42, [7, 9]))
  })

  test('publish failure keeps the sheet open, retains the draft, and shows an alert', async () => {
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, false)],
    })
    vi.mocked(storyApi.publish).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    const { onClose, onPublished } = renderSheet()

    await user.click(await screen.findByText('阿禾'))
    await user.click(screen.getByRole('button', { name: '发布 · 1 人可见' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('发布失败，请重试')
    expect(onClose).not.toHaveBeenCalled()
    expect(onPublished).not.toHaveBeenCalled()
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true)
  })
})
