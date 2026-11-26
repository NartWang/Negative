import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import VisibilitySheet from './index'
import { storyApi } from '../../api/client'
import type { StoryWork, WorkAudience } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    storyApi: {
      ...actual.storyApi,
      getAudience: vi.fn(),
      replaceAudience: vi.fn(),
    },
  }
})

const work = (overrides: Partial<StoryWork> = {}): StoryWork => ({
  id: 42,
  owner_user_id: 1,
  source_diary_id: null,
  title: '我的一页',
  medium: 'picture_book',
  narrative_mode: 'true_record',
  style: 'watercolor',
  selected_segments: ['今天很好'],
  forbidden_content: null,
  status: 'ready',
  assets: [],
  created_at: '2026-08-04T08:00:00Z',
  updated_at: '2026-08-04T08:00:00Z',
  ...overrides,
})

const audience = (
  subscription_id: number,
  selected: boolean,
  nickname = '阿禾',
): WorkAudience => ({
  id: 100 + subscription_id,
  subscription_id,
  owner_user_id: 1,
  subscriber_user_id: 99,
  status: 'active',
  selected,
  created_at: '2026-08-04T08:00:00Z',
  subscriber: { id: 99, nickname, avatar_url: null },
})

function renderSheet(open = true, w: StoryWork | null = work()) {
  const onClose = vi.fn()
  render(<VisibilitySheet open={open} work={w} onClose={onClose} />)
  return { onClose }
}

describe('VisibilitySheet per-work audience', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storyApi.getAudience).mockResolvedValue({ items: [] })
    vi.mocked(storyApi.replaceAudience).mockResolvedValue({ items: [] })
  })

  test('shows loading state then echoes existing selection from getAudience', async () => {
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, true), audience(9, false, '小蓝')],
    })

    renderSheet()

    expect(screen.getByRole('status')).toHaveTextContent('正在读取…')
    const checked = await screen.findAllByRole('checkbox')
    expect(checked).toHaveLength(2)
    expect((checked[0] as HTMLInputElement).checked).toBe(true)
    expect((checked[1] as HTMLInputElement).checked).toBe(false)
    expect(storyApi.getAudience).toHaveBeenCalledWith(42)
  })

  test('save calls replaceAudience with the complete checked list and closes', async () => {
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, true), audience(9, false, '小蓝')],
    })
    const user = userEvent.setup()
    const { onClose } = renderSheet()

    const second = await screen.findByText('小蓝')
    await user.click(second.parentElement!.querySelector('input')!)

    await user.click(screen.getByRole('button', { name: '保存可见范围' }))

    await waitFor(() =>
      expect(storyApi.replaceAudience).toHaveBeenCalledWith(42, [7, 9]),
    )
    expect(onClose).toHaveBeenCalled()
  })

  test('save with empty selection calls replaceAudience with an empty array', async () => {
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, true)],
    })
    const user = userEvent.setup()

    renderSheet()

    const row = await screen.findByText('阿禾')
    await user.click(row.parentElement!.querySelector('input')!)

    await user.click(screen.getByRole('button', { name: '保存可见范围' }))

    await waitFor(() => expect(storyApi.replaceAudience).toHaveBeenCalledWith(42, []))
  })

  test('save button is disabled while loading and saving; save failure retains the draft', async () => {
    let rejectSave!: (err: Error) => void
    vi.mocked(storyApi.getAudience).mockResolvedValue({
      items: [audience(7, false)],
    })
    vi.mocked(storyApi.replaceAudience).mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectSave = reject
        }),
    )
    const user = userEvent.setup()
    const { onClose } = renderSheet()

    // Loading state: status text appears, save button is disabled.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '保存可见范围' })).toBeDisabled(),
    )
    await screen.findByText('阿禾')
    const saveBtn = screen.getByRole('button', { name: '保存可见范围' })
    expect(saveBtn).not.toBeDisabled()

    // Saving state: save click triggers replaceAudience; button stays disabled while pending.
    await user.click(saveBtn)
    await waitFor(() => expect(storyApi.replaceAudience).toHaveBeenCalledWith(42, []))
    expect(saveBtn).toBeDisabled()

    // Failure: error surfaces, draft selection retained, sheet stays open.
    rejectSave(new Error('boom'))
    expect(await screen.findByRole('alert')).toHaveTextContent('保存可见范围失败')
    await waitFor(() => expect(saveBtn).not.toBeDisabled())
    expect(onClose).not.toHaveBeenCalled()
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
  })

  test('does not expose publish/send/revoke language', async () => {
    renderSheet()
    await screen.findByText(/选择谁可以在回响里看到/)

    expect(screen.queryByText('发布')).not.toBeInTheDocument()
    expect(screen.queryByText('发送')).not.toBeInTheDocument()
    expect(screen.queryByText('撤回')).not.toBeInTheDocument()
    expect(screen.queryByText('发布到我们')).not.toBeInTheDocument()
  })

  test('a 404 from getAudience surfaces the source error message (no refresh path)', async () => {
    vi.mocked(storyApi.getAudience).mockRejectedValue(new Error('not found'))

    renderSheet()

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取可见范围')
    expect(screen.queryByRole('button', { name: /重试|刷新/ })).not.toBeInTheDocument()
  })
})