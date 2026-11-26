import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import MotionComicWizard from './index'
import type { CompletedPicturebook } from '../../types'

vi.mock('../../api/client', () => ({
  filmFolderApi: {
    createMotionDraft: vi.fn(),
    getMotionDraft: vi.fn(),
    updateMotionDraft: vi.fn(),
  },
  picturebookVideoApi: {
    latest: vi.fn(async () => null),
    start: vi.fn(),
    get: vi.fn(),
    retry: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) { super(message) }
  },
}))

import { filmFolderApi } from '../../api/client'

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(filmFolderApi.createMotionDraft).mockImplementation(async data => ({
    id: 501,
    source_kind: data.source_kind,
    source_id: data.source_id,
    title: data.title ?? '',
    page_sequence: data.page_sequence,
    video_job_id: null,
    created_at: 't',
    updated_at: 't',
  }))
  vi.mocked(filmFolderApi.updateMotionDraft).mockImplementation(
    async (id, data) => ({
      id,
      source_kind: 'work',
      source_id: 42,
      title: '',
      page_sequence: data.page_sequence ?? [],
      video_job_id: null,
      created_at: 't',
      updated_at: 't2',
    }),
  )
})

function page(pageIndex: number, overrides: Partial<CompletedPicturebook['pages'][number]> = {}) {
  return {
    page_index: pageIndex,
    image_url: `/media/page-${pageIndex}.png`,
    caption: pageIndex === 0 ? '封面' : `正文第 ${pageIndex} 页`,
    asset_id: `asset-${pageIndex}`,
    ...overrides,
  }
}

function fullPages(overrides: Partial<CompletedPicturebook['pages'][number]>[] = []) {
  return Array.from({ length: 9 }, (_, index) => page(index, overrides[index] ?? {}))
}

function book(
  sourceKind: CompletedPicturebook['source_kind'],
  sourceId: number,
  title: string,
  overrides: Partial<CompletedPicturebook> = {},
): CompletedPicturebook {
  return {
    source_kind: sourceKind,
    source_id: sourceId,
    title,
    source_start_date: '2026-08-01',
    source_end_date: '2026-08-08',
    start_date: '2026-08-01',
    end_date: '2026-08-08',
    date: '2026-08-08',
    style: 'watercolor',
    cover_url: `/covers/${sourceKind}-${sourceId}.png`,
    total_pages: 9,
    ready_pages: 9,
    pages: fullPages(),
    created_at: '2026-08-08T10:00:00Z',
    updated_at: '2026-08-08T10:00:00Z',
    ...overrides,
  }
}

const completedWork = book('canonical_work', 42, '暑假完整绘本')
const completedLegacyWithSameId = book('historical_job', 42, '旧版完整绘本', {
  source_start_date: '2026-07-01',
  source_end_date: '2026-07-03',
  style: 'pixel',
})
const partialReady = book('canonical_work', 43, '缺页绘本', {
  ready_pages: 8,
  pages: fullPages().slice(0, 8),
})
const failedLike = book('historical_job', 44, '失败遗留任务', {
  ready_pages: 7,
  pages: fullPages([{ image_url: null }]),
})
const coverOnly = book('canonical_work', 45, '只有封面', {
  ready_pages: 1,
  pages: [page(0)],
})

function renderWizard(props: Partial<React.ComponentProps<typeof MotionComicWizard>> = {}) {
  const loadPicturebooks = vi.fn().mockResolvedValue([
    completedWork,
    completedLegacyWithSameId,
    partialReady,
    failedLike,
    coverOnly,
  ])
  const writeSpies = {
    createDraft: vi.fn(),
    saveWork: vi.fn(),
    startMotionComic: vi.fn(),
    deleteDraft: vi.fn(),
  }
  const onBack = vi.fn()

  render(
    <MotionComicWizard
      loadPicturebooks={loadPicturebooks}
      onBack={onBack}
      writeSpies={writeSpies}
      {...props}
    />,
  )
  return { loadPicturebooks, onBack, writeSpies }
}

describe('MotionComicWizard', () => {
  test('lists only completed nine-page picturebooks with stable source keys and metadata', async () => {
    renderWizard()

    expect(await screen.findByRole('button', { name: /暑假完整绘本/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /旧版完整绘本/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /缺页绘本/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /失败遗留任务/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /只有封面/ })).not.toBeInTheDocument()

    const work = screen.getByTestId('source-canonical_work-42')
    expect(work).toHaveTextContent('暑假完整绘本')
    expect(work).toHaveTextContent('2026-08-01 - 2026-08-08')
    expect(work).toHaveTextContent('watercolor')
    expect(within(work).getByRole('img', { name: '暑假完整绘本 封面' })).toHaveAttribute(
      'src',
      '/covers/canonical_work-42.png',
    )

    const legacy = screen.getByTestId('source-historical_job-42')
    expect(legacy).toHaveTextContent('旧版完整绘本')
    expect(legacy).toHaveTextContent('2026-07-01 - 2026-07-03')
    expect(legacy).toHaveTextContent('pixel')
  })

  test('does not call write callbacks while selecting, ordering, previewing, and returning', async () => {
    const user = userEvent.setup()
    const { onBack, writeSpies } = renderWizard()

    await user.click(await screen.findByRole('button', { name: /旧版完整绘本/ }))
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('checkbox', { name: /正文第 2 页/ }))
    await user.click(screen.getByRole('button', { name: '将第 3 页左移' }))
    await user.click(screen.getByRole('button', { name: '预览序列' }))
    await user.click(screen.getByRole('button', { name: '返回编辑' }))
    await user.click(screen.getByRole('button', { name: '返回选择绘本' }))
    expect(screen.getByRole('button', { name: /旧版完整绘本/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '返回故事' }))

    expect(onBack).toHaveBeenCalledOnce()
    expect(Object.values(writeSpies).every(spy => spy.mock.calls.length === 0)).toBe(true)
  })

  test('selects only body pages 1-8 by default and keeps at least one deterministic selection', async () => {
    const user = userEvent.setup()
    renderWizard({ sources: [completedWork], loadPicturebooks: undefined })

    await user.click(screen.getByRole('button', { name: /暑假完整绘本/ }))
    await user.click(screen.getByRole('button', { name: '下一步' }))

    expect(screen.queryByRole('checkbox', { name: /封面/ })).not.toBeInTheDocument()
    const pages = screen.getAllByRole('checkbox')
    expect(pages.map(item => item.getAttribute('aria-checked'))).toEqual(Array(8).fill('true'))

    for (const item of pages.slice(1)) {
      await user.click(item)
    }
    expect(screen.getByRole('checkbox', { name: /正文第 1 页/ })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /正文第 4 页/ }))
    await user.click(screen.getByRole('checkbox', { name: /正文第 2 页/ }))

    const sequence = within(screen.getByLabelText('已选页面顺序')).getAllByRole('listitem')
    expect(sequence.map(item => item.textContent)).toEqual([
      expect.stringContaining('第 1 页'),
      expect.stringContaining('第 2 页'),
      expect.stringContaining('第 4 页'),
    ])
  })

  test('provides accessible ordering icon buttons with disabled boundaries', async () => {
    const user = userEvent.setup()
    renderWizard({ sources: [completedWork], loadPicturebooks: undefined })

    await user.click(screen.getByRole('button', { name: /暑假完整绘本/ }))
    await user.click(screen.getByRole('button', { name: '下一步' }))

    const firstLeft = screen.getByRole('button', { name: '将第 1 页左移' })
    const firstRight = screen.getByRole('button', { name: '将第 1 页右移' })
    const lastRight = screen.getByRole('button', { name: '将第 8 页右移' })

    expect(firstLeft).toBeDisabled()
    expect(firstLeft).toHaveAttribute('title', '将第 1 页左移')
    expect(firstRight).toHaveAttribute('title', '将第 1 页右移')
    expect(lastRight).toBeDisabled()

    await user.click(firstRight)
    const sequence = within(screen.getByLabelText('已选页面顺序')).getAllByRole('listitem')
    expect(sequence[0]).toHaveTextContent('第 2 页')
    expect(sequence[1]).toHaveTextContent('第 1 页')
  })

  test('previews selected image sequence without implying generation and preserves state on back', async () => {
    const user = userEvent.setup()
    renderWizard({ sources: [completedWork], loadPicturebooks: undefined })

    await user.click(screen.getByRole('button', { name: /暑假完整绘本/ }))
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: '将第 1 页右移' }))
    await user.click(screen.getByRole('checkbox', { name: /正文第 8 页/ }))
    await user.click(screen.getByRole('button', { name: '预览序列' }))

    const preview = screen.getByLabelText('漫剧片段预览')
    const frames = within(preview).getAllByRole('listitem')
    expect(frames[0]).toHaveTextContent('序号 1')
    expect(frames[0]).toHaveTextContent('正文第 2 页')
    expect(within(frames[0]).getByRole('img', { name: '序号 1：正文第 2 页' })).toHaveAttribute(
      'src',
      '/media/page-2.png',
    )
    expect(screen.queryByText(/已生成|生成完成/)).not.toBeInTheDocument()
    // 预览页现在直接接上生成入口，页序就是这里排出来的顺序。
    expect(await screen.findByRole('button', { name: '生成绘本视频' })).toBeEnabled()
    expect(screen.queryByText(/把绘本接成一段连续的小片子/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '返回编辑' }))

    expect(screen.getByText('暑假完整绘本')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /正文第 8 页/ })).toHaveAttribute('aria-checked', 'false')
    const sequence = within(screen.getByLabelText('已选页面顺序')).getAllByRole('listitem')
    expect(sequence[0]).toHaveTextContent('第 2 页')
    expect(sequence[1]).toHaveTextContent('第 1 页')
  })

  test('loads sources through the injected read-only loader', async () => {
    const { loadPicturebooks } = renderWizard({ sources: undefined })

    await waitFor(() => expect(loadPicturebooks).toHaveBeenCalledOnce())
    expect(await screen.findByRole('button', { name: /暑假完整绘本/ })).toBeInTheDocument()
  })
})

describe('MotionComicWizard draft autosave', () => {
  test('selecting a source creates a draft with the body page order', async () => {
    renderWizard()
    await screen.findByTestId('source-canonical_work-42')
    await userEvent.click(screen.getByTestId('source-canonical_work-42'))

    await waitFor(() => expect(filmFolderApi.createMotionDraft).toHaveBeenCalled())
    expect(vi.mocked(filmFolderApi.createMotionDraft).mock.calls[0][0]).toEqual({
      source_kind: 'work',
      source_id: 42,
      title: '暑假完整绘本',
      page_sequence: [1, 2, 3, 4, 5, 6, 7, 8],
    })
  })

  test('page toggle persists the exact sequence through the draft api', async () => {
    renderWizard()
    await screen.findByTestId('source-canonical_work-42')
    await userEvent.click(screen.getByTestId('source-canonical_work-42'))
    await waitFor(() => expect(filmFolderApi.createMotionDraft).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    // 在编辑页取消第 5 页的选择。
    await userEvent.click(screen.getByRole('checkbox', { name: /第 5 页/ }))

    await waitFor(() => expect(filmFolderApi.updateMotionDraft).toHaveBeenCalled())
    expect(vi.mocked(filmFolderApi.updateMotionDraft).mock.calls.slice(-1)[0]).toEqual([
      501,
      { page_sequence: [1, 2, 3, 4, 6, 7, 8] },
    ])
  })

  test('reopening with draftId restores source and order', async () => {
    vi.mocked(filmFolderApi.getMotionDraft).mockResolvedValue({
      id: 88,
      source_kind: 'work',
      source_id: 42,
      title: '暑假完整绘本',
      page_sequence: [3, 1, 2],
      video_job_id: null,
      created_at: 't',
      updated_at: 't',
    })
    renderWizard({ draftId: 88 })
    // 恢复后直接进入编辑页,顺序来自草稿。
    await screen.findByText('序列')
    await waitFor(() => expect(filmFolderApi.getMotionDraft).toHaveBeenCalledWith(88))
    const orderItems = screen.getByRole('list', { name: '已选页面顺序' })
    const labels = within(orderItems).getAllByText(/^第 \d 页$/).map(node => node.textContent)
    expect(labels).toEqual(['第 3 页', '第 1 页', '第 2 页'])
  })
})
