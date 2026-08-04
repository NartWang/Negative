import { useState } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import PublishSheet from './index'
import DiaryEditor from '../../pages/DiaryEditor'
import ComicResultModal from '../WeeklyComic/ResultModal'
import Mine from '../../pages/Mine'
import NaggingSheet from '../NaggingSheet'
import {
  diaryApi, imageApi, profileApi, roomsApi, statsApi, transformApi,
} from '../../api/client'
import type { Diary, Room, RoomPost, WeeklyComic } from '../../types'

const testState = vi.hoisted(() => ({ room: null as Room | null }))
const toast = vi.hoisted(() => ({
  success: vi.fn(), error: vi.fn(), info: vi.fn(),
}))

vi.mock('../../contexts/RoomContext', () => ({
  useRoom: () => ({ room: testState.room }),
}))

vi.mock('../../contexts/ToastContext', () => ({
  useToast: () => toast,
}))

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    roomsApi: {
      ...actual.roomsApi,
      publishDiary: vi.fn(),
      publishComic: vi.fn(),
    },
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
      batchGenerate: vi.fn(),
      keep: vi.fn(),
    },
    profileApi: { ...actual.profileApi, get: vi.fn() },
    statsApi: { ...actual.statsApi, get: vi.fn() },
    transformApi: {
      ...actual.transformApi,
      inbox: vi.fn(),
      transform: vi.fn(),
    },
  }
})

const pairedRoom: Room = {
  id: 'room-pair',
  status: 'active',
  state: 'paired',
  waiting: false,
  created_at: '2026-08-01T08:00:00Z',
  members: [
    { id: 1, nickname: '小满', avatar_url: null, role: 'owner', slot: 1 },
    { id: 2, nickname: '妈妈', avatar_url: null, role: 'member', slot: 2 },
  ],
  partner: { id: 2, nickname: '妈妈', avatar_url: null, role: 'member', slot: 2 },
}

const draftDiary: Diary = {
  id: 9,
  date: '2026-08-03',
  text: '旧文本',
  draft_text: '旧文本',
  emotion_mode: 'warm',
  status: 'draft',
  source: 'manual',
  images: [
    { id: 21, diary_id: 9, style: 'ghibli', style_prompt: null, url: '/one.png', created_at: '', kept: 0 },
    { id: 22, diary_id: 9, style: 'ghibli', style_prompt: null, url: '/two.png', created_at: '', kept: 1 },
  ],
  created_at: '2026-08-03T08:00:00Z',
  confirmed_at: null,
}

const publishedPost = (sourceType: 'diary' | 'weekly_comic'): RoomPost => ({
  id: 'post-1',
  source_type: sourceType,
  author: { nickname: '小满', avatar_url: null },
  mine: true,
  snapshot: sourceType === 'diary'
    ? { type: 'diary', date: draftDiary.date, text: draftDiary.text, emotion_mode: 'warm', images: [] }
    : { type: 'weekly_comic', week_start: '2026-07-27', week_end: '2026-08-02', style: 'ghibli', caption: '这一周', image_url: '/comic.png' },
  media_urls: [],
  published_at: '2026-08-03T12:00:00Z',
  like_count: 0,
  liked_by_me: false,
  comment_count: 0,
  comments_truncated: false,
  comments: [],
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function FocusHarness() {
  const [open, setOpen] = useState(false)
  return (
    <div data-testid="transformed-shell" style={{ transform: 'translateZ(0)' }}>
      <button type="button" onClick={() => setOpen(true)}>打开发布确认</button>
      <nav data-testid="bottom-navigation">底部导航</nav>
      <PublishSheet
        open={open}
        kind="diary"
        title="今天的日记"
        summary="只分享这一段"
        images={[]}
        onClose={() => setOpen(false)}
        onConfirm={() => undefined}
      />
    </div>
  )
}

describe('explicit room publication', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testState.room = pairedRoom
    vi.mocked(diaryApi.get).mockResolvedValue(draftDiary)
    vi.mocked(diaryApi.update).mockImplementation(async (_id, data) => ({
      ...draftDiary,
      text: data.text ?? draftDiary.text,
      draft_text: data.draft_text ?? draftDiary.draft_text,
      status: data.status ?? draftDiary.status,
    }))
    vi.mocked(diaryApi.aiFill).mockResolvedValue({
      ...draftDiary, text: 'AI 写好的正文', draft_text: 'AI 写好的正文', source: 'ai',
    })
    vi.mocked(diaryApi.aiRewrite).mockResolvedValue({
      original: '旧文本', rewritten: '改写后的正文', direction: 'warmer',
    })
    vi.mocked(imageApi.keep).mockResolvedValue({ images: draftDiary.images.filter(image => image.kept === 1) })
    vi.mocked(imageApi.batchGenerate).mockResolvedValue({ candidates: [] })
    vi.mocked(roomsApi.publishDiary).mockResolvedValue(publishedPost('diary'))
    vi.mocked(roomsApi.publishComic).mockResolvedValue(publishedPost('weekly_comic'))
  })

  test('disables publication until a two-person room is paired', async () => {
    testState.room = null
    const confirm = vi.fn()
    const user = userEvent.setup()
    render(
      <PublishSheet
        open
        kind="diary"
        title="8 月 3 日的日记"
        summary="今天很好"
        images={[]}
        selectedImageIds={[]}
        onClose={() => undefined}
        onConfirm={confirm}
      />,
    )

    expect(screen.getByText('先与对方建立双人房间，才能发布。')).toBeInTheDocument()
    const button = screen.getByRole('button', { name: '确认发布' })
    expect(button).toBeDisabled()
    await user.click(button)
    expect(confirm).not.toHaveBeenCalled()
  })

  test('names the partner and confirms exactly the selected diary images', async () => {
    const confirm = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(
      <PublishSheet
        open
        kind="diary"
        title="8 月 3 日的日记"
        summary="今天很好"
        images={[
          { id: 21, url: '/one.png' },
          { id: 22, url: '/two.png' },
          { id: 23, url: '/three.png' },
        ]}
        selectedImageIds={[21, 23]}
        onClose={() => undefined}
        onConfirm={confirm}
      />,
    )

    expect(screen.getByRole('heading', { name: '发布给妈妈' })).toBeInTheDocument()
    expect(screen.getByText('日记仍默认私密；只有这次确认的文字与画面会进入「我们」。')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: '选择画面 1' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: '选择画面 2' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: '选择画面 3' })).toBeChecked()

    await user.click(screen.getByRole('checkbox', { name: '选择画面 1' }))
    await user.click(screen.getByRole('checkbox', { name: '选择画面 2' }))
    await user.click(screen.getByRole('button', { name: '确认发布' }))

    await waitFor(() => expect(confirm).toHaveBeenCalledWith([22, 23]))
  })

  test('traps focus in the real modal dialog and restores the opening trigger', async () => {
    const user = userEvent.setup()
    render(<FocusHarness />)
    const trigger = screen.getByRole('button', { name: '打开发布确认' })

    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: '发布给妈妈' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog.parentElement?.parentElement).toBe(document.body)
    expect(dialog.closest('[data-testid="transformed-shell"]')).toBeNull()
    expect(screen.getByTestId('bottom-navigation')).not.toContainElement(dialog)
    const cancel = within(dialog).getByRole('button', { name: '暂不分享' })
    const confirm = within(dialog).getByRole('button', { name: '确认发布' })
    await waitFor(() => expect(cancel).toHaveFocus())

    await user.tab()
    expect(confirm).toHaveFocus()
    await user.tab()
    expect(cancel).toHaveFocus()
    await user.tab({ shift: true })
    expect(confirm).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  test('completes a diary privately, then publishes the confirmed snapshot through the room API', async () => {
    const user = userEvent.setup()
    const onBack = vi.fn()
    render(<DiaryEditor date={draftDiary.date} onBack={onBack} />)

    await screen.findByDisplayValue('旧文本')
    await user.click(screen.getByRole('button', { name: '完成日记' }))

    expect(await screen.findByRole('heading', { name: '发布给妈妈' })).toBeInTheDocument()
    expect(diaryApi.update).toHaveBeenCalledWith(9, {
      text: '旧文本', draft_text: '旧文本', status: 'confirmed',
    })
    expect(imageApi.keep).toHaveBeenCalledWith(9, [22])
    await user.click(screen.getByRole('button', { name: '确认发布' }))

    await waitFor(() => expect(roomsApi.publishDiary).toHaveBeenCalledWith('room-pair', 9, [22]))
    expect(onBack).toHaveBeenCalledOnce()
  })

  test('freezes the exact diary body and kept images while completion is in flight', async () => {
    const confirmSave = deferred<Diary>()
    vi.mocked(diaryApi.update).mockImplementationOnce(() => confirmSave.promise)
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={() => undefined} />)

    const editor = await screen.findByDisplayValue('旧文本') as HTMLTextAreaElement
    await user.clear(editor)
    await user.type(editor, '点击完成时的正文')
    const finishButton = screen.getByRole('button', { name: '完成日记' })
    await user.click(finishButton)

    expect(editor).toBeDisabled()
    expect(finishButton).toBeDisabled()
    expect(screen.getByRole('button', { name: '生成画面' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '← 返回' })).toBeDisabled()
    await user.type(editor, '不应进入发布快照')
    expect(editor).toHaveValue('点击完成时的正文')

    confirmSave.resolve({
      ...draftDiary,
      text: '点击完成时的正文',
      draft_text: '点击完成时的正文',
      status: 'confirmed',
    })
    const dialog = await screen.findByRole('dialog', { name: '发布给妈妈' })
    expect(within(dialog).getByText('点击完成时的正文')).toBeInTheDocument()
    expect(within(dialog).queryByText(/不应进入/)).not.toBeInTheDocument()
    expect(editor).toBeDisabled()
    expect(screen.getByRole('button', { name: '✨ 一键生成' })).toBeDisabled()
    await user.click(within(dialog).getByRole('button', { name: '确认发布' }))

    await waitFor(() => expect(roomsApi.publishDiary).toHaveBeenCalledWith('room-pair', 9, [22]))
    expect(diaryApi.update).toHaveBeenCalledWith(9, {
      text: '点击完成时的正文',
      draft_text: '点击完成时的正文',
      status: 'confirmed',
    })
  })

  test('blocks final actions during ai fill and freezes its resolved text into the preview', async () => {
    const fill = deferred<Diary>()
    vi.mocked(diaryApi.aiFill).mockImplementationOnce(() => fill.promise)
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={() => undefined} />)

    const editor = await screen.findByDisplayValue('旧文本') as HTMLTextAreaElement
    await user.click(screen.getByRole('button', { name: '✨ 一键生成' }))
    await user.click(screen.getByRole('button', { name: '覆盖生成' }))
    await waitFor(() => expect(diaryApi.aiFill).toHaveBeenCalledWith(9, { emotion_mode: 'warm' }))

    expect(editor).toBeDisabled()
    expect(screen.getByRole('button', { name: '← 返回' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '完成日记' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '生成画面' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '完成日记' }))
    expect(imageApi.keep).not.toHaveBeenCalled()

    fill.resolve({
      ...draftDiary,
      text: 'AI 最终正文',
      draft_text: 'AI 最终正文',
      source: 'ai',
    })
    expect(await screen.findByDisplayValue('AI 最终正文')).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '完成日记' }))
    const dialog = await screen.findByRole('dialog', { name: '发布给妈妈' })

    expect(within(dialog).getByText('AI 最终正文')).toBeInTheDocument()
    expect(diaryApi.update).toHaveBeenCalledWith(9, {
      text: 'AI 最终正文', draft_text: 'AI 最终正文', status: 'confirmed',
    })
  })

  test('blocks back during rewrite and saves the resolved rewritten text', async () => {
    const rewrite = deferred<{ original: string; rewritten: string; direction: string }>()
    vi.mocked(diaryApi.aiRewrite).mockImplementationOnce(() => rewrite.promise)
    const onBack = vi.fn()
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={onBack} />)

    const editor = await screen.findByDisplayValue('旧文本') as HTMLTextAreaElement
    editor.focus()
    editor.setSelectionRange(0, 3)
    await user.click(screen.getByRole('button', { name: '✍️ 改写选中' }))
    await user.click(screen.getByRole('button', { name: '更温暖' }))
    await waitFor(() => expect(diaryApi.aiRewrite).toHaveBeenCalledOnce())

    expect(editor).toBeDisabled()
    expect(screen.getByRole('button', { name: '← 返回' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '← 返回' }))
    expect(onBack).not.toHaveBeenCalled()

    rewrite.resolve({ original: '旧文本', rewritten: '改写后的最终正文', direction: 'warmer' })
    expect(await screen.findByDisplayValue('改写后的最终正文')).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '← 返回' }))

    await waitFor(() => expect(onBack).toHaveBeenCalledOnce())
    expect(diaryApi.update).toHaveBeenCalledWith(9, {
      text: '改写后的最终正文', draft_text: '改写后的最终正文',
    })
  })

  test('releases the content mutation lock when rewrite fails', async () => {
    vi.mocked(diaryApi.aiRewrite).mockRejectedValueOnce(new Error('rewrite offline'))
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={() => undefined} />)

    const editor = await screen.findByDisplayValue('旧文本') as HTMLTextAreaElement
    editor.focus()
    editor.setSelectionRange(0, 3)
    await user.click(screen.getByRole('button', { name: '✍️ 改写选中' }))
    await user.click(screen.getByRole('button', { name: '更温暖' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('改写失败'))
    expect(editor).toBeEnabled()
    expect(screen.getByRole('button', { name: '← 返回' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '完成日记' })).toBeEnabled()
  })

  test('ignores a late ai fill response after the editor unmounts', async () => {
    const fill = deferred<Diary>()
    vi.mocked(diaryApi.aiFill).mockImplementationOnce(() => fill.promise)
    const user = userEvent.setup()
    const view = render(<DiaryEditor date={draftDiary.date} onBack={() => undefined} />)

    await screen.findByDisplayValue('旧文本')
    await user.click(screen.getByRole('button', { name: '✨ 一键生成' }))
    await user.click(screen.getByRole('button', { name: '覆盖生成' }))
    await waitFor(() => expect(diaryApi.aiFill).toHaveBeenCalledOnce())
    view.unmount()

    await act(async () => {
      fill.resolve({ ...draftDiary, text: '迟到正文', draft_text: '迟到正文', source: 'ai' })
      await Promise.resolve(); await Promise.resolve()
    })
    expect(toast.success).not.toHaveBeenCalledWith('✨ AI 已为你写好初稿')
  })

  test('flushes the latest editor text before starting batch image generation', async () => {
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={() => undefined} />)

    const editor = await screen.findByDisplayValue('旧文本')
    await user.clear(editor)
    await user.type(editor, '刚刚补上的最新一句')
    await user.click(screen.getByRole('button', { name: '生成画面' }))

    await waitFor(() => expect(imageApi.batchGenerate).toHaveBeenCalledOnce())
    expect(diaryApi.update).toHaveBeenCalledWith(9, {
      text: '刚刚补上的最新一句', draft_text: '刚刚补上的最新一句',
    })
    expect(vi.mocked(diaryApi.update).mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(imageApi.batchGenerate).mock.invocationCallOrder[0])
  })

  test('waits for an in-flight autosave before flushing the newest text for images', async () => {
    const staleSave = deferred<Diary>()
    vi.mocked(diaryApi.update)
      .mockImplementationOnce(() => staleSave.promise)
      .mockImplementationOnce(async (_id, data) => ({
        ...draftDiary,
        text: data.text ?? draftDiary.text,
        draft_text: data.draft_text ?? draftDiary.draft_text,
      }))
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={() => undefined} />)

    const editor = await screen.findByDisplayValue('旧文本')
    await user.clear(editor)
    await user.type(editor, '正在保存的旧一句')
    await waitFor(() => expect(diaryApi.update).toHaveBeenCalledOnce(), { timeout: 1500 })

    await user.clear(editor)
    await user.type(editor, '最后才写下的新一句')
    await user.click(screen.getByRole('button', { name: '生成画面' }))
    expect(imageApi.batchGenerate).not.toHaveBeenCalled()

    staleSave.resolve({ ...draftDiary, text: '正在保存的旧一句', draft_text: '正在保存的旧一句' })
    await waitFor(() => expect(imageApi.batchGenerate).toHaveBeenCalledOnce())
    expect(diaryApi.update).toHaveBeenNthCalledWith(2, 9, {
      text: '最后才写下的新一句', draft_text: '最后才写下的新一句',
    })
  })

  test('publishes a weekly comic through an explicit partner preview', async () => {
    const comic: WeeklyComic = {
      id: 7,
      user_id: 1,
      week_start: '2026-07-27',
      week_end: '2026-08-02',
      style: 'ghibli',
      style_prompt: null,
      prompt: null,
      url: '/comic.png',
      caption: '这一周',
      created_at: '2026-08-03T08:00:00Z',
    }
    const user = userEvent.setup()
    const closeComic = vi.fn()
    render(
      <ComicResultModal
        comic={comic}
        onClose={closeComic}
        onRetry={() => undefined}
        onShare={() => undefined}
        onDelete={() => undefined}
      />,
    )

    await user.click(screen.getByRole('button', { name: '发布给妈妈' }))
    const sheet = await screen.findByRole('dialog', { name: '发布给妈妈' })
    expect(screen.queryByRole('button', { name: '重新生成' })).not.toBeInTheDocument()
    expect(within(sheet).getByRole('img', { name: '这一周' })).toHaveAttribute('src', '/comic.png')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '发布给妈妈' })).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '重新生成' })).toBeInTheDocument()
    expect(closeComic).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '发布给妈妈' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: '发布给妈妈' }))
    await user.click(within(screen.getByRole('dialog', { name: '发布给妈妈' }))
      .getByRole('button', { name: '确认发布' }))

    await waitFor(() => expect(roomsApi.publishComic).toHaveBeenCalledWith('room-pair', 7))
  })

  test('closes a weekly publication preview if its source comic changes', async () => {
    const first: WeeklyComic = {
      id: 7, user_id: 1, week_start: '2026-07-27', week_end: '2026-08-02',
      style: 'ghibli', style_prompt: null, prompt: null, url: '/comic.png',
      caption: '第一张', created_at: '2026-08-03T08:00:00Z',
    }
    const props = {
      onClose: () => undefined,
      onRetry: () => undefined,
      onShare: () => undefined,
      onDelete: () => undefined,
    }
    const user = userEvent.setup()
    const view = render(<ComicResultModal comic={first} {...props} />)
    await user.click(screen.getByRole('button', { name: '发布给妈妈' }))
    expect(screen.getByRole('dialog', { name: '发布给妈妈' })).toBeInTheDocument()

    view.rerender(<ComicResultModal comic={{ ...first, id: 8, caption: '第二张', url: '/second.png' }} {...props} />)

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '发布给妈妈' })).not.toBeInTheDocument())
    expect(screen.getByRole('img', { name: '第二张' })).toHaveAttribute('src', '/second.png')
  })

  test('flushes an immediate edit before leaving the diary editor', async () => {
    vi.useFakeTimers()
    try {
      const onBack = vi.fn()
      render(<DiaryEditor date={draftDiary.date} onBack={onBack} />)
      await act(async () => { await Promise.resolve() })
      const editor = screen.getByDisplayValue('旧文本')

      fireEvent.change(editor, { target: { value: '刚写完就返回' } })
      expect(diaryApi.update).not.toHaveBeenCalled()
      fireEvent.click(screen.getByRole('button', { name: '← 返回' }))
      await act(async () => { await Promise.resolve(); await Promise.resolve() })

      expect(diaryApi.update).toHaveBeenCalledWith(9, {
        text: '刚写完就返回', draft_text: '刚写完就返回',
      })
      expect(onBack).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  test('waits for an in-flight autosave and flushes the newest text before back', async () => {
    vi.useFakeTimers()
    try {
      const staleSave = deferred<Diary>()
      vi.mocked(diaryApi.update)
        .mockImplementationOnce(() => staleSave.promise)
        .mockImplementationOnce(async (_id, data) => ({
          ...draftDiary,
          text: data.text ?? draftDiary.text,
          draft_text: data.draft_text ?? draftDiary.draft_text,
        }))
      const onBack = vi.fn()
      render(<DiaryEditor date={draftDiary.date} onBack={onBack} />)
      await act(async () => { await Promise.resolve() })
      const editor = screen.getByDisplayValue('旧文本')

      fireEvent.change(editor, { target: { value: '在途的旧文本' } })
      await act(async () => { vi.advanceTimersByTime(600); await Promise.resolve() })
      expect(diaryApi.update).toHaveBeenCalledOnce()
      fireEvent.change(editor, { target: { value: '返回时的最新文本' } })
      fireEvent.click(screen.getByRole('button', { name: '← 返回' }))
      expect(onBack).not.toHaveBeenCalled()

      await act(async () => {
        staleSave.resolve({ ...draftDiary, text: '在途的旧文本', draft_text: '在途的旧文本' })
        await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
      })
      expect(diaryApi.update).toHaveBeenNthCalledWith(2, 9, {
        text: '返回时的最新文本', draft_text: '返回时的最新文本',
      })
      expect(onBack).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  test('stays in the editor and shows an error when back cannot save', async () => {
    vi.mocked(diaryApi.update).mockRejectedValueOnce(new Error('offline'))
    const onBack = vi.fn()
    const user = userEvent.setup()
    render(<DiaryEditor date={draftDiary.date} onBack={onBack} />)

    const editor = await screen.findByDisplayValue('旧文本')
    await user.clear(editor)
    await user.type(editor, '还没有保存的内容')
    await user.click(screen.getByRole('button', { name: '← 返回' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('离开前保存失败，请重试')
    expect(onBack).not.toHaveBeenCalled()
    expect(editor).toHaveValue('还没有保存的内容')
  })
})

describe('removed external delivery paths', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testState.room = pairedRoom
    vi.mocked(profileApi.get).mockResolvedValue({
      id: 1, nickname: '小满', avatar_url: null, signature: '', created_at: '2026-08-01T08:00:00Z',
    })
    vi.mocked(statsApi.get).mockResolvedValue({
      diary_count: 1, fragment_count: 2, longest_streak: 3, month_checkins: 4, month_days: 31,
    })
  })

  test('Mine has private export and transformation without external delivery settings', async () => {
    render(<Mine />)
    expect(await screen.findByText('导出全部日记为 PDF')).toBeInTheDocument()
    expect(screen.getByText('化解对方的牵挂')).toBeInTheDocument()
    expect(screen.queryByText('家书设置')).not.toBeInTheDocument()
  })

  test('transformed cards can only be copied', async () => {
    vi.mocked(transformApi.inbox).mockResolvedValue([
      { id: 1, from: '妈妈', received_at: '', kind: 'checkin', text: '吃饭了吗？' },
    ])
    vi.mocked(transformApi.transform).mockResolvedValue({
      nag_text: '吃饭了吗？',
      cards: { help_request: '帮我选一道菜', co_challenge: '一起吃饭', warm_echo: '已经吃啦' },
    })
    const user = userEvent.setup()
    render(<NaggingSheet open onClose={() => undefined} />)

    expect(screen.getByText('化解对方的牵挂')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /吃饭了吗/ }))
    expect(await screen.findAllByRole('button', { name: '📋 复制' })).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /寄/ })).not.toBeInTheDocument()
  })
})
