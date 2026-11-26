import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import DailyPicturebookWizard from './index'
import { diaryApi, picturebookApi, storyWorksApi } from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { Diary, PicturebookJob, StoryWorkDetail } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    diaryApi: {
      ...actual.diaryApi,
      list: vi.fn(),
    },
    storyWorksApi: {
      createDraft: vi.fn(),
      get: vi.fn(),
      listDrafts: vi.fn(),
      update: vi.fn(),
      updateSources: vi.fn(),
      duplicate: vi.fn(),
      startPicturebook: vi.fn(),
    },
    picturebookApi: {
      ...actual.picturebookApi,
      get: vi.fn(),
      retry: vi.fn(),
    },
  }
})

const diaries: Diary[] = [
  {
    id: 11,
    date: '2026-08-08',
    text: '第一段。\n\n第二段，有内容。\n\n\n第三段。',
    draft_text: null,
    emotion_mode: null,
    status: 'confirmed',
    source: 'manual',
    images: [],
    created_at: '2026-08-08T09:00:00Z',
    confirmed_at: '2026-08-08T09:05:00Z',
  },
  {
    id: 12,
    date: '2026-08-07',
    text: '',
    draft_text: '  ',
    emotion_mode: null,
    status: 'draft',
    source: 'manual',
    images: [],
    created_at: '2026-08-07T09:00:00Z',
    confirmed_at: null,
  },
  {
    id: 13,
    date: '2026-08-06',
    text: '旧日记正文。',
    draft_text: null,
    emotion_mode: null,
    status: 'confirmed',
    source: 'manual',
    images: [],
    created_at: '2026-08-06T09:00:00Z',
    confirmed_at: '2026-08-06T09:05:00Z',
  },
]

const draft: StoryWorkDetail = {
  id: 501,
  owner_user_id: 7,
  kind: 'daily_picturebook',
  status: 'draft',
  stage: 'narrative_confirmed',
  title: '2026-08-08 的绘本',
  style: 'watercolor',
  selected_segments: ['第一段。', '第三段。'],
  source_diary_ids: [11],
  source_diaries: [{
    id: 11,
    date: '2026-08-08',
    status: 'confirmed',
    text: diaries[0].text,
  }],
  source_snapshot: {
    diaries: [{
      id: 11,
      date: '2026-08-08',
      status: 'confirmed',
      body: diaries[0].text,
    }],
  },
  source_snapshot_hash: 'snapshot-hash',
  source_start_date: '2026-08-08',
  source_end_date: '2026-08-08',
  display_start_date: '2026-08-08',
  display_end_date: '2026-08-08',
  generation_error: null,
  active_picturebook_job: null,
  picturebook_job: null,
  pages: [],
  created_at: '2026-08-08T10:00:00Z',
  updated_at: '2026-08-08T10:00:00Z',
}

const runningJob: PicturebookJob = {
  id: 900,
  diary_id: null,
  work_id: 501,
  style: 'watercolor',
  status: 'running',
  stage: 'queued',
  stage_label: '正在排队',
  error: null,
  total_pages: 9,
  ready_pages: 0,
  created_at: '2026-08-08T10:00:01Z',
  updated_at: '2026-08-08T10:00:01Z',
  pages: [],
}

const failedWorkJob: PicturebookJob = {
  ...runningJob,
  status: 'failed',
  stage: 'failed',
  stage_label: '生成失败',
  error: '生成过程出错了，可以重试',
  ready_pages: 2,
  pages: [
    {
      page_index: 0,
      image_id: 'cover',
      caption: '封面',
      image_url: '/api/media/cover',
      status: 'ready',
      error: null,
    },
    {
      page_index: 2,
      image_id: '',
      caption: '第二页',
      image_url: null,
      status: 'failed',
      error: '生成过程出错了，可以重试',
    },
  ],
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(resolvePromise => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function renderWizard(props: Partial<React.ComponentProps<typeof DailyPicturebookWizard>> = {}) {
  const onBack = vi.fn()
  render(
    <ToastProvider>
      <DailyPicturebookWizard date="2026-08-08" onBack={onBack} {...props} />
    </ToastProvider>,
  )
  return { onBack }
}

describe('DailyPicturebookWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(diaryApi.list).mockResolvedValue([...diaries])
    vi.mocked(storyWorksApi.createDraft).mockResolvedValue(draft)
    vi.mocked(storyWorksApi.startPicturebook).mockResolvedValue(runningJob)
    vi.mocked(picturebookApi.get).mockResolvedValue(runningJob)
  })

  test('lists only non-empty diaries and defaults to all non-empty paragraphs selected', async () => {
    renderWizard()

    expect(await screen.findByRole('button', { name: /2026-08-08/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /2026-08-07/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /2026-08-06/ })).toBeInTheDocument()

    const paragraphs = screen.getAllByRole('checkbox')
    expect(paragraphs).toHaveLength(3)
    expect(paragraphs.map(item => item.getAttribute('aria-checked'))).toEqual(['true', 'true', 'true'])
    expect(paragraphs[0]).toHaveTextContent('第一段。')
    expect(paragraphs[1]).toHaveTextContent('第二段，有内容。')
    expect(paragraphs[2]).toHaveTextContent('第三段。')
  })

  test('keeps at least one paragraph selected', async () => {
    const user = userEvent.setup()
    renderWizard()

    const paragraphs = await screen.findAllByRole('checkbox')
    await user.click(paragraphs[1])
    await user.click(paragraphs[2])

    expect(paragraphs[0]).toHaveAttribute('aria-checked', 'true')
    expect(paragraphs[0]).toBeDisabled()

    await user.click(paragraphs[0])

    expect(paragraphs[0]).toHaveAttribute('aria-checked', 'true')
  })

  test('selects style and creates no draft before confirmation', async () => {
    const user = userEvent.setup()
    renderWizard()

    await screen.findByRole('button', { name: /2026-08-08/ })
    await user.click(screen.getByRole('button', { name: /水彩温柔/ }))
    const paragraphs = screen.getAllByRole('checkbox')
    await user.click(paragraphs[1])

    expect(storyWorksApi.createDraft).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '确认生成绘本' }))

    await waitFor(() => expect(storyWorksApi.createDraft).toHaveBeenCalledOnce())
    expect(storyWorksApi.createDraft).toHaveBeenCalledWith({
      kind: 'daily_picturebook',
      source_diary_ids: [11],
      selected_segments: ['第一段。', '第三段。'],
      style: 'watercolor',
      title: '2026-08-08 的绘本',
    })
    expect(storyWorksApi.startPicturebook).toHaveBeenCalledWith(501)
    expect(await screen.findByText('正在排队')).toBeInTheDocument()
  })

  test('guards the confirm action from double creating drafts', async () => {
    const user = userEvent.setup()
    const createDraft = deferred<StoryWorkDetail>()
    vi.mocked(storyWorksApi.createDraft).mockReturnValue(createDraft.promise)
    renderWizard()

    const confirm = await screen.findByRole('button', { name: '确认生成绘本' })
    await user.dblClick(confirm)

    expect(storyWorksApi.createDraft).toHaveBeenCalledOnce()
    expect(confirm).toBeDisabled()

    createDraft.resolve(draft)
    await waitFor(() => expect(storyWorksApi.startPicturebook).toHaveBeenCalledOnce())
  })

  test('resumes an existing work before rendering the progress step', async () => {
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...draft,
      stage: 'rendering',
      active_picturebook_job: runningJob,
    })

    renderWizard({ workId: 501 })

    expect(await screen.findByText('正在排队')).toBeInTheDocument()
    expect(storyWorksApi.get).toHaveBeenCalledWith(501)
    expect(diaryApi.list).not.toHaveBeenCalled()
  })

  test('loads full job details when an existing work only returns a job summary', async () => {
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...draft,
      stage: 'rendering',
      active_picturebook_job: {
        id: 900,
        status: 'running',
        stage: 'queued',
        total_pages: 9,
        ready_pages: 0,
      } as any,
    })

    renderWizard({ workId: 501 })

    expect(await screen.findByText('正在排队')).toBeInTheDocument()
    expect(picturebookApi.get).toHaveBeenCalledWith(900)
  })

  test('retries work-backed failed jobs through the story work state machine', async () => {
    const user = userEvent.setup()
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...draft,
      stage: 'render_failed',
      generation_error: '生成过程出错了，可以重试',
      active_picturebook_job: {
        id: 900,
        status: 'failed',
        stage: 'failed',
        total_pages: 9,
        ready_pages: 2,
      } as any,
    })
    vi.mocked(picturebookApi.get).mockResolvedValue(failedWorkJob)

    renderWizard({ workId: 501 })

    await user.click(await screen.findByRole('button', { name: '重试没成功的页' }))

    await waitFor(() => expect(storyWorksApi.startPicturebook).toHaveBeenCalledWith(501))
    expect(picturebookApi.retry).not.toHaveBeenCalled()
  })
})
