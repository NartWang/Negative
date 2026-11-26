import { beforeEach, describe, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import FilmFolder from './index'
import type {
  FilmFolderResponse,
  PicturebookJob,
  PicturebookVideoJob,
} from '../../types'

vi.mock('../../api/client', () => ({
  characterApi: { get: vi.fn(async () => { throw new Error('no character') }) },
  filmFolderApi: {
    picturebooks: vi.fn(),
    motionComics: vi.fn(),
    deletePicturebook: vi.fn(),
    timeStories: vi.fn(async () => ({ items: [] })),
  },
  picturebookApi: { get: vi.fn() },
  picturebookVideoApi: { get: vi.fn() },
  storyApi: { publish: vi.fn() },
  exportApi: {
    dayAvailability: vi.fn(async () => ({ has_diary: false, has_picturebooks: false })),
  },
}))

import { filmFolderApi, picturebookApi, picturebookVideoApi, storyApi } from '../../api/client'

function collection(partial: Partial<FilmFolderResponse> = {}): FilmFolderResponse {
  return {
    active_generation: null,
    unfinished_count: 0,
    items: [],
    ...partial,
  }
}

function runningActive(ready = 2, total = 9, id = 9) {
  return {
    id, stage: 'rendering', status: 'running', total, ready, updated_at: 't',
  }
}

function terminalPicturebook(partial: Partial<PicturebookJob> = {}): PicturebookJob {
  return {
    id: 9,
    diary_id: 1,
    work_id: 1,
    style: 'watercolor',
    status: 'done',
    stage: 'done',
    stage_label: '完成',
    error: null,
    total_pages: 9,
    ready_pages: 9,
    ...partial,
  } as PicturebookJob
}

function terminalVideo(partial: Partial<PicturebookVideoJob> = {}): PicturebookVideoJob {
  return {
    id: 5,
    picturebook_job_id: 9,
    work_id: 1,
    style: 'watercolor',
    status: 'done',
    stage: 'done',
    stage_label: '完成',
    error: null,
    include_cover: true,
    segment_duration: 2,
    ratio: '16:9',
    total_segments: 8,
    ...partial,
  } as PicturebookVideoJob
}

function flush(ms: number) {
  return act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function ariaNow(): number {
  return Number(screen.getByRole('progressbar').getAttribute('aria-valuenow'))
}

const props = {
  onCreateDailyPicturebook: vi.fn(),
  onCreateTimeStory: vi.fn(),
  onCreateMotionComic: vi.fn(),
  onContinue: vi.fn(),
  onOpenPicturebook: vi.fn(),
  onOpenMotionComic: vi.fn(),
}

describe('FilmFolder', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection())
    vi.mocked(filmFolderApi.motionComics).mockResolvedValue(collection())
  })

  test('initial tab loads picturebooks only, motion comics load on switch', async () => {
    render(<FilmFolder {...props} />)
    await waitFor(() => expect(filmFolderApi.picturebooks).toHaveBeenCalledTimes(1))
    expect(filmFolderApi.motionComics).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('tab', { name: '漫剧' }))
    await waitFor(() => expect(filmFolderApi.motionComics).toHaveBeenCalledTimes(1))
  })

  test('can reopen directly on the motion comic tab', async () => {
    render(<FilmFolder {...props} initialMedium="motion_comic" />)

    await waitFor(() => expect(filmFolderApi.motionComics).toHaveBeenCalledTimes(1))
    expect(filmFolderApi.picturebooks).not.toHaveBeenCalled()
    expect(screen.getByRole('tab', { name: '漫剧' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: '生成 AI 漫剧' })).toBeInTheDocument()
  })

  test('motion failures have a visible retry entry instead of disappearing', async () => {
    vi.mocked(filmFolderApi.motionComics).mockResolvedValue(collection({
      unfinished_count: 1,
    }))
    render(<FilmFolder {...props} initialMedium="motion_comic" />)

    const retryEntry = await screen.findByRole('button', {
      name: '继续生成 / 重试漫剧（1）',
    })
    fireEvent.click(retryEntry)
    expect(props.onContinue).toHaveBeenCalledWith('motion_comic')
  })

  test('hierarchy: tabs → progress → create → continue → collection', async () => {
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection({
      active_generation: runningActive(),
      unfinished_count: 3,
      items: [{
        id: 1, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
        title: '晚霞', display_start_date: '2026-08-08',
        display_end_date: '2026-08-08', cover_url: null,
        completed_at: '2026-08-08T13:00:00Z',
      }],
    }))
    const { container } = render(<FilmFolder {...props} />)
    await screen.findByText('晚霞')

    const order = [
      '.film-folder-tabs',
      '.character-progress',
      '.film-folder-create',
      '.film-folder-continue',
      '.monthly-collection',
    ].map(selector => container.querySelector(selector))
    for (const node of order) expect(node).not.toBeNull()
    for (let index = 1; index < order.length; index += 1) {
      const relation = order[index - 1]!.compareDocumentPosition(order[index]!)
      expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  test('create is blocked while active, other tab stays independent', async () => {
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection({
      active_generation: runningActive(),
    }))
    render(<FilmFolder {...props} />)
    await screen.findByRole('progressbar')

    const create = screen.getByRole('button', { name: '生成绘本' })
    expect(create).toBeDisabled()
    fireEvent.click(create)
    expect(props.onCreateDailyPicturebook).not.toHaveBeenCalled()

    // 切到漫剧:入口不被绘本任务阻塞。
    fireEvent.click(screen.getByRole('tab', { name: '漫剧' }))
    await waitFor(() => expect(filmFolderApi.motionComics).toHaveBeenCalled())
    const motionCreate = screen.getByRole('button', { name: '生成 AI 漫剧' })
    expect(motionCreate).not.toBeDisabled()
    fireEvent.click(motionCreate)
    expect(props.onCreateMotionComic).toHaveBeenCalled()
  })

  test('no active or unfinished state leaves no blank rows', async () => {
    const { container } = render(<FilmFolder {...props} />)
    await waitFor(() => expect(filmFolderApi.picturebooks).toHaveBeenCalled())
    expect(container.querySelector('.character-progress')).toBeNull()
    expect(container.querySelector('.film-folder-continue')).toBeNull()
  })

  test('picturebook card asks for confirmation before deleting', async () => {
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection({
      items: [{
        id: 8, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
        title: '八月九日的绘本', display_start_date: '2026-08-09',
        display_end_date: '2026-08-09', cover_url: null,
        completed_at: '2026-08-09T13:00:00Z',
      }],
    }))
    vi.mocked(filmFolderApi.deletePicturebook).mockResolvedValue(undefined)
    render(<FilmFolder {...props} />)

    fireEvent.click(await screen.findByRole('button', { name: '删除《八月九日的绘本》' }))
    expect(props.onOpenPicturebook).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: '删除这本绘本？' })).toBeInTheDocument()
    expect(filmFolderApi.deletePicturebook).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => {
      expect(filmFolderApi.deletePicturebook).toHaveBeenCalledWith('canonical_work', 8)
    })
  })

  test('an unpublished canonical picturebook can be published to resonance', async () => {
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection({
      items: [{
        id: 8, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
        title: '八月九日的绘本', display_start_date: '2026-08-09',
        display_end_date: '2026-08-09', cover_url: null,
        completed_at: '2026-08-09T13:00:00Z', published: false,
      }],
    }))
    vi.mocked(storyApi.publish).mockResolvedValue({} as never)
    render(<FilmFolder {...props} />)

    fireEvent.click(await screen.findByRole('button', { name: '发布到回响' }))
    await waitFor(() => expect(storyApi.publish).toHaveBeenCalledWith(8, []))
  })

  test('continue entry opens only when unfinished exist', async () => {
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection({
      unfinished_count: 2,
    }))
    render(<FilmFolder {...props} />)
    const entry = await screen.findByRole('button', { name: '继续创作（2）' })
    fireEvent.click(entry)
    expect(props.onContinue).toHaveBeenCalledWith('picturebook')
  })

  test('rendering picturebook animates above its floor but never past the next page milestone', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(collection({
        active_generation: runningActive(2, 9),
      }))
      render(<FilmFolder {...props} />)
      await flush(0)
      const realFloor = 20 + (2 / 9) * 80
      const thirdPage = 20 + (3 / 9) * 80
      expect(ariaNow()).toBe(Math.round(realFloor))

      await flush(10_000)
      const moved = ariaNow()
      expect(moved).toBeGreaterThan(Math.round(realFloor))
      expect(moved).toBeLessThanOrEqual(Math.round(thirdPage))
    } finally {
      vi.useRealTimers()
    }
  })

  test('a failed collection poll freezes the percentage; the next success resumes without regression', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(2, 9) }))
        .mockRejectedValueOnce(new Error('network down'))
        .mockResolvedValue(collection({ active_generation: runningActive(2, 9) }))
      render(<FilmFolder {...props} />)
      await flush(0)

      await flush(6_000)
      const frozen = ariaNow()

      // 轮询失败后百分比冻结:断线期间最多再走一个动画 tick。
      await flush(4_100)
      const afterFailure = ariaNow()
      await flush(2_000)
      expect(ariaNow() - afterFailure).toBeLessThanOrEqual(1)

      // 断线时长不计入动画:恢复后从冻结值继续,速率与冻结前一致——
      // 冻结窗口里动画走了 ~4.1s;恢复后 4.1s 的前进只允许是同等的
      // 健康动画速率,不回退、不补算断线的 6.1s、不跳跃到下一节点。
      const preOutageAdvance = afterFailure - frozen
      await flush(4_100)
      const resumed = ariaNow()
      expect(resumed).toBeGreaterThanOrEqual(afterFailure)
      expect(resumed - afterFailure).toBeLessThanOrEqual(preOutageAdvance + 2)
      expect(resumed).toBeLessThanOrEqual(Math.round(20 + (3 / 9) * 80))
    } finally {
      vi.useRealTimers()
    }
  })

  test('a lower real node never moves the avatar backwards', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(4, 9) }))
        .mockResolvedValue(collection({ active_generation: runningActive(3, 9) }))
      render(<FilmFolder {...props} />)
      await flush(0)
      await flush(2_000)
      const before = ariaNow()

      await flush(4_100)
      expect(ariaNow()).toBeGreaterThanOrEqual(before)
    } finally {
      vi.useRealTimers()
    }
  })

  test('a vanished active job confirmed done holds 100% for 800ms, then keeps the new collection item', async () => {
    vi.useFakeTimers()
    try {
      const finishedItems = [{
        id: 7, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
        title: '新绘本', display_start_date: '2026-08-09',
        display_end_date: '2026-08-09', cover_url: null,
        completed_at: '2026-08-09T01:00:00Z',
      }] as FilmFolderResponse['items']
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(4, 9) }))
        .mockResolvedValue(collection({ items: finishedItems }))
      vi.mocked(picturebookApi.get).mockResolvedValue(terminalPicturebook())

      const { container } = render(<FilmFolder {...props} />)
      await flush(0)
      expect(container.querySelector('.character-progress')).not.toBeNull()

      // active 消失:读终端详情,done → 100% 停留 800ms。
      await flush(4_100)
      expect(picturebookApi.get).toHaveBeenCalledWith(9)
      expect(ariaNow()).toBe(100)
      expect(container.querySelector('.character-progress')).not.toBeNull()
      expect(screen.getByText('新绘本')).toBeTruthy()
      expect(screen.getByRole('button', { name: '生成绘本' })).toBeDisabled()

      await flush(800)
      expect(container.querySelector('.character-progress')).toBeNull()
      expect(screen.getByText('新绘本')).toBeTruthy()
      expect(screen.getByRole('button', { name: '生成绘本' })).not.toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })

  test('a terminal failed response never shows 100%, alerts safely and keeps the failed work in 继续创作', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(4, 9) }))
        .mockResolvedValue(collection({ unfinished_count: 1 }))
      vi.mocked(picturebookApi.get).mockResolvedValue(
        terminalPicturebook({ status: 'failed', stage: 'failed', error: '生成过程出错了，可以重试' }),
      )

      const { container } = render(<FilmFolder {...props} />)
      await flush(0)

      await flush(4_100)
      expect(container.querySelector('.character-progress')).toBeNull()
      expect(container.querySelector('[aria-valuenow="100"]')).toBeNull()
      expect(screen.getByRole('alert').textContent).toContain('生成过程出错了，可以重试')
      expect(screen.getByRole('button', { name: '继续创作（1）' })).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  test('motion comics advance from real ready_segments without the picturebook interpolation', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(filmFolderApi.motionComics).mockResolvedValue(collection({
        active_generation: {
          id: 5, stage: 'rendering', status: 'running', total: 8, ready: 4,
          updated_at: 't',
        },
      }))
      render(<FilmFolder {...props} />)
      fireEvent.click(screen.getByRole('tab', { name: '漫剧' }))
      await flush(0)
      const realPercent = 15 + (4 / 8) * 75
      expect(ariaNow()).toBe(Math.round(realPercent))

      // 时间推移不产生插值:没有新的真实节点就停在下界。
      await flush(10_000)
      expect(ariaNow()).toBe(Math.round(realPercent))
    } finally {
      vi.useRealTimers()
    }
  })

  test('poll requests are single-flight even when a response outlives the cadence', async () => {
    vi.useFakeTimers()
    try {
      let resolveSlow: ((value: FilmFolderResponse) => void) | null = null
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(2, 9) }))
        .mockImplementationOnce(() => new Promise(resolve => { resolveSlow = resolve }))
        .mockResolvedValue(collection({ active_generation: runningActive(2, 9) }))

      render(<FilmFolder {...props} />)
      await flush(0)
      await flush(4_100)
      expect(filmFolderApi.picturebooks).toHaveBeenCalledTimes(2)

      // 慢响应挂起期间,节拍过去也不再并发发请求。
      await flush(9_000)
      expect(filmFolderApi.picturebooks).toHaveBeenCalledTimes(2)

      await act(async () => {
        resolveSlow!(collection({ active_generation: runningActive(2, 9) }))
        await Promise.resolve()
      })
      await flush(4_100)
      expect(filmFolderApi.picturebooks).toHaveBeenCalledTimes(3)
    } finally {
      vi.useRealTimers()
    }
  })

  test('a slow picturebook response resolving after a tab switch cannot update motion state', async () => {
    vi.useFakeTimers()
    try {
      let resolveSlow: ((value: FilmFolderResponse) => void) | null = null
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(2, 9) }))
        .mockImplementationOnce(() => new Promise(resolve => { resolveSlow = resolve }))
      vi.mocked(filmFolderApi.motionComics).mockResolvedValue(collection({
        items: [{
          id: 3, source_kind: 'canonical_work', work_kind: 'daily_picturebook',
          title: '漫剧甲', display_start_date: '2026-08-09',
          display_end_date: '2026-08-09', cover_url: null,
          completed_at: '2026-08-09T01:00:00Z',
        }],
      }))

      const { container } = render(<FilmFolder {...props} />)
      await flush(0)
      expect(container.querySelector('.character-progress')).not.toBeNull()

      await flush(4_100)
      fireEvent.click(screen.getByRole('tab', { name: '漫剧' }))
      await flush(0)
      expect(screen.getByText('漫剧甲')).toBeTruthy()
      expect(container.querySelector('.character-progress')).toBeNull()

      // 旧分区的慢响应此刻才返回:必须被丢弃。
      await act(async () => {
        resolveSlow!(collection({ active_generation: runningActive(9, 9) }))
        await Promise.resolve()
      })
      await flush(1_000)
      expect(container.querySelector('.character-progress')).toBeNull()
      expect(screen.getByText('漫剧甲')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  test('an old 800ms hold timer firing after a new job starts leaves the new job intact', async () => {
    vi.useFakeTimers()
    try {
      const newJobActive = {
        id: 10, stage: 'story', status: 'running', total: 9, ready: 0, updated_at: 't3',
      }
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(4, 9) }))
        .mockResolvedValueOnce(collection()) // active 消失
        .mockResolvedValue(collection({ active_generation: newJobActive })) // hold 后重读发现新任务
      vi.mocked(picturebookApi.get).mockResolvedValue(terminalPicturebook())

      const { container } = render(<FilmFolder {...props} />)
      await flush(0)
      await flush(4_100) // 进入 100% hold
      expect(ariaNow()).toBe(100)

      await flush(800) // hold 结束,触发重读
      await flush(0) // 重读返回新任务
      expect(container.querySelector('.character-progress')).not.toBeNull()
      expect(ariaNow()).toBe(Math.round(8))

      // 再过很久也不应再有旧定时器清掉新任务的进度。
      await flush(2_000)
      expect(container.querySelector('.character-progress')).not.toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  test('unmount cancels scheduled writes and produces no post-unmount updates', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(filmFolderApi.picturebooks)
        .mockResolvedValueOnce(collection({ active_generation: runningActive(4, 9) }))
        .mockResolvedValue(collection())
      vi.mocked(picturebookApi.get).mockResolvedValue(terminalPicturebook())

      const { container, unmount } = render(<FilmFolder {...props} />)
      await flush(0)
      await flush(4_100) // 进入 hold,800ms 定时器已挂起
      unmount()
      await flush(5_000) // 所有挂起定时器触发;不应有状态写入或警告。
      expect(container.querySelector('.character-progress')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
