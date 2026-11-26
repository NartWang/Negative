import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import DiaryEditor from './index'
import { diaryApi, imageApi, picturebookApi } from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { Diary, DiarySourceSelection, PicturebookJob } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    diaryApi: {
      ...actual.diaryApi,
      get: vi.fn(),
      createBlank: vi.fn(),
      update: vi.fn(),
      aiFill: vi.fn(),
      aiRewrite: vi.fn(),
    },
    imageApi: {
      ...actual.imageApi,
      keep: vi.fn(),
    },
    picturebookApi: {
      ...actual.picturebookApi,
      latest: vi.fn(),
    },
  }
})

const sourceSelection: DiarySourceSelection = {
  schedule_ids: [101],
  fragment_ids: [201, 202],
}

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

function renderEditor(props: Partial<React.ComponentProps<typeof DiaryEditor>> = {}) {
  const onBack = vi.fn()
  const onChangeDate = vi.fn()
  render(
    <ToastProvider>
      <DiaryEditor
        userId={7}
        date="2026-08-08"
        selection={sourceSelection}
        onBack={onBack}
        onChangeDate={onChangeDate}
        {...props}
      />
    </ToastProvider>,
  )
  return { onBack, onChangeDate }
}

const legacyBook: PicturebookJob = {
  id: 501,
  diary_id: 88,
  work_id: null,
  style: 'watercolor',
  status: 'done',
  stage: 'rendering',
  stage_label: '绘本已完成',
  error: null,
  total_pages: 1,
  ready_pages: 1,
  created_at: '2026-08-08T10:00:00Z',
  updated_at: '2026-08-08T10:05:00Z',
  pages: [{
    page_index: 0,
    image_id: 'legacy-cover',
    image_url: '/api/media/legacy-cover',
    caption: '旧绘本封面',
    status: 'ready',
    error: null,
  }],
}

describe('DiaryEditor', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.mocked(diaryApi.get).mockImplementation(async date => {
      if (date === '2026-08-08') {
        return diary({ id: 88, date, draft_text: '今天原稿' })
      }
      return null
    })
    vi.mocked(diaryApi.createBlank).mockImplementation(async date =>
      diary({ id: 99, date }),
    )
    vi.mocked(diaryApi.update).mockImplementation(async (id, data) =>
      diary({
        id,
        date: id === 88 ? '2026-08-08' : '2026-08-07',
        text: data.text ?? '',
        draft_text: data.draft_text ?? '',
        status: data.status ?? 'draft',
        confirmed_at: data.status === 'confirmed' ? '2026-08-08T09:00:00Z' : null,
      }),
    )
    vi.mocked(diaryApi.aiFill).mockResolvedValue(diary({
      id: 88,
      date: '2026-08-08',
      text: 'AI 生成的日记',
      draft_text: 'AI 生成的日记',
      source: 'ai',
    }))
    vi.mocked(picturebookApi.latest).mockResolvedValue(null)
    vi.mocked(imageApi.keep).mockResolvedValue({ images: [] })
  })

  test('initial load failure offers retry and back without creating twice', async () => {
    vi.mocked(diaryApi.get)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(diary({ id: 88, date: '2026-08-08', draft_text: '恢复稿' }))
    const user = userEvent.setup()
    const { onBack } = renderEditor()

    expect(await screen.findByRole('alert')).toHaveTextContent('加载日记失败')
    expect(onBack).not.toHaveBeenCalled()
    expect(diaryApi.createBlank).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('textbox')).toBeInTheDocument()
    expect(diaryApi.get).toHaveBeenCalledTimes(2)
    expect(diaryApi.createBlank).not.toHaveBeenCalled()
    expect(onBack).not.toHaveBeenCalled()
  })

  test('initial load back button returns to the record page', async () => {
    vi.mocked(diaryApi.get).mockRejectedValueOnce(new Error('offline'))
    const user = userEvent.setup()
    const { onBack } = renderEditor()

    expect(await screen.findByRole('alert')).toHaveTextContent('加载日记失败')
    await user.click(screen.getByRole('button', { name: '返回记录页' }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  test('opens today by default and flushes manual edits before changing dates', async () => {
    const user = userEvent.setup()
    const { onChangeDate } = renderEditor()

    const textarea = await screen.findByRole('textbox') as HTMLTextAreaElement
    expect(textarea).toHaveValue('今天原稿')
    expect(screen.getByRole('button', { name: '日记日期' })).toHaveTextContent('2026/08/08')
    expect(diaryApi.get).toHaveBeenCalledWith('2026-08-08')

    await user.clear(textarea)
    await user.type(textarea, '今天手写的一段')
    await user.click(screen.getByRole('button', { name: '前一天' }))

    await waitFor(() => expect(diaryApi.update).toHaveBeenCalledWith(88, {
      text: '今天手写的一段',
      draft_text: '今天手写的一段',
    }))
    expect(onChangeDate).toHaveBeenCalledWith('2026-08-07')
  })

  test('appends reverted text after an in-flight save and waits before changing dates', async () => {
    const calls: string[] = []
    let resolveOlderSave!: (value: Diary) => void
    let resolveFinalSave!: (value: Diary) => void
    const olderSave = new Promise<Diary>(resolve => { resolveOlderSave = resolve })
    const finalSave = new Promise<Diary>(resolve => { resolveFinalSave = resolve })
    vi.mocked(diaryApi.update).mockImplementation((id, data) => {
      calls.push(`update:${data.text}`)
      if (data.text === '队列中的 B') return olderSave
      if (data.text === '今天原稿') return finalSave
      return Promise.resolve(diary({ id, text: data.text, draft_text: data.draft_text }))
    })
    const { onChangeDate } = renderEditor()
    const textarea = await screen.findByRole('textbox')

    vi.useFakeTimers()
    try {
      fireEvent.change(textarea, { target: { value: '队列中的 B' } })
      await act(async () => {
        vi.advanceTimersByTime(600)
        await Promise.resolve()
      })
      expect(calls).toEqual(['update:队列中的 B'])

      fireEvent.change(textarea, { target: { value: '今天原稿' } })
      fireEvent.click(screen.getByRole('button', { name: '前一天' }))
      expect(onChangeDate).not.toHaveBeenCalled()

      await act(async () => {
        calls.push('resolved:队列中的 B')
        resolveOlderSave(diary({
          id: 88,
          text: '队列中的 B',
          draft_text: '队列中的 B',
        }))
        await Promise.resolve()
        await Promise.resolve()
        await Promise.resolve()
      })

      expect(diaryApi.update).toHaveBeenNthCalledWith(2, 88, {
        text: '今天原稿',
        draft_text: '今天原稿',
      })
      expect(calls).toEqual([
        'update:队列中的 B',
        'resolved:队列中的 B',
        'update:今天原稿',
      ])
      expect(onChangeDate).not.toHaveBeenCalled()

      await act(async () => {
        calls.push('resolved:今天原稿')
        resolveFinalSave(diary({
          id: 88,
          text: '今天原稿',
          draft_text: '今天原稿',
        }))
        await Promise.resolve()
        await Promise.resolve()
        await Promise.resolve()
      })

      expect(calls).toEqual([
        'update:队列中的 B',
        'resolved:队列中的 B',
        'update:今天原稿',
        'resolved:今天原稿',
      ])
      expect(onChangeDate).toHaveBeenCalledWith('2026-08-07')
    } finally {
      vi.useRealTimers()
    }
  })

  test('shows a labeled diary style selector beside one-click generation with real selected by default', async () => {
    renderEditor()

    await screen.findByRole('textbox')
    const generateButton = screen.getByRole('button', { name: '一键生成' })
    const toolbar = generateButton.closest('.de-toolbar')
    expect(toolbar).not.toBeNull()
    const styleSelector = within(toolbar as HTMLElement).getByRole('radiogroup', { name: '日记风格' })

    expect(styleSelector).toBeVisible()
    expect(within(styleSelector).getByRole('radio', { name: '真实' })).toBeChecked()
    expect(within(styleSelector).getByRole('radio', { name: '意象' })).not.toBeChecked()
  })

  test('initializes imagery from a stored legacy poetic preference', async () => {
    localStorage.setItem('zhiji:user:7:emotionMode', 'poetic')
    renderEditor()

    await screen.findByRole('textbox')
    const styleSelector = screen.getByRole('radiogroup', { name: '日记风格' })

    expect(within(styleSelector).getByRole('radio', { name: '真实' })).not.toBeChecked()
    expect(within(styleSelector).getByRole('radio', { name: '意象' })).toBeChecked()
  })

  test('uses a locally selected imagery style for overwrite generation with the source selection', async () => {
    const user = userEvent.setup()
    renderEditor()

    await screen.findByRole('textbox')
    await user.click(screen.getByRole('radio', { name: '意象' }))
    await user.click(screen.getByRole('button', { name: '一键生成' }))
    expect(await screen.findByText('文本框已有内容')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '覆盖生成' }))

    await waitFor(() => expect(diaryApi.aiFill).toHaveBeenCalledWith(88, {
      emotion_mode: 'imagery',
      schedule_ids: [101],
      fragment_ids: [201, 202],
    }))
    expect(await screen.findByRole('textbox')).toHaveValue('AI 生成的日记')
  })

  test('uses a locally selected imagery style for direct generation when the diary is empty', async () => {
    vi.mocked(diaryApi.get).mockResolvedValueOnce(diary({
      id: 88,
      date: '2026-08-08',
      text: '',
      draft_text: '',
    }))
    const user = userEvent.setup()
    renderEditor()

    await screen.findByRole('textbox')
    await user.click(screen.getByRole('radio', { name: '意象' }))
    await user.click(screen.getByRole('button', { name: '一键生成' }))

    await waitFor(() => expect(diaryApi.aiFill).toHaveBeenCalledWith(88, {
      emotion_mode: 'imagery',
      schedule_ids: [101],
      fragment_ids: [201, 202],
    }))
  })

  test('disables diary style choices while generation is in flight', async () => {
    let resolveAiFill!: (value: Diary) => void
    vi.mocked(diaryApi.aiFill).mockImplementation(() => new Promise(resolve => {
      resolveAiFill = resolve
    }))
    const user = userEvent.setup()
    renderEditor()

    await screen.findByRole('textbox')
    const realRadio = screen.getByRole('radio', { name: '真实' })
    const imageryRadio = screen.getByRole('radio', { name: '意象' })
    await user.click(imageryRadio)
    await user.click(screen.getByRole('button', { name: '一键生成' }))
    await user.click(await screen.findByRole('button', { name: '覆盖生成' }))

    await waitFor(() => expect(diaryApi.aiFill).toHaveBeenCalledTimes(1))
    expect(realRadio).toBeDisabled()
    expect(imageryRadio).toBeDisabled()
    await user.click(realRadio)
    expect(imageryRadio).toBeChecked()

    await act(async () => {
      resolveAiFill(diary({
        id: 88,
        date: '2026-08-08',
        text: 'AI 生成的日记',
        draft_text: 'AI 生成的日记',
        source: 'ai',
      }))
      await Promise.resolve()
      await Promise.resolve()
    })
  })

  test('does not persist editor-only diary style changes', async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const user = userEvent.setup()

    try {
      renderEditor()
      await screen.findByRole('textbox')

      await user.click(screen.getByRole('radio', { name: '意象' }))

      expect(screen.getByRole('radio', { name: '意象' })).toBeChecked()
      expect(setItemSpy).not.toHaveBeenCalled()
    } finally {
      setItemSpy.mockRestore()
    }
  })

  test('flushes the current unsaved text before immediate overwrite generation', async () => {
    const calls: string[] = []
    vi.mocked(diaryApi.update).mockImplementation(async (id, data) => {
      calls.push(`update:${data.text}`)
      return diary({ id, text: data.text, draft_text: data.draft_text })
    })
    vi.mocked(diaryApi.aiFill).mockImplementation(async () => {
      calls.push('ai-fill')
      return diary({
        id: 88,
        text: 'AI 生成的日记',
        draft_text: 'AI 生成的日记',
        source: 'ai',
      })
    })
    renderEditor()
    const textarea = await screen.findByRole('textbox')

    vi.useFakeTimers()
    try {
      fireEvent.change(textarea, { target: { value: '600ms 内刚写完的正文' } })
      fireEvent.click(screen.getByRole('button', { name: '一键生成' }))
      fireEvent.click(screen.getByRole('button', { name: '覆盖生成' }))

      await act(async () => {
        await Promise.resolve()
        await Promise.resolve()
        await Promise.resolve()
      })

      expect(diaryApi.update).toHaveBeenCalledWith(88, {
        text: '600ms 内刚写完的正文',
        draft_text: '600ms 内刚写完的正文',
      })
      expect(calls).toEqual(['update:600ms 内刚写完的正文', 'ai-fill'])
    } finally {
      vi.useRealTimers()
    }
  })

  test('appends current text after an older deferred save before overwrite generation', async () => {
    const calls: string[] = []
    let resolveOlderSave!: (value: Diary) => void
    const olderSave = new Promise<Diary>(resolve => { resolveOlderSave = resolve })
    vi.mocked(diaryApi.update).mockImplementation((id, data) => {
      calls.push(`update:${data.text}`)
      if (data.text === '队列中的 B') return olderSave
      return Promise.resolve(diary({ id, text: data.text, draft_text: data.draft_text }))
    })
    vi.mocked(diaryApi.aiFill).mockImplementation(async () => {
      calls.push('ai-fill')
      return diary({
        id: 88,
        text: 'AI 生成的日记',
        draft_text: 'AI 生成的日记',
        source: 'ai',
      })
    })
    renderEditor()
    const textarea = await screen.findByRole('textbox')

    vi.useFakeTimers()
    try {
      fireEvent.change(textarea, { target: { value: '队列中的 B' } })
      await act(async () => {
        vi.advanceTimersByTime(600)
        await Promise.resolve()
      })
      expect(calls).toEqual(['update:队列中的 B'])

      fireEvent.change(textarea, { target: { value: '今天原稿' } })
      fireEvent.click(screen.getByRole('button', { name: '一键生成' }))
      fireEvent.click(screen.getByRole('button', { name: '覆盖生成' }))
      expect(diaryApi.aiFill).not.toHaveBeenCalled()

      await act(async () => {
        calls.push('resolved:队列中的 B')
        resolveOlderSave(diary({
          id: 88,
          text: '队列中的 B',
          draft_text: '队列中的 B',
        }))
        await Promise.resolve()
        await Promise.resolve()
        await Promise.resolve()
      })

      expect(diaryApi.update).toHaveBeenNthCalledWith(2, 88, {
        text: '今天原稿',
        draft_text: '今天原稿',
      })
      expect(calls).toEqual([
        'update:队列中的 B',
        'resolved:队列中的 B',
        'update:今天原稿',
        'ai-fill',
      ])
    } finally {
      vi.useRealTimers()
    }
  })

  test('can complete a private diary while keeping the story-save step optional', async () => {
    const user = userEvent.setup()
    renderEditor()

    const textarea = await screen.findByRole('textbox') as HTMLTextAreaElement
    expect(screen.getByText('私密草稿')).toBeInTheDocument()
    await user.clear(textarea)
    await user.type(textarea, '完成前的正文')

    await user.click(screen.getByRole('button', { name: '完成日记' }))

    await waitFor(() => expect(diaryApi.update).toHaveBeenCalledWith(88, {
      text: '完成前的正文',
      draft_text: '完成前的正文',
      status: 'confirmed',
    }))
    expect(imageApi.keep).toHaveBeenCalledWith(88, [])
    const saveDialog = await screen.findByRole('dialog', { name: '放入故事架' })
    expect(within(saveDialog).getByText('完成前的正文')).toBeInTheDocument()
    expect(within(saveDialog).getByRole('button', { name: '暂不保存' })).toBeInTheDocument()
  })

  test('does not expose or call rewrite-selected while harmless text selection remains possible', async () => {
    const user = userEvent.setup()
    renderEditor()

    const textarea = await screen.findByRole('textbox') as HTMLTextAreaElement
    textarea.setSelectionRange(0, 2)
    await user.click(textarea)

    expect(screen.queryByRole('button', { name: '改写选中' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: '改写选中段落' })).not.toBeInTheDocument()
    expect(diaryApi.aiRewrite).not.toHaveBeenCalled()
  })

  test('does not expose the legacy picturebook creation entry in the diary editor', async () => {
    renderEditor()

    await screen.findByRole('textbox')

    expect(screen.queryByRole('heading', { name: '把日记做成一本绘本' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '生成绘本' })).not.toBeInTheDocument()
  })

  test('still restores an existing legacy picturebook as read-only history', async () => {
    vi.mocked(picturebookApi.latest).mockResolvedValueOnce(legacyBook)
    renderEditor()

    expect(await screen.findByRole('heading', { name: '历史绘本' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '旧绘本封面' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '生成绘本' })).not.toBeInTheDocument()
  })
})
