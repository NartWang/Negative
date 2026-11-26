import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import StoryDay from './index'
import { exportApi, storyApi } from '../../api/client'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      day: vi.fn(),
      getAudience: vi.fn(),
      replaceAudience: vi.fn(),
      publish: vi.fn(),
    },
    exportApi: {
      ...actual.exportApi,
      downloadDayPdf: vi.fn(),
    },
  }
})

const detail = {
  kind: 'day',
  date: '2026-08-08',
  start_date: '2026-08-08',
  end_date: '2026-08-08',
  title: '水边拍照的一天',
  summary: '上午完成安排，下午把照片和日记整理成故事。',
  cover_url: 'https://example.test/day-cover.jpg',
  content_types: ['photo', 'diary', 'picturebook', 'story'],
  timeline: [
    {
      id: 1,
      kind: 'schedule',
      clock: '09:00',
      date: '2026-08-08',
      title: '晨间散步',
      completed: true,
      feeling: '轻松',
    },
    {
      id: 2,
      kind: 'fragment',
      clock: '10:00',
      date: '2026-08-08',
      content: '桥边的光落在水面上。',
      photo_url: 'https://example.test/fragment.jpg',
      photo_asset_id: 'asset-fragment',
      photo_description: '桥边水面反光',
      mood_tag: '明亮',
      created_at: '2026-08-08T10:00:00Z',
    },
    {
      id: 3,
      kind: 'schedule',
      clock: '11:00',
      date: '2026-08-08',
      title: '写下观察',
      completed: false,
      feeling: '专注',
    },
    {
      id: 4,
      kind: 'schedule',
      clock: '',
      date: '2026-08-08',
      title: '随时整理书包',
      completed: false,
      feeling: null,
    },
  ],
  schedules: [],
  fragments: [],
  diaries: [{
    id: 18,
    date: '2026-08-08',
    text: '今天的片段已经串起来了。',
    draft_text: null,
    emotion_mode: null,
    status: 'confirmed',
    source: 'manual',
    images: [],
    created_at: '2026-08-08T11:30:00Z',
    confirmed_at: '2026-08-08T11:35:00Z',
  }],
  picturebooks: [{
    source_kind: 'canonical_work',
    source_id: 42,
    title: '水边拍照的一天',
    source_start_date: '2026-08-08',
    source_end_date: '2026-08-08',
    start_date: '2026-08-08',
    end_date: '2026-08-08',
    date: '2026-08-08',
    style: 'watercolor',
    cover_url: 'https://example.test/book-cover.jpg',
    total_pages: 2,
    created_at: '2026-08-08T12:00:00Z',
    updated_at: '2026-08-08T12:10:00Z',
    pages: [
      {
        page_index: 0,
        caption: '水边拍照的一天',
        image_url: 'https://example.test/book-cover.jpg',
      },
      {
        page_index: 1,
        caption: '桥边的光',
        image_url: 'https://example.test/page-1.jpg',
      },
    ],
  }],
  story_works: [{
    id: 42,
    owner_user_id: 7,
    source_diary_id: 18,
    date: '2026-08-08',
    title: '桥边的光',
    medium: 'picture_book',
    narrative_mode: 'warm',
    style: 'watercolor',
    selected_segments: ['桥边的光落在水面上。'],
    forbidden_content: null,
    status: 'ready',
    assets: [
      { id: 1, work_id: 42, ordinal: 0, asset_type: 'text', url: null, text: '一部短短的水边故事。' },
      { id: 2, work_id: 42, ordinal: 1, asset_type: 'image', url: 'https://example.test/work.jpg', text: null },
    ],
    created_at: '2026-08-08T12:30:00Z',
    updated_at: '2026-08-08T12:30:00Z',
  }],
  draft_count: 1,
}

describe('StoryDay detail page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storyApi.day).mockResolvedValue(detail as never)
    vi.mocked(storyApi.getAudience).mockResolvedValue({ items: [] })
    vi.mocked(storyApi.replaceAudience).mockResolvedValue({ items: [] })
    vi.mocked(exportApi.downloadDayPdf).mockResolvedValue(new Blob(['pdf']))
  })

  test('loads a day story and renders its cover, labels, timeline, diary, picturebook, and work controls', async () => {
    const user = userEvent.setup()
    const onBack = vi.fn()
    render(<StoryDay date="2026-08-08" onBack={onBack} />)

    expect(await screen.findByRole('heading', { level: 1, name: '水边拍照的一天' })).toBeInTheDocument()
    expect(storyApi.day).toHaveBeenCalledWith('2026-08-08')
    expect(screen.getAllByRole('img', { name: '水边拍照的一天' })[0]).toHaveAttribute(
      'src',
      'https://example.test/day-cover.jpg',
    )
    expect(screen.getAllByText('2026年8月8日')[0]).toBeInTheDocument()
    expect(screen.getByText('上午完成安排，下午把照片和日记整理成故事。')).toBeInTheDocument()
    const labels = within(screen.getByLabelText('内容类型'))
    expect(labels.getByText('照片')).toBeInTheDocument()
    expect(labels.getByText('日记')).toBeInTheDocument()
    expect(labels.getByText('绘本')).toBeInTheDocument()
    expect(labels.getByText('故事')).toBeInTheDocument()

    const timeline = within(screen.getByRole('list', { name: '当天时间线' })).getAllByRole('listitem')
    expect(timeline).toHaveLength(4)
    expect(timeline.map(item => item.textContent)).toEqual([
      expect.stringContaining('09:00'),
      expect.stringContaining('10:00'),
      expect.stringContaining('11:00'),
      expect.stringContaining('未定'),
    ])
    expect(timeline[0]).toHaveTextContent('晨间散步')
    expect(timeline[0]).toHaveTextContent('轻松')
    expect(timeline[1]).toHaveTextContent('桥边的光落在水面上。')
    expect(timeline[1]).not.toHaveTextContent('桥边水面反光')
    expect(timeline[1]).toHaveTextContent('明亮')
    expect(within(timeline[1]).getByRole('img', { name: '桥边的光落在水面上。' })).toHaveAttribute(
      'src',
      'https://example.test/fragment.jpg',
    )
    expect(timeline[2]).toHaveTextContent('写下观察')
    expect(timeline[2]).toHaveTextContent('未完成')
    expect(timeline[3]).toHaveTextContent('随时整理书包')

    const diary = screen.getByRole('article', { name: '日记 2026-08-08' })
    expect(diary).not.toHaveTextContent('草稿')
    expect(diary).toHaveTextContent('今天的片段已经串起来了。')

    const picturebook = screen.getByRole('article', { name: '绘本 水边拍照的一天' })
    expect(picturebook).toHaveTextContent('2 页')
    expect(picturebook).toHaveTextContent('watercolor')
    expect(picturebook).not.toHaveTextContent('undefined')
    expect(within(picturebook).getByRole('img', { name: '水边拍照的一天' })).toHaveAttribute(
      'src',
      'https://example.test/book-cover.jpg',
    )
    expect(within(picturebook).getByRole('button', { name: '打开绘本' })).toBeInTheDocument()

    const work = screen.getByRole('article', { name: '故事作品 桥边的光' })
    expect(work).toHaveTextContent('绘本')
    expect(work).toHaveTextContent('一部短短的水边故事。')
    const publishButton = within(work).getByRole('button', { name: '发布到回响' })
    await user.click(publishButton)

    await waitFor(() => expect(storyApi.getAudience).toHaveBeenCalledWith(42))
    expect(await screen.findByRole('dialog', { name: '发布到回响' })).toBeInTheDocument()

    vi.mocked(storyApi.publish).mockResolvedValue({
      work: { id: 42, status: 'published', published_at: '2026-08-09T10:00:00+00:00', unpublished_at: null },
      audience: { items: [] },
    })
    await user.click(screen.getByRole('button', { name: '发布 · 仅自己可见' }))
    await waitFor(() => expect(storyApi.publish).toHaveBeenCalledWith(42, []))
    // after publishing, the card flips to the visibility entry (sheet closed)
    expect(
      await within(work).findByRole('button', { name: /已发布 · 可见范围/ }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: '发布到回响' })).not.toBeInTheDocument()
  })

  test('a published work opens the visibility sheet', async () => {
    const user = userEvent.setup()
    vi.mocked(storyApi.day).mockResolvedValue({
      ...detail,
      story_works: [{ ...detail.story_works[0], status: 'published' }],
    } as never)
    render(
      <StoryDay date="2026-08-08" onBack={vi.fn()} onOpenPicturebook={vi.fn()} />,
    )

    const work = await screen.findByRole('article', { name: '故事作品 桥边的光' })
    const visibilityButton = await within(work).findByRole('button', { name: /已发布 · 可见范围/ })
    await user.click(visibilityButton)

    await waitFor(() => expect(storyApi.getAudience).toHaveBeenCalledWith(42))
    expect(await screen.findByRole('dialog', { name: '可见范围' })).toBeInTheDocument()
  })

  test('opens completed picturebooks in the horizontal reader flow', async () => {
    const user = userEvent.setup()
    const onOpenPicturebook = vi.fn()
    render(
      <StoryDay
        date="2026-08-08"
        onBack={vi.fn()}
        onOpenPicturebook={onOpenPicturebook}
      />,
    )

    const picturebook = await screen.findByRole('article', { name: '绘本 水边拍照的一天' })
    await user.click(within(picturebook).getByRole('button', { name: '打开绘本 水边拍照的一天' }))

    expect(onOpenPicturebook).toHaveBeenCalledWith(
      '水边拍照的一天',
      [
        expect.objectContaining({ page_index: 0, caption: '水边拍照的一天' }),
        expect.objectContaining({ page_index: 1, caption: '桥边的光' }),
      ],
    )

    onOpenPicturebook.mockClear()
    await user.click(within(picturebook).getByRole('button', { name: '打开绘本' }))

    expect(onOpenPicturebook).toHaveBeenCalledWith(
      '水边拍照的一天',
      [
        expect.objectContaining({ page_index: 0 }),
        expect.objectContaining({ page_index: 1 }),
      ],
    )
  })

  test('returns to the previous view through the back button', async () => {
    const user = userEvent.setup()
    const onBack = vi.fn()
    render(<StoryDay date="2026-08-08" onBack={onBack} />)

    await screen.findByRole('heading', { level: 1, name: '水边拍照的一天' })
    await user.click(screen.getByRole('button', { name: '返回故事列表' }))

    expect(onBack).toHaveBeenCalledOnce()
  })

  test('defensively labels draft diary content if the detail payload includes it', async () => {
    vi.mocked(storyApi.day).mockResolvedValue({
      ...detail,
      diaries: [{
        id: 19,
        date: '2026-08-08',
        text: '',
        draft_text: '还没确认，但今天的片段已经串起来了。',
        emotion_mode: null,
        status: 'draft',
        source: 'manual',
        images: [],
        created_at: '2026-08-08T11:30:00Z',
        confirmed_at: null,
      }],
    } as never)

    render(<StoryDay date="2026-08-08" onBack={vi.fn()} />)

    const diary = await screen.findByRole('article', { name: '日记 2026-08-08' })
    expect(diary).toHaveTextContent('草稿')
    expect(diary).toHaveTextContent('还没确认，但今天的片段已经串起来了。')
  })

  test('exports the day as a dated PDF download', async () => {
    const user = userEvent.setup()
    const blob = new Blob(['day-pdf'], { type: 'application/pdf' })
    if (!URL.createObjectURL) {
      Object.defineProperty(URL, 'createObjectURL', {
        configurable: true,
        value: vi.fn(),
      })
    }
    if (!URL.revokeObjectURL) {
      Object.defineProperty(URL, 'revokeObjectURL', {
        configurable: true,
        value: vi.fn(),
      })
    }
    const anchor = document.createElement('a')
    const click = vi.spyOn(anchor, 'click').mockImplementation(() => {})
    const originalCreateElement = document.createElement.bind(document)
    const createElement = vi.spyOn(document, 'createElement').mockImplementation(tagName => {
      if (tagName.toLowerCase() === 'a') return anchor
      return originalCreateElement(tagName)
    })
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:day-pdf')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.mocked(exportApi.downloadDayPdf).mockResolvedValue(blob)

    try {
      render(<StoryDay date="2026-08-08" onBack={vi.fn()} />)

      await screen.findByRole('heading', { level: 1, name: '水边拍照的一天' })
      await user.click(screen.getByRole('button', { name: '导出这一天为 PDF' }))

      await waitFor(() => expect(exportApi.downloadDayPdf).toHaveBeenCalledWith('2026-08-08'))
      expect(createObjectURL).toHaveBeenCalledWith(blob)
      expect(click).toHaveBeenCalledOnce()
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:day-pdf')
      expect(anchor.download).toBe('zhiji-2026-08-08.pdf')
    } finally {
      click.mockRestore()
      createElement.mockRestore()
      createObjectURL.mockRestore()
      revokeObjectURL.mockRestore()
    }
  })

  test('keeps page content visible when day PDF export fails', async () => {
    const user = userEvent.setup()
    vi.mocked(exportApi.downloadDayPdf).mockRejectedValue(new Error('network down'))

    render(<StoryDay date="2026-08-08" onBack={vi.fn()} />)

    expect(await screen.findByRole('heading', { level: 1, name: '水边拍照的一天' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '导出这一天为 PDF' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('导出失败，请稍后再试')
    expect(screen.getByRole('heading', { level: 1, name: '水边拍照的一天' })).toBeInTheDocument()
  })
})
