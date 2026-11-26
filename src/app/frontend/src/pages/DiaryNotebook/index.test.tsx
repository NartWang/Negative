import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import DiaryNotebook, { nearestNotebookIndex } from './index'
import { diaryApi } from '../../api/client'
import type { Diary, DiaryNotebookIndexEntry } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    diaryApi: {
      ...actual.diaryApi,
      notebookIndex: vi.fn(),
      notebookDetail: vi.fn(),
    },
  }
})

const entry = (diary_id: number, date: string): DiaryNotebookIndexEntry => ({ diary_id, date })

const diary = (overrides: Partial<Diary> = {}): Diary => ({
  id: 31,
  date: '2026-08-09',
  text: '今天的日记正文',
  draft_text: null,
  emotion_mode: null,
  status: 'confirmed',
  source: 'manual',
  images: [],
  created_at: '2026-08-09T08:00:00Z',
  confirmed_at: '2026-08-09T09:00:00Z',
  ...overrides,
})

const threeEntries = [
  entry(11, '2026-08-05'),
  entry(21, '2026-08-07'),
  entry(31, '2026-08-09'),
]

function mockIndex(items: DiaryNotebookIndexEntry[]) {
  vi.mocked(diaryApi.notebookIndex).mockResolvedValue({ items, total: items.length })
}

function mockDetails(map: Record<number, Diary>) {
  vi.mocked(diaryApi.notebookDetail).mockImplementation(async id => {
    const found = map[id]
    if (!found) throw new Error(`no fixture for ${id}`)
    return found
  })
}

function renderNotebook(initialDate = '2026-08-07') {
  const onBack = vi.fn()
  render(<DiaryNotebook initialDate={initialDate} onBack={onBack} />)
  return { onBack }
}

describe('nearestNotebookIndex', () => {
  const items = [
    entry(11, '2026-08-05'),
    entry(21, '2026-08-07'),
    entry(31, '2026-08-09'),
  ]

  test('exact date match returns that index', () => {
    expect(nearestNotebookIndex(items, '2026-08-07')).toBe(1)
  })

  test('tie distance prefers the earlier date', () => {
    // 2026-08-06 is 1 day from both 08-05 and 08-07 → earlier wins
    expect(nearestNotebookIndex(items, '2026-08-06')).toBe(0)
  })

  test('nearest by absolute day distance', () => {
    expect(nearestNotebookIndex(items, '2026-08-08')).toBe(1)
    expect(nearestNotebookIndex(items, '2026-08-04')).toBe(0)
  })

  test('target before all entries returns 0', () => {
    expect(nearestNotebookIndex(items, '2026-01-01')).toBe(0)
  })

  test('target after all entries returns the last index', () => {
    expect(nearestNotebookIndex(items, '2027-01-01')).toBe(2)
  })

  test('empty list returns -1', () => {
    expect(nearestNotebookIndex([], '2026-08-07')).toBe(-1)
  })
})

describe('DiaryNotebook', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('exact initialDate loads that diary detail and shows its text', async () => {
    mockIndex(threeEntries)
    mockDetails({
      11: diary({ id: 11, date: '2026-08-05', text: '五号的内容' }),
      21: diary({ id: 21, date: '2026-08-07', text: '七号的内容' }),
      31: diary({ id: 31, date: '2026-08-09', text: '九号的内容' }),
    })
    renderNotebook('2026-08-07')

    expect(await screen.findByText('七号的内容')).toBeInTheDocument()
    expect(diaryApi.notebookIndex).toHaveBeenCalledTimes(1)
    expect(diaryApi.notebookDetail).toHaveBeenCalledWith(21)
  })

  test('no exact date picks the nearest with ties preferring the earlier one', async () => {
    mockIndex(threeEntries)
    mockDetails({
      11: diary({ id: 11, date: '2026-08-05', text: '五号的内容' }),
      21: diary({ id: 21, date: '2026-08-07', text: '七号的内容' }),
      31: diary({ id: 31, date: '2026-08-09', text: '九号的内容' }),
    })
    renderNotebook('2026-08-06')

    expect(await screen.findByText('五号的内容')).toBeInTheDocument()
    expect(diaryApi.notebookDetail).toHaveBeenCalledWith(11)
  })

  test('empty index shows the empty state and a working back button, without page indicator', async () => {
    mockIndex([])
    const user = userEvent.setup()
    const { onBack } = renderNotebook()

    expect(await screen.findByText('还没有正式日记')).toBeInTheDocument()
    expect(screen.queryByText(/第 .* 篇/)).not.toBeInTheDocument()
    expect(diaryApi.notebookDetail).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '回到记录页' }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  test('index failure shows role alert with retry; retry reloads the index', async () => {
    vi.mocked(diaryApi.notebookIndex)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ items: threeEntries, total: threeEntries.length })
    mockDetails({
      11: diary({ id: 11, date: '2026-08-05', text: '五号的内容' }),
      21: diary({ id: 21, date: '2026-08-07', text: '七号的内容' }),
      31: diary({ id: 31, date: '2026-08-09', text: '九号的内容' }),
    })
    const user = userEvent.setup()
    renderNotebook('2026-08-07')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('七号的内容')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(diaryApi.notebookIndex).toHaveBeenCalledTimes(2)
  })

  test('after the current detail loads, prev and next details are prefetched; a prefetch failure keeps the page', async () => {
    mockIndex(threeEntries)
    vi.mocked(diaryApi.notebookDetail).mockImplementation(async id => {
      if (id === 21) return diary({ id: 21, date: '2026-08-07', text: '七号的内容' })
      if (id === 11) throw new Error('prefetch failure')
      return diary({ id: 31, date: '2026-08-09', text: '九号的内容' })
    })
    renderNotebook('2026-08-07')

    expect(await screen.findByText('七号的内容')).toBeInTheDocument()
    await waitFor(() => {
      const ids = vi.mocked(diaryApi.notebookDetail).mock.calls.map(([id]) => id)
      expect(ids).toContain(11)
      expect(ids).toContain(31)
    })
    // Prefetch rejection must not replace the current page
    expect(screen.getByText('七号的内容')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  test('page indicator shows 第 X / Y 篇 and updates after clicking 后一篇; boundaries disable buttons', async () => {
    mockIndex(threeEntries)
    mockDetails({
      11: diary({ id: 11, date: '2026-08-05', text: '五号的内容' }),
      21: diary({ id: 21, date: '2026-08-07', text: '七号的内容' }),
      31: diary({ id: 31, date: '2026-08-09', text: '九号的内容' }),
    })
    const user = userEvent.setup()
    renderNotebook('2026-08-07')

    expect(await screen.findByText('第 2 / 3 篇')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '前一篇' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '后一篇' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '后一篇' }))
    expect(await screen.findByText('九号的内容')).toBeInTheDocument()
    expect(screen.getByText('第 3 / 3 篇')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '后一篇' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '前一篇' }))
    expect(await screen.findByText('七号的内容')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '前一篇' }))
    expect(await screen.findByText('五号的内容')).toBeInTheDocument()
    expect(screen.getByText('第 1 / 3 篇')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '前一篇' })).toBeDisabled()
  })

  test('detail failure shows role alert with retry and keeps the index and page indicator', async () => {
    mockIndex(threeEntries)
    vi.mocked(diaryApi.notebookDetail)
      .mockRejectedValueOnce(new Error('offline'))
      .mockImplementation(async id => diary({ id, date: '2026-08-07', text: '恢复后的内容' }))
    const user = userEvent.setup()
    renderNotebook('2026-08-07')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    // Page indicator survives the detail failure
    expect(screen.getByText('第 2 / 3 篇')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('恢复后的内容')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('第 2 / 3 篇')).toBeInTheDocument()
  })

  test('image error falls back to the SafeImage placeholder while text, turning and indicator keep working', async () => {
    mockIndex(threeEntries)
    mockDetails({
      11: diary({ id: 11, date: '2026-08-05', text: '五号的内容' }),
      21: diary({
        id: 21,
        date: '2026-08-07',
        text: '带照片的日记',
        images: [{
          id: 5,
          diary_id: 21,
          style: 'watercolor',
          style_prompt: null,
          url: 'https://example.test/broken.jpg',
          asset_id: null,
          created_at: '2026-08-07T10:00:00Z',
          kept: 1,
        }],
      }),
      31: diary({ id: 31, date: '2026-08-09', text: '九号的内容' }),
    })
    const user = userEvent.setup()
    renderNotebook('2026-08-07')

    expect(await screen.findByText('带照片的日记')).toBeInTheDocument()
    const image = document.querySelector('.notebook-paper img') as HTMLImageElement
    expect(image).not.toBeNull()
    // Trigger the image error: SafeImage shows the neutral placeholder
    image.dispatchEvent(new Event('error'))
    expect(await screen.findByRole('img', { name: '照片暂时无法显示' })).toBeInTheDocument()

    // Text, page indicator and turning still work
    expect(screen.getByText('带照片的日记')).toBeInTheDocument()
    expect(screen.getByText('第 2 / 3 篇')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '后一篇' }))
    expect(await screen.findByText('九号的内容')).toBeInTheDocument()
  })
})
