import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import TimeStoryWizard from './index'
import { diaryApi, picturebookApi, storyWorksApi } from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { Diary, PicturebookJob, StoryWorkDetail, StorylineCandidate } from '../../types'

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
      createDraft: vi.fn(),
      get: vi.fn(),
      update: vi.fn(),
      generateStorylines: vi.fn(),
      generateNarrative: vi.fn(),
      confirmNarrative: vi.fn(),
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
    id: 31,
    date: '2026-08-03',
    text: '周一保存正文',
    draft_text: null,
    emotion_mode: null,
    status: 'confirmed',
    source: 'manual',
    images: [],
    created_at: '2026-08-03T09:00:00Z',
    confirmed_at: '2026-08-03T10:00:00Z',
  },
  {
    id: 32,
    date: '2026-08-05',
    text: '',
    draft_text: '周三草稿正文',
    emotion_mode: null,
    status: 'draft',
    source: 'manual',
    images: [],
    created_at: '2026-08-05T09:00:00Z',
    confirmed_at: null,
  },
  {
    id: 33,
    date: '2026-08-06',
    text: '',
    draft_text: '   ',
    emotion_mode: null,
    status: 'draft',
    source: 'manual',
    images: [],
    created_at: '2026-08-06T09:00:00Z',
    confirmed_at: null,
  },
]

const candidates: StorylineCandidate[] = [
  { id: 'line-1', title: '一条温柔线', summary: '从散步到收束。', tone: '温柔' },
  { id: 'line-2', title: '一条行动线', summary: '从计划到完成。', tone: '明亮' },
  { id: 'line-3', title: '一条转折线', summary: '从卡住到看见。', tone: '安静' },
]

const baseWork: StoryWorkDetail = {
  id: 701,
  owner_user_id: 7,
  kind: 'time_story',
  status: 'draft',
  stage: 'sources_selected',
  title: '2026-08-03 至 2026-08-09 的时光故事',
  style: 'watercolor',
  selected_segments: [],
  source_diary_ids: [31, 32],
  source_diaries: [],
  source_snapshot: {
    diaries: [
      { id: 31, date: '2026-08-03', status: 'confirmed', body: '周一保存正文' },
      { id: 32, date: '2026-08-05', status: 'draft', body: '周三草稿正文' },
    ],
  },
  source_snapshot_hash: 'hash',
  source_start_date: '2026-08-03',
  source_end_date: '2026-08-09',
  display_start_date: '2026-08-03',
  display_end_date: '2026-08-09',
  storyline_candidates: [],
  selected_storyline: null,
  selected_storyline_id: null,
  narrative_text: '',
  generation_error: null,
  active_picturebook_job: null,
  picturebook_job: null,
  pages: [],
  created_at: '2026-08-08T10:00:00Z',
  updated_at: '2026-08-08T10:00:00Z',
}

const runningJob: PicturebookJob = {
  id: 920,
  diary_id: null,
  work_id: 701,
  style: 'watercolor',
  status: 'running',
  stage: 'rendering',
  stage_label: '逐页作画',
  error: null,
  total_pages: 3,
  ready_pages: 1,
  created_at: '2026-08-08T10:00:01Z',
  updated_at: '2026-08-08T10:00:01Z',
  pages: [{
    page_index: 0,
    image_id: 'cover',
    image_url: 'https://example.test/cover.jpg',
    caption: '封面',
    status: 'ready',
    error: null,
  }],
}

function renderWizard(props: Partial<React.ComponentProps<typeof TimeStoryWizard>> = {}) {
  const onBack = vi.fn()
  render(
    <ToastProvider>
      <TimeStoryWizard userId={7} onBack={onBack} {...props} />
    </ToastProvider>,
  )
  return { onBack }
}

describe('TimeStoryWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    vi.mocked(diaryApi.list).mockResolvedValue([...diaries])
    vi.mocked(storyWorksApi.createDraft).mockResolvedValue(baseWork)
    vi.mocked(storyWorksApi.generateStorylines).mockResolvedValue({
      ...baseWork,
      stage: 'storylines_ready',
      storyline_candidates: candidates,
    })
    vi.mocked(storyWorksApi.update).mockImplementation(async (_id, payload) => {
      if (payload.selected_storyline_id) {
        return {
          ...baseWork,
          stage: 'storylines_ready',
          storyline_candidates: candidates,
          selected_storyline_id: payload.selected_storyline_id,
          selected_storyline: candidates.find(candidate => candidate.id === payload.selected_storyline_id) ?? null,
        }
      }
      if (payload.narrative_text) {
        return {
          ...baseWork,
          stage: 'narrative_editing',
          narrative_text: payload.narrative_text,
        }
      }
      return {
        ...baseWork,
        stage: 'narrative_confirmed',
        style: payload.style ?? baseWork.style,
      }
    })
    vi.mocked(storyWorksApi.generateNarrative).mockResolvedValue({
      ...baseWork,
      stage: 'narrative_editing',
      selected_storyline_id: 'line-2',
      selected_storyline: candidates[1],
      storyline_candidates: candidates,
      narrative_text: '这是生成好的长故事。',
    })
    vi.mocked(storyWorksApi.confirmNarrative).mockResolvedValue({
      ...baseWork,
      stage: 'narrative_confirmed',
      selected_storyline_id: 'line-2',
      selected_storyline: candidates[1],
      storyline_candidates: candidates,
      narrative_text: '这是生成好的长故事。',
    })
    vi.mocked(storyWorksApi.startPicturebook).mockResolvedValue(runningJob)
    vi.mocked(picturebookApi.get).mockResolvedValue(runningJob)
  })

  test('selects non-empty diaries in a range and creates no draft until continuing', async () => {
    const user = userEvent.setup()
    renderWizard()

    expect(await screen.findByRole('heading', { name: '选择日记范围' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '本周' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('checkbox', { name: /周一保存正文/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /周三草稿正文/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /周三草稿正文/ })).toHaveTextContent('草稿')
    expect(screen.queryByText(/2026-08-06/)).not.toBeInTheDocument()
    expect(storyWorksApi.createDraft).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '继续' }))

    await waitFor(() => expect(storyWorksApi.createDraft).toHaveBeenCalledWith({
      kind: 'time_story',
      source_start_date: '2026-08-03',
      source_end_date: '2026-08-09',
      source_diary_ids: [31, 32],
      style: 'watercolor',
      title: '2026-08-03 至 2026-08-09 的时光故事',
    }))
    expect(await screen.findByRole('heading', { name: '选择故事线' })).toBeInTheDocument()
  })

  test('requires one storyline, offers four styles, then generates the picturebook directly', async () => {
    const user = userEvent.setup()
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      stage: 'sources_selected',
    })
    renderWizard({ workId: 701 })

    await user.click(await screen.findByRole('button', { name: '生成故事线' }))
    expect(await screen.findAllByRole('radio')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '生成绘本' })).toBeDisabled()
    expect(screen.getAllByRole('button', { name: /蜡笔童趣|水彩温柔|素描观察|像素游戏/ })).toHaveLength(4)

    await user.click(screen.getByRole('radio', { name: /一条行动线/ }))
    await user.click(screen.getByRole('button', { name: '生成绘本' }))

    await waitFor(() => expect(storyWorksApi.generateNarrative).toHaveBeenCalledWith(701))
    expect(storyWorksApi.confirmNarrative).toHaveBeenCalledWith(701)
    expect(storyWorksApi.startPicturebook).toHaveBeenCalledWith(701)
    expect(await screen.findAllByText('逐页作画')).not.toHaveLength(0)
  })

  test('waits for storyline selection to be saved before narrative generation', async () => {
    const user = userEvent.setup()
    let finishUpdate!: (value: StoryWorkDetail) => void
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      stage: 'storylines_ready',
      storyline_candidates: candidates,
    })
    vi.mocked(storyWorksApi.update).mockReturnValueOnce(new Promise(resolve => {
      finishUpdate = resolve
    }))
    renderWizard({ workId: 701 })

    await user.click(await screen.findByRole('radio', { name: /一条行动线/ }))

    expect(screen.getByRole('button', { name: '正在生成绘本…' })).toBeDisabled()
    expect(storyWorksApi.generateNarrative).not.toHaveBeenCalled()

    finishUpdate({
      ...baseWork,
      stage: 'storylines_ready',
      storyline_candidates: candidates,
      selected_storyline_id: 'line-2',
      selected_storyline: candidates[1],
    })
    await waitFor(() => expect(screen.getByRole('button', { name: '生成绘本' })).toBeEnabled())
  })

  test('resumes plural storylines stage and selected storyline object from the backend', async () => {
    const user = userEvent.setup()
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      stage: 'storylines_ready',
      storyline_candidates: candidates,
      selected_storyline: candidates[1],
      selected_storyline_id: null,
    })
    renderWizard({ workId: 701 })

    const selected = await screen.findByRole('radio', { name: /一条行动线/ })
    expect(selected).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('button', { name: '生成绘本' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '生成绘本' }))

    expect(storyWorksApi.generateNarrative).toHaveBeenCalledWith(701)
  })

  test('resumes a generated narrative and starts a work-backed picturebook without an edit step', async () => {
    const user = userEvent.setup()
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      stage: 'narrative_editing',
      storyline_candidates: candidates,
      selected_storyline_id: 'line-2',
      selected_storyline: candidates[1],
      narrative_text: '旧文本',
    })
    renderWizard({ workId: 701 })

    expect(await screen.findByRole('heading', { name: '选择绘本风格' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '生成绘本' }))

    await waitFor(() => expect(storyWorksApi.startPicturebook).toHaveBeenCalledWith(701))
    expect(await screen.findAllByText('逐页作画')).not.toHaveLength(0)
  })

  test('allows leaving a resumed narrative because editing is no longer required', async () => {
    const user = userEvent.setup()
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      stage: 'narrative_editing',
      storyline_candidates: candidates,
      selected_storyline_id: 'line-2',
      selected_storyline: candidates[1],
      narrative_text: '旧文本',
    })
    const { onBack } = renderWizard({ workId: 701 })

    await screen.findByRole('heading', { name: '选择绘本风格' })
    await user.click(screen.getByRole('button', { name: '返回故事' }))

    expect(onBack).toHaveBeenCalled()
  })

  test('does not expose edit or start actions while a resumed render is active without a job payload', async () => {
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      stage: 'rendering',
      active_picturebook_job: null,
      picturebook_job: null,
      selected_storyline_id: 'line-2',
      selected_storyline: candidates[1],
      narrative_text: '这是生成好的长故事。',
    })
    renderWizard({ workId: 701 })

    expect(await screen.findByRole('heading', { name: '绘本生成中' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑故事文本' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '开始生成绘本' })).not.toBeInTheDocument()
  })

  test('keeps continue disabled when a custom range is invalid', async () => {
    const user = userEvent.setup()
    renderWizard()

    await user.click(await screen.findByRole('button', { name: '自选' }))
    await user.clear(screen.getByLabelText('开始'))
    await user.type(screen.getByLabelText('开始'), '2026-08-10')
    await user.clear(screen.getByLabelText('结束'))
    await user.type(screen.getByLabelText('结束'), '2026-08-03')

    expect(await screen.findByRole('alert')).toHaveTextContent('开始日期不能晚于结束日期')
    expect(screen.getByRole('button', { name: '继续' })).toBeDisabled()
  })

  test('resumes a ready time story directly into the horizontal reader', async () => {
    vi.mocked(storyWorksApi.get).mockResolvedValue({
      ...baseWork,
      status: 'ready',
      stage: 'ready',
      narrative_text: '完成的长故事',
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
          image_url: 'https://example.test/page-1.jpg',
          caption: '第一页',
          status: 'ready',
          error: null,
        },
      ],
    })
    renderWizard({ workId: 701 })

    expect(await screen.findByRole('region', { name: baseWork.title })).toBeInTheDocument()
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
  })
})
