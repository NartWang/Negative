import { beforeEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import UnfinishedWorks from './index'
import type { UnfinishedMotionComic, UnfinishedPicturebook } from '../../types'

vi.mock('../../api/client', () => ({
  filmFolderApi: {
    unfinishedPicturebooks: vi.fn(),
    unfinishedMotionComics: vi.fn(),
    deletePicturebook: vi.fn(),
    deleteMotionDraft: vi.fn(),
  },
}))

import { filmFolderApi } from '../../api/client'

const picturebookItems: UnfinishedPicturebook[] = [
  {
    id: 42, job_id: null, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
    title: '未完成的绘本', display_start_date: '2026-08-08',
    display_end_date: '2026-08-08', error: null, updated_at: 't1',
  },
  {
    id: 101, job_id: 201, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
    title: '失败的绘本', display_start_date: '2026-08-08',
    display_end_date: '2026-08-08', error: '生成过程出错了，可以重试', updated_at: 't3',
  },
  {
    id: 9, job_id: 9, source_kind: 'historical_job', work_kind: null,
    title: '2026-08-07 绘本', display_start_date: '2026-08-07',
    display_end_date: '2026-08-07', error: '生成过程出错了，可以重试',
    updated_at: 't2',
  },
]

const motionItems: UnfinishedMotionComic[] = [
  {
    id: 3, source_kind: 'work', source_id: 42, title: '晚霞漫剧',
    video_job_id: null, status: 'draft', error: null, updated_at: 't1',
  },
  {
    id: 4, source_kind: 'work', source_id: 42, title: '',
    video_job_id: 501, status: 'failed', error: '有 2 段没生成成功，可以重试这几段',
    updated_at: 't2',
  },
]

function picturebookProps(overrides = {}) {
  return {
    medium: 'picturebook' as const,
    onBack: vi.fn(),
    onOpenPicturebook: vi.fn(),
    onRetryPicturebook: vi.fn(async () => undefined),
    onOpenMotionDraft: vi.fn(),
    onRetryMotionComic: vi.fn(async () => undefined),
    ...overrides,
  }
}

function motionProps(overrides = {}) {
  return {
    medium: 'motion_comic' as const,
    onBack: vi.fn(),
    onOpenPicturebook: vi.fn(),
    onRetryPicturebook: vi.fn(async () => undefined),
    onOpenMotionDraft: vi.fn(),
    onRetryMotionComic: vi.fn(async () => undefined),
    ...overrides,
  }
}

describe('UnfinishedWorks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(filmFolderApi.unfinishedPicturebooks).mockResolvedValue({
      items: picturebookItems,
    })
    vi.mocked(filmFolderApi.unfinishedMotionComics).mockResolvedValue({
      items: motionItems,
    })
    vi.mocked(filmFolderApi.deletePicturebook).mockResolvedValue(undefined)
    vi.mocked(filmFolderApi.deleteMotionDraft).mockResolvedValue(undefined)
  })

  test('picturebook list loads only the picturebook endpoint and no diary drafts', async () => {
    render(<UnfinishedWorks {...picturebookProps()} />)
    await screen.findByText('未完成的绘本')
    expect(filmFolderApi.unfinishedPicturebooks).toHaveBeenCalledTimes(1)
    expect(filmFolderApi.unfinishedMotionComics).not.toHaveBeenCalled()
    expect(screen.queryByText(/日记草稿/)).toBeNull()
  })

  test('canonical picturebook failures open the wizard by work id, never job id', async () => {
    const onOpen = vi.fn()
    render(<UnfinishedWorks {...picturebookProps({ onOpenPicturebook: onOpen })} />)
    const rows = await screen.findAllByRole('button', { name: '继续创作' })
    fireEvent.click(rows[1]!) // 失败的绘本:id=101, job_id=201
    expect(onOpen).toHaveBeenCalledWith(
      expect.objectContaining({ id: 101, job_id: 201 }),
    )
  })

  test('historical failures render an explicit retry action bound to the job id', async () => {
    const onRetry = vi.fn(async () => undefined)
    const onOpen = vi.fn()
    render(<UnfinishedWorks {...picturebookProps({
      onRetryPicturebook: onRetry,
      onOpenPicturebook: onOpen,
    })} />)
    const retry = await screen.findByRole('button', { name: '重试绘本' })
    fireEvent.click(retry)
    expect(onRetry).toHaveBeenCalledWith(
      expect.objectContaining({ id: 9, job_id: 9, source_kind: 'historical_job' }),
    )
    expect(onOpen).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: '重试绘本' })).toBeTruthy())
  })

  test('a retry is single-flight and shows 正在重试 while in flight', async () => {
    let resolveRetry: (() => void) | null = null
    const onRetry = vi.fn(() => new Promise<void>(resolve => { resolveRetry = resolve }))
    render(<UnfinishedWorks {...picturebookProps({ onRetryPicturebook: onRetry })} />)

    const retry = await screen.findByRole('button', { name: '重试绘本' })
    fireEvent.click(retry)
    fireEvent.click(screen.getByRole('button', { name: '正在重试' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '正在重试' })).toBeDisabled()

    await (async () => resolveRetry!())()
    await waitFor(() => expect(screen.getByRole('button', { name: '重试绘本' })).toBeTruthy())
  })

  test('a failed retry keeps the row and shows the stable safe feedback', async () => {
    const onRetry = vi.fn(async () => { throw new Error('503 upstream') })
    render(<UnfinishedWorks {...picturebookProps({ onRetryPicturebook: onRetry })} />)

    fireEvent.click(await screen.findByRole('button', { name: '重试绘本' }))
    expect(await screen.findByText('重试没能开始，请稍后再试')).toBeTruthy()
    expect(screen.getByText('2026-08-07 绘本')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试绘本' })).not.toBeDisabled()
  })

  test('motion drafts open the wizard; failed ones expose an explicit retry', async () => {
    const onOpenDraft = vi.fn()
    const onRetry = vi.fn(async () => undefined)
    render(<UnfinishedWorks {...motionProps({
      onOpenMotionDraft: onOpenDraft,
      onRetryMotionComic: onRetry,
    })} />)

    fireEvent.click(await screen.findByRole('button', { name: '继续编辑' }))
    expect(onOpenDraft).toHaveBeenCalledWith(expect.objectContaining({ id: 3, status: 'draft' }))
    expect(onRetry).not.toHaveBeenCalled()

    expect(screen.getByText('有 2 段没生成成功，可以重试这几段')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重试漫剧' }))
    expect(onRetry).toHaveBeenCalledWith(
      expect.objectContaining({ id: 4, video_job_id: 501, status: 'failed' }),
    )
    expect(onOpenDraft).toHaveBeenCalledTimes(1)
  })

  test('a failed motion retry keeps the page and row with safe feedback', async () => {
    const onRetry = vi.fn(async () => { throw new Error('network down') })
    render(<UnfinishedWorks {...motionProps({ onRetryMotionComic: onRetry })} />)

    fireEvent.click(await screen.findByRole('button', { name: '重试漫剧' }))
    expect(await screen.findByText('重试没能开始，请稍后再试')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试漫剧' })).toBeTruthy()
    // 行仍可见。
    expect(screen.getByText('未命名漫剧')).toBeTruthy()
  })

  test('deletes an unfinished picturebook only after confirmation', async () => {
    render(<UnfinishedWorks {...picturebookProps()} />)
    fireEvent.click(await screen.findByRole('button', { name: '删除《未完成的绘本》' }))

    expect(screen.getByRole('dialog', { name: '删除这条创作？' })).toBeTruthy()
    expect(filmFolderApi.deletePicturebook).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(filmFolderApi.deletePicturebook).toHaveBeenCalledWith(
      'canonical_work', 42,
    ))
    await waitFor(() => expect(screen.queryByText('未完成的绘本')).toBeNull())
  })

  test('deletes an unfinished motion draft only after confirmation', async () => {
    render(<UnfinishedWorks {...motionProps()} />)
    fireEvent.click(await screen.findByRole('button', { name: '删除《晚霞漫剧》' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(filmFolderApi.deleteMotionDraft).toHaveBeenCalledWith(3))
    await waitFor(() => expect(screen.queryByText('晚霞漫剧')).toBeNull())
  })
})
