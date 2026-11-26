import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import StoryDrafts from './index'
import { diaryApi, storyWorksApi } from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { Diary, StoryWorkDetail } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    diaryApi: {
      ...actual.diaryApi,
      list: vi.fn(),
    },
    storyWorksApi: {
      ...actual.storyWorksApi,
      listDrafts: vi.fn(),
    },
  }
})

function diary(overrides: Partial<Diary>): Diary {
  return {
    id: 1,
    date: '2026-08-08',
    text: '',
    draft_text: '',
    emotion_mode: null,
    status: 'draft',
    source: 'manual',
    images: [],
    created_at: '2026-08-08T08:00:00Z',
    confirmed_at: null,
    ...overrides,
  }
}

function work(overrides: Partial<StoryWorkDetail>): StoryWorkDetail {
  return {
    id: 501,
    owner_user_id: 7,
    kind: 'daily_picturebook',
    status: 'draft',
    stage: 'narrative_confirmed',
    title: '8 月 8 日绘本草稿',
    style: 'watercolor',
    selected_segments: ['第一段'],
    source_diary_ids: [1],
    source_diaries: [],
    source_snapshot: { diaries: [] },
    source_snapshot_hash: 'hash',
    source_start_date: '2026-08-08',
    source_end_date: '2026-08-08',
    display_start_date: '2026-08-08',
    display_end_date: '2026-08-08',
    generation_error: null,
    active_picturebook_job: null,
    picturebook_job: null,
    pages: [],
    created_at: '2026-08-08T09:00:00Z',
    updated_at: '2026-08-08T09:00:00Z',
    ...overrides,
  }
}

function renderDrafts() {
  const onBack = vi.fn()
  const onOpenDiaryDraft = vi.fn()
  const onOpenStoryDraft = vi.fn()
  render(
    <ToastProvider>
      <StoryDrafts
        onBack={onBack}
        onOpenDiaryDraft={onOpenDiaryDraft}
        onOpenStoryDraft={onOpenStoryDraft}
      />
    </ToastProvider>,
  )
  return { onBack, onOpenDiaryDraft, onOpenStoryDraft }
}

describe('StoryDrafts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(diaryApi.list).mockResolvedValue([
      diary({ id: 11, date: '2026-08-08', draft_text: '今天还没写完的日记。' }),
      diary({ id: 14, date: '2026-08-05', draft_text: '', text: '只写在 text 里的草稿。' }),
      diary({ id: 12, date: '2026-08-07', draft_text: '   ' }),
      diary({ id: 13, date: '2026-08-06', status: 'confirmed', text: '已经完成的日记。', draft_text: null }),
    ])
    vi.mocked(storyWorksApi.listDrafts).mockResolvedValue({
      items: [
        work({ id: 501, title: '8 月 8 日绘本草稿', status: 'draft', stage: 'narrative_confirmed' }),
        work({ id: 502, title: '已经生成的绘本', status: 'ready', stage: 'ready' }),
        work({ id: 503, title: '历史失败作品', status: 'failed', stage: 'render_failed' }),
      ],
    })
  })

  test('shows only non-empty diary drafts and story works whose status is draft', async () => {
    renderDrafts()

    expect(await screen.findByRole('heading', { name: '草稿箱' })).toBeInTheDocument()

    const diaryGroup = screen.getByRole('region', { name: '日记草稿' })
    expect(within(diaryGroup).getByRole('button', { name: /2026-08-08/ })).toHaveTextContent('今天还没写完的日记。')
    expect(within(diaryGroup).getByRole('button', { name: /2026-08-05/ })).toHaveTextContent('只写在 text 里的草稿。')
    expect(within(diaryGroup).queryByText('2026-08-07')).not.toBeInTheDocument()
    expect(within(diaryGroup).queryByText('2026-08-06')).not.toBeInTheDocument()

    const storyGroup = screen.getByRole('region', { name: '故事草稿' })
    const storyDraft = within(storyGroup).getByRole('button', { name: /8 月 8 日绘本草稿/ })
    expect(storyDraft).toHaveTextContent('当日绘本')
    expect(storyDraft).toHaveTextContent('叙事已确认')
    expect(within(storyGroup).queryByText('已经生成的绘本')).not.toBeInTheDocument()
    expect(within(storyGroup).queryByText('历史失败作品')).not.toBeInTheDocument()
  })

  test('opens persisted diary dates and story work ids for resume', async () => {
    const user = userEvent.setup()
    const { onOpenDiaryDraft, onOpenStoryDraft } = renderDrafts()

    const diaryGroup = await screen.findByRole('region', { name: '日记草稿' })
    await user.click(within(diaryGroup).getByRole('button', { name: /2026-08-08/ }))
    expect(onOpenDiaryDraft).toHaveBeenCalledWith('2026-08-08')

    const storyGroup = screen.getByRole('region', { name: '故事草稿' })
    await user.click(within(storyGroup).getByRole('button', { name: /8 月 8 日绘本草稿/ }))
    expect(onOpenStoryDraft).toHaveBeenCalledWith(501, 'daily_picturebook')
  })

  test('keeps the page readable when both draft lists are empty', async () => {
    vi.mocked(diaryApi.list).mockResolvedValue([])
    vi.mocked(storyWorksApi.listDrafts).mockResolvedValue({ items: [] })

    renderDrafts()

    await waitFor(() => expect(diaryApi.list).toHaveBeenCalledWith({ status: 'draft' }))
    expect(await screen.findByText('还没有草稿')).toBeInTheDocument()
  })
})
