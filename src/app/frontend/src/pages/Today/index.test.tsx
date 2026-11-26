import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import Today from './index'
import { diaryApi, fragmentsApi } from '../../api/client'
import * as client from '../../api/client'
import { DateProvider } from '../../contexts/DateContext'
import { ToastProvider } from '../../contexts/ToastContext'
import type { Fragment } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    schedulesApi: {
      ...actual.schedulesApi,
      list: vi.fn(),
    },
    fragmentsApi: {
      ...actual.fragmentsApi,
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    diaryApi: {
      ...actual.diaryApi,
      get: vi.fn(),
    },
    uploadApi: {
      ...actual.uploadApi,
      upload: vi.fn(),
    },
  }
})

const fragment = (overrides: Partial<Fragment> = {}): Fragment => ({
  id: 10,
  date: '2026-08-06',
  content: '中午阳光很软',
  photo_url: null,
  photo_asset_id: null,
  photo_description: null,
  mood_tag: null,
  record_time: null,
  created_at: '2026-08-06T12:00:00Z',
  ...overrides,
})

function renderToday(options: {
  onOpenEditor?: ReturnType<typeof vi.fn>
  onOpenNotebook?: (date: string) => void
} = {}) {
  const handle = options.onOpenEditor ?? vi.fn()
  const onOpenNotebook = options.onOpenNotebook ?? vi.fn()
  const utils = render(
    <DateProvider>
      <ToastProvider>
        <Today onOpenEditor={handle} onOpenNotebook={onOpenNotebook} />
      </ToastProvider>
    </DateProvider>,
  )
  return { handle, onOpenNotebook, unmount: utils.unmount }
}

async function openSourcePicker(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /生成今日日记|生成 .* 的日记|打开 .* 的日记/ }))
  const sheetTitle = await screen.findByText('选择生成素材')
  const picker = (sheetTitle.closest('.bs-sheet') as HTMLElement).querySelector('.source-picker') as HTMLElement
  return picker
}

describe('Today fragment-only record page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fragmentsApi.list).mockResolvedValue([])
    vi.mocked(diaryApi.get).mockResolvedValue(null)
  })

  test('loads only fragments and renders composer before the 已记下 timeline', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([fragment({ id: 10 })])
    renderToday()

    expect(await screen.findByRole('heading', { name: '随手记' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '已记下' })).toBeInTheDocument()
    expect(fragmentsApi.list).toHaveBeenCalled()
    expect(vi.mocked(client.schedulesApi.list)).not.toHaveBeenCalled()
    expect(screen.queryByText('感受（可选）')).not.toBeInTheDocument()
    expect(screen.queryByText('今天的日程')).not.toBeInTheDocument()

    const composer = screen.getByRole('heading', { name: '随手记' })
    const timeline = screen.getByRole('region', { name: '已记下' })
    expect(
      composer.compareDocumentPosition(timeline) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  test('fragments are sorted by record_time descending', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({ id: 1, content: '早上的一条', record_time: '08:15', created_at: '2026-08-06T00:15:00Z' }),
      fragment({ id: 2, content: '晚上的一条', record_time: '21:40', created_at: '2026-08-06T13:40:00Z' }),
      fragment({ id: 3, content: '中午的一条', record_time: '12:05', created_at: '2026-08-06T04:05:00Z' }),
    ])

    renderToday()

    const region = await screen.findByRole('region', { name: '已记下' })
    const items = await within(region).findAllByRole('article')
    expect(items.map(item => item.textContent)).toEqual([
      expect.stringContaining('晚上的一条'),
      expect.stringContaining('中午的一条'),
      expect.stringContaining('早上的一条'),
    ])
  })

  test('已记下 shows the fragment count and an empty state inside the container when zero', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([])
    renderToday()

    const region = await screen.findByRole('region', { name: '已记下' })
    expect(within(region).getByText('0')).toBeInTheDocument()
    await waitFor(() => expect(within(region).getByText(/还没有记录|一条都没有|空空|记下第一条/)).toBeInTheDocument())
    expect(within(region).queryByRole('article')).not.toBeInTheDocument()
  })

  test('已记下 count badge matches the loaded fragments', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({ id: 1, content: '一' }),
      fragment({ id: 2, content: '二' }),
      fragment({ id: 3, content: '三' }),
    ])
    renderToday()

    const region = await screen.findByRole('region', { name: '已记下' })
    await within(region).findAllByRole('article')
    expect(within(region).getByText('3')).toBeInTheDocument()
  })

  test('generate-btn appears only when fragments exist and sits after the timeline region in normal flow', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([])
    const { unmount } = renderToday()

    await screen.findByRole('region', { name: '已记下' })
    expect(screen.queryByRole('button', { name: /生成今日日记|生成 .* 的日记|打开 .* 的日记/ })).not.toBeInTheDocument()
    unmount()

    vi.mocked(fragmentsApi.list).mockResolvedValue([fragment({ id: 10 })])
    renderToday()

    const generateBtn = await screen.findByRole('button', { name: /生成今日日记|生成 .* 的日记|打开 .* 的日记/ })
    expect(generateBtn).toHaveClass('generate-btn')
    const timeline = screen.getByRole('region', { name: '已记下' })
    expect(
      timeline.compareDocumentPosition(generateBtn) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  test('uses diary existence instead of today status for the action label', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([fragment({ id: 10 })])
    vi.mocked(diaryApi.get).mockResolvedValue({ id: 88 } as any)
    renderToday()

    expect(await screen.findByRole('button', { name: /打开 .* 的日记/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '生成今日日记' })).not.toBeInTheDocument()
  })

  test('source picker shows only the 随手记 group and confirm sends empty schedule_ids with selected fragments', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({ id: 21, content: '街角' }),
      fragment({ id: 22, content: '晚风' }),
    ])
    const user = userEvent.setup()
    const { handle } = renderToday()

    await screen.findByText('街角')
    const picker = await openSourcePicker(user)

    expect(within(picker).getByText('随手记')).toBeInTheDocument()
    expect(within(picker).queryByText('今天的日程')).not.toBeInTheDocument()

    const checkboxes = within(picker).getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(2)
    expect(checkboxes.every(box => (box as HTMLInputElement).checked)).toBe(true)

    await user.click(checkboxes[0])
    await user.click(within(picker).getByRole('button', { name: '用 1 条素材生成' }))

    await waitFor(() => expect(handle).toHaveBeenCalledOnce())
    const request = handle.mock.calls[0][0] as {
      date: string
      selection: { schedule_ids: number[]; fragment_ids: number[] }
    }
    expect(request.selection.schedule_ids).toEqual([])
    expect(request.selection.fragment_ids).toEqual([22])
    expect(typeof request.date).toBe('string')
  })

  test('deleting a fragment also removes it from the source picker selection', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({ id: 21, content: '街角' }),
      fragment({ id: 22, content: '晚风' }),
    ])
    vi.mocked(fragmentsApi.delete).mockResolvedValue({ message: 'ok' })
    const user = userEvent.setup()
    const { handle } = renderToday()

    await screen.findByText('街角')

    // Delete fragment 21 through the editor sheet
    const region = screen.getByRole('region', { name: '已记下' })
    const articles = within(region).getAllByRole('article')
    const first = articles.find(item => item.textContent?.includes('街角')) as HTMLElement
    await user.click(within(first).getByRole('button', { name: '编辑随记' }))
    const deleteBtn = await screen.findByRole('button', { name: /删除/ })
    await user.click(deleteBtn)
    const confirmBtn = await screen.findByRole('button', { name: /确认删除|确定|删除这条/ })
    await user.click(confirmBtn)
    await waitFor(() => expect(fragmentsApi.delete).toHaveBeenCalledWith(21))
    await waitFor(() => expect(screen.queryByText('街角')).not.toBeInTheDocument())

    const picker = await openSourcePicker(user)
    const checkboxes = within(picker).getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(1)

    await user.click(within(picker).getByRole('button', { name: '用 1 条素材生成' }))
    await waitFor(() => expect(handle).toHaveBeenCalledOnce())
    const request = handle.mock.calls[0][0] as {
      selection: { schedule_ids: number[]; fragment_ids: number[] }
    }
    expect(request.selection.fragment_ids).toEqual([22])
    expect(request.selection.schedule_ids).toEqual([])
  })

  test('source confirmation is single-flight before React state flushes', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([fragment({ id: 21 })])
    const { handle } = renderToday()

    await screen.findByText('中午阳光很软')
    fireEvent.click(screen.getByRole('button', { name: /生成今日日记|生成 .* 的日记|打开 .* 的日记/ }))
    const confirm = await screen.findByRole('button', { name: '用 1 条素材生成' })
    act(() => {
      confirm.click()
      expect(confirm).toHaveTextContent('正在打开')
      confirm.click()
    })

    expect(handle).toHaveBeenCalledTimes(1)
  })

  test('load failure shows role alert with retry; retry reloads and success clears the error', async () => {
    vi.mocked(fragmentsApi.list)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce([fragment({ id: 10, content: '恢复后的一条' })])
    const user = userEvent.setup()
    renderToday()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/加载失败|失败/)

    await user.click(screen.getByRole('button', { name: '重试加载' }))

    expect(await screen.findByText('恢复后的一条')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fragmentsApi.list).toHaveBeenCalledTimes(2)
  })

  test('photo-only fragments can be edited and saved without text', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({
        id: 12,
        content: null,
        photo_url: 'https://example.com/photo.jpg',
        created_at: '2026-08-08 07:42:00',
      }),
    ])
    vi.mocked(fragmentsApi.update).mockResolvedValue(fragment({
      id: 12,
      content: null,
      photo_url: 'https://example.com/photo.jpg',
      created_at: '2026-08-08 07:42:00',
    }))
    const user = userEvent.setup()

    renderToday()

    await screen.findByRole('button', { name: '查看完整照片' })
    await user.click(screen.getByRole('button', { name: '编辑随记' }))
    expect(screen.getByText('编辑随记')).toBeInTheDocument()

    const save = screen.getByRole('button', { name: '保存' })
    expect(save).not.toBeDisabled()
    await user.click(save)

    await waitFor(() => expect(fragmentsApi.update).toHaveBeenCalledWith(12, { content: '', record_time: '15:42' }))
    await waitFor(() => expect(screen.queryByText('编辑随记')).not.toBeInTheDocument())
  })

  test('photo-only source picker uses a neutral photo label instead of the AI description', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({
        id: 44,
        content: null,
        photo_url: '/api/media/asset-44',
        photo_asset_id: 'asset-44',
        photo_description: 'AI saw a private receipt',
      }),
    ])
    const user = userEvent.setup()

    renderToday()

    await screen.findByRole('button', { name: '查看完整照片' })
    const picker = await openSourcePicker(user)
    expect(within(picker).getByText('一张照片')).toBeInTheDocument()
    expect(within(picker).queryByText('AI saw a private receipt')).not.toBeInTheDocument()
  })

  test('fragment update failure keeps the editor sheet open', async () => {
    vi.mocked(fragmentsApi.list).mockResolvedValue([
      fragment({ id: 12, content: '原始文字' }),
    ])
    vi.mocked(fragmentsApi.update).mockRejectedValue(new Error('save failed'))
    const user = userEvent.setup()

    renderToday()

    await screen.findByText('原始文字')
    await user.click(screen.getByRole('button', { name: '编辑随记' }))
    expect(screen.getByText('编辑随记')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(fragmentsApi.update).toHaveBeenCalled())
    // Sheet must stay open on failure so the user can retry
    expect(screen.getByText('编辑随记')).toBeInTheDocument()
  })
})
