import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import StoryWork from './index'
import { storyApi, storyWorksApi } from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { StoryWorkDetail } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      getAudience: vi.fn(),
      replaceAudience: vi.fn(),
      publish: vi.fn(),
    },
    storyWorksApi: {
      ...actual.storyWorksApi,
      get: vi.fn(),
      duplicate: vi.fn(),
    },
  }
})

const work: StoryWorkDetail = {
  id: 801,
  owner_user_id: 7,
  kind: 'time_story',
  status: 'ready',
  stage: 'ready',
  title: '八月第一周',
  style: 'watercolor',
  selected_segments: [],
  source_diary_ids: [31, 32],
  source_diaries: [],
  source_snapshot: {
    diaries: [
      { id: 31, date: '2026-08-03', status: 'confirmed', body: '周一正文' },
      { id: 32, date: '2026-08-05', status: 'draft', body: '周三草稿' },
    ],
  },
  source_snapshot_hash: 'hash',
  source_start_date: '2026-08-03',
  source_end_date: '2026-08-09',
  display_start_date: '2026-08-03',
  display_end_date: '2026-08-09',
  storyline_candidates: [],
  selected_storyline_id: 'line-1',
  narrative_text: '这一周，我先出发，然后慢慢收束。',
  generation_error: null,
  active_picturebook_job: null,
  picturebook_job: null,
  pages: [
    {
      page_index: 0,
      image_id: 'cover',
      image_url: 'https://example.test/cover.jpg',
      caption: '封面',
      status: 'ready',
      error: null,
    },
    {
      page_index: 1,
      image_id: 'page-1',
      image_url: 'https://example.test/page.jpg',
      caption: '慢慢收束',
      status: 'ready',
      error: null,
    },
  ],
  created_at: '2026-08-08T10:00:00Z',
  updated_at: '2026-08-08T10:00:00Z',
}

function renderPage(props: Partial<React.ComponentProps<typeof StoryWork>> = {}) {
  const onBack = vi.fn()
  const onOpenDraft = vi.fn()
  render(
    <ToastProvider>
      <StoryWork workId={801} onBack={onBack} onOpenDraft={onOpenDraft} {...props} />
    </ToastProvider>,
  )
  return { onBack, onOpenDraft }
}

describe('StoryWork page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storyWorksApi.get).mockResolvedValue(work)
    vi.mocked(storyWorksApi.duplicate).mockResolvedValue({
      ...work,
      id: 802,
      status: 'draft',
      stage: 'narrative_editing',
    })
    vi.mocked(storyApi.getAudience).mockResolvedValue({ items: [] })
    vi.mocked(storyApi.replaceAudience).mockResolvedValue({ items: [] })
  })

  test('shows a completed range work with narrative and horizontal picturebook reader', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: '八月第一周' })).toBeInTheDocument()
    expect(screen.getByText('2026-08-03 - 2026-08-09')).toBeInTheDocument()
    expect(screen.getByText('这一周，我先出发，然后慢慢收束。')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '八月第一周' })).toBeInTheDocument()
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
  })

  test('duplicates a completed work into an editable draft', async () => {
    const user = userEvent.setup()
    const { onOpenDraft } = renderPage()

    await user.click(await screen.findByRole('button', { name: '编辑并重新生成' }))

    await waitFor(() => expect(storyWorksApi.duplicate).toHaveBeenCalledWith(801))
    expect(onOpenDraft).toHaveBeenCalledWith(802)
  })

  test('ready work shows a publish entry that opens the publish sheet', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: '发布到回响' }))

    expect(await screen.findByRole('dialog', { name: '发布到回响' })).toBeInTheDocument()
    expect(storyApi.getAudience).toHaveBeenCalledWith(801)
    expect(screen.queryByRole('button', { name: /可见范围/ })).not.toBeInTheDocument()
  })

  test('published work shows visibility entry instead of publish', async () => {
    const user = userEvent.setup()
    vi.mocked(storyWorksApi.get).mockResolvedValue({ ...work, status: 'published' })
    renderPage()

    await user.click(await screen.findByRole('button', { name: /已发布 · 可见范围/ }))

    expect(await screen.findByRole('dialog', { name: '可见范围' })).toBeInTheDocument()
    expect(storyApi.getAudience).toHaveBeenCalledWith(801)
    expect(screen.queryByRole('button', { name: '发布到回响' })).not.toBeInTheDocument()
  })

  test('publishing merges only the lifecycle status into the loaded work', async () => {
    const user = userEvent.setup()
    vi.mocked(storyApi.publish).mockResolvedValue({
      work: {
        id: 801,
        status: 'published',
        published_at: '2026-08-09T10:00:00+00:00',
        unpublished_at: null,
      },
      audience: { items: [] },
    })
    renderPage()

    await user.click(await screen.findByRole('button', { name: '发布到回响' }))
    await user.click(await screen.findByRole('button', { name: '发布 · 仅自己可见' }))

    // status flips to published, but the full detail (title, narrative, pages) stays
    expect(await screen.findByRole('heading', { name: '八月第一周' })).toBeInTheDocument()
    expect(screen.getByText('这一周，我先出发，然后慢慢收束。')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /已发布 · 可见范围/ })).toBeInTheDocument()
  })
})
