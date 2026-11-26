import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import Diary from './index'
import { storyApi } from '../../api/client'
import { DateProvider } from '../../contexts/DateContext'
import { ToastProvider } from '../../contexts/ToastContext'
import { getLocalDateStr } from '../../utils/date'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      chapters: vi.fn(),
    },
  }
})

const chapters = [
  {
    kind: 'day',
    date: '2026-08-08',
    start_date: '2026-08-08',
    end_date: '2026-08-08',
    title: '水边拍照的一天',
    summary: '下午整理了照片，也写完日记。',
    cover_url: 'https://example.test/august-cover.jpg',
    content_types: ['photo', 'diary', 'picturebook'],
  },
  {
    kind: 'day',
    date: '2026-08-04',
    start_date: '2026-08-04',
    end_date: '2026-08-04',
    title: '只有文字的记录',
    summary: '这一天没有封面图。',
    cover_url: null,
    content_types: ['diary'],
  },
  {
    kind: 'day',
    date: '2026-07-29',
    start_date: '2026-07-29',
    end_date: '2026-07-29',
    title: '七月收尾',
    summary: '把月底的小故事留住。',
    cover_url: null,
    content_types: ['story'],
  },
] as const

function renderDiary(
  onOpenCreateMenu = vi.fn(),
  onOpenDay = vi.fn(),
  onOpenDrafts = vi.fn(),
  onOpenStoryWork = vi.fn(),
  onOpenLegacyWeekly = vi.fn(),
) {
  render(
    <DateProvider>
      <ToastProvider>
        <Diary
          userId={1}
          onOpenCreateMenu={onOpenCreateMenu}
          onOpenDay={onOpenDay}
          onOpenStoryWork={onOpenStoryWork}
          onOpenLegacyWeekly={onOpenLegacyWeekly}
          onOpenDrafts={onOpenDrafts}
        />
      </ToastProvider>
    </DateProvider>,
  )
  return { onOpenCreateMenu, onOpenDay, onOpenDrafts, onOpenStoryWork, onOpenLegacyWeekly }
}

describe('Diary monthly chapters', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storyApi.chapters).mockResolvedValue({ items: [...chapters], draft_count: 2 })
  })

  test('groups story days by month, keeps newest days first, and renders one card per day', async () => {
    renderDiary()

    expect(await screen.findByRole('heading', { name: '2026年8月' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '2026年7月' })).toBeInTheDocument()

    const cards = await screen.findAllByRole('article')
    expect(cards).toHaveLength(3)
    expect(cards.map(card => card.textContent)).toEqual([
      expect.stringContaining('8月8日'),
      expect.stringContaining('8月4日'),
      expect.stringContaining('7月29日'),
    ])

    expect(cards[0]).toHaveTextContent('照片')
    expect(cards[0]).toHaveTextContent('日记')
    expect(cards[0]).toHaveTextContent('绘本')
    expect(within(cards[0]).getByRole('img', { name: '水边拍照的一天' })).toHaveAttribute(
      'src',
      'https://example.test/august-cover.jpg',
    )

    expect(cards[1]).toHaveTextContent('只有文字的记录')
    expect(cards[1]).toHaveTextContent('这一天没有封面图。')
    expect(within(cards[1]).queryByRole('img')).not.toBeInTheDocument()
    expect(cards[1]).toHaveTextContent('8月4日')
    expect(cards[2]).toHaveTextContent('故事')
  })

  test('removes the legacy weekly banner and shelves while opening the create menu', async () => {
    const user = userEvent.setup()
    const onOpenCreateMenu = vi.fn()
    renderDiary(onOpenCreateMenu)

    await screen.findByRole('heading', { name: '2026年8月' })

    expect(screen.queryByRole('heading', { name: '作品架' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '草稿箱' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '已保存' })).not.toBeInTheDocument()
    expect(screen.queryByText('导出全部日记为 PDF')).not.toBeInTheDocument()
    expect(screen.queryByText(/周/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '创建故事' }))

    await waitFor(() => expect(onOpenCreateMenu).toHaveBeenCalledOnce())
    expect(onOpenCreateMenu).toHaveBeenCalledWith(getLocalDateStr())
  })

  test('uses one compact draft entry with the current draft count', async () => {
    const user = userEvent.setup()
    const onOpenDrafts = vi.fn()
    renderDiary(vi.fn(), vi.fn(), onOpenDrafts)

    await screen.findByRole('heading', { name: '2026年8月' })

    expect(screen.queryByRole('heading', { name: '草稿箱' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '打开草稿箱，2 篇草稿' }))

    expect(onOpenDrafts).toHaveBeenCalledOnce()
  })

  test('keeps the compact draft entry visible when the count is zero', async () => {
    const user = userEvent.setup()
    const onOpenDrafts = vi.fn()
    vi.mocked(storyApi.chapters).mockResolvedValueOnce({ items: [...chapters], draft_count: 0 })
    renderDiary(vi.fn(), vi.fn(), onOpenDrafts)

    await screen.findByRole('heading', { name: '2026年8月' })
    await user.click(screen.getByRole('button', { name: '打开草稿箱，0 篇草稿' }))

    expect(onOpenDrafts).toHaveBeenCalledOnce()
  })

  test('opens a story day from a monthly chapter card', async () => {
    const user = userEvent.setup()
    const onOpenDay = vi.fn()
    renderDiary(vi.fn(), onOpenDay)

    await user.click(await screen.findByRole('button', { name: /水边拍照的一天/ }))

    expect(onOpenDay).toHaveBeenCalledWith('2026-08-08')
  })

  test('opens a completed range work from a monthly chapter card', async () => {
    const user = userEvent.setup()
    const onOpenStoryWork = vi.fn()
    vi.mocked(storyApi.chapters).mockResolvedValueOnce({
      draft_count: 0,
      items: [{
        kind: 'range_work',
        source_kind: 'time_story',
        source_id: 808,
        start_date: '2026-08-03',
        end_date: '2026-08-09',
        title: '八月第一周',
        summary: '一整周的时光故事。',
        cover_url: null,
        content_types: ['story', 'picturebook'],
      }],
    })
    renderDiary(vi.fn(), vi.fn(), vi.fn(), onOpenStoryWork)

    await user.click(await screen.findByRole('button', { name: /八月第一周/ }))

    expect(onOpenStoryWork).toHaveBeenCalledWith(808)
  })

  test('opens a legacy weekly comic from a monthly range card', async () => {
    const user = userEvent.setup()
    const onOpenLegacyWeekly = vi.fn()
    vi.mocked(storyApi.chapters).mockResolvedValueOnce({
      draft_count: 0,
      items: [{
        kind: 'range_work',
        source_kind: 'legacy_weekly',
        source_id: 120,
        start_date: '2026-07-27',
        end_date: '2026-08-02',
        title: '七月最后一周',
        summary: '旧版周漫画。',
        cover_url: null,
        content_types: ['story', 'picturebook'],
      }],
    })
    renderDiary(vi.fn(), vi.fn(), vi.fn(), vi.fn(), onOpenLegacyWeekly)

    await user.click(await screen.findByRole('button', { name: /七月最后一周/ }))

    expect(onOpenLegacyWeekly).toHaveBeenCalledWith(120)
  })
})
