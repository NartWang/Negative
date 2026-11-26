import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FragmentItem from './index'
import { uploadApi } from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { Fragment } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    uploadApi: {
      ...actual.uploadApi,
      upload: vi.fn(),
    },
  }
})

const fragment = (overrides: Partial<Fragment> = {}): Fragment => ({
  id: 10,
  date: '2026-08-08',
  content: '中午阳光很软',
  photo_url: null,
  photo_asset_id: null,
  photo_description: null,
  mood_tag: null,
  record_time: null,
  created_at: '2026-08-08T06:32:00Z',
  ...overrides,
})

function renderItem(
  frag: Fragment,
  options: {
    onUpdate?: (id: number, data: unknown) => Promise<void>
    onDelete?: (id: number) => Promise<void>
  } = {},
) {
  const onUpdate = options.onUpdate ?? vi.fn().mockResolvedValue(undefined)
  const onDelete = options.onDelete ?? vi.fn().mockResolvedValue(undefined)
  render(
    <ToastProvider>
      <FragmentItem fragment={frag} onUpdate={onUpdate} onDelete={onDelete} />
    </ToastProvider>,
  )
  return { onUpdate, onDelete }
}

async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: '编辑随记' }))
  return screen.findByText('编辑随记', { selector: '.bs-title' })
}

describe('FragmentItem display', () => {
  beforeEach(() => {
    vi.mocked(uploadApi.upload).mockReset()
  })

  test('shows the record_time clock', () => {
    renderItem(fragment({ record_time: '14:32' }))
    expect(screen.getByText('下午')).toBeInTheDocument()
    expect(screen.getByText('2:32')).toBeInTheDocument()
    expect(screen.getByText('中午阳光很软')).toBeInTheDocument()
  })

  test('renders a cropped preview and opens an uncropped viewer', async () => {
    const user = userEvent.setup()
    renderItem(fragment({ record_time: '14:32', photo_url: '/api/media/a' }))

    const preview = screen.getByRole('button', { name: '查看完整照片' })
    expect(preview.querySelector('img')).toHaveClass('fragment-photo-preview')

    await user.click(preview)

    const dialog = screen.getByRole('dialog', { name: '完整照片' })
    expect(dialog.querySelector('img')).toHaveClass('image-viewer-image')
  })

  test('shows a neutral fallback when the preview image fails', () => {
    renderItem(fragment({ photo_url: '/api/media/broken' }))

    const preview = screen.getByRole('button', { name: '查看完整照片' })
    fireEvent.error(preview.querySelector('img')!)

    expect(screen.getByRole('img', { name: '照片暂时无法显示' })).toBeInTheDocument()
    expect(screen.getByText('中午阳光很软')).toBeInTheDocument()
  })

  test('shows the fallback inside the viewer when the full image fails', async () => {
    const user = userEvent.setup()
    renderItem(fragment({ photo_url: '/api/media/broken' }))

    await user.click(screen.getByRole('button', { name: '查看完整照片' }))
    const dialog = screen.getByRole('dialog', { name: '完整照片' })
    fireEvent.error(dialog.querySelector('img')!)

    expect(
      (await screen.findAllByRole('img', { name: '照片暂时无法显示' })).length,
    ).toBeGreaterThan(0)
    expect(screen.getByRole('dialog', { name: '完整照片' })).toBeInTheDocument()
  })
})

describe('FragmentItem editing', () => {
  beforeEach(() => {
    vi.mocked(uploadApi.upload).mockReset()
  })

  test('saves edited text and closes the sheet after update resolves', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    renderItem(fragment({ record_time: '14:32' }), { onUpdate })

    await openEditor(user)
    const textarea = screen.getByLabelText('随记内容')
    await user.clear(textarea)
    await user.type(textarea, '晚上改了想法')
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(onUpdate).toHaveBeenCalledWith(10, expect.objectContaining({
      content: '晚上改了想法',
      record_time: '14:32',
    }))
    await waitFor(() =>
      expect(screen.queryByText('编辑随记', { selector: '.bs-title' })).not.toBeInTheDocument(),
    )
  })

  test('keeps the sheet open with edits intact when update rejects, closes on retry success', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(undefined)
    renderItem(fragment({ record_time: '14:32' }), { onUpdate })

    await openEditor(user)
    const textarea = screen.getByLabelText('随记内容')
    await user.clear(textarea)
    await user.type(textarea, '改过的文字')
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('编辑随记', { selector: '.bs-title' })).toBeInTheDocument()
    expect(screen.getByLabelText('随记内容')).toHaveValue('改过的文字')

    await user.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() =>
      expect(screen.queryByText('编辑随记', { selector: '.bs-title' })).not.toBeInTheDocument(),
    )
    expect(onUpdate).toHaveBeenCalledTimes(2)
  })

  test('disables save when the only photo is removed from a photo-only fragment', async () => {
    const user = userEvent.setup()
    renderItem(fragment({ content: '', photo_url: '/api/media/a', record_time: '09:10' }))

    await openEditor(user)
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '移除照片' }))

    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  })

  test('sends null photo fields when the photo is removed', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    renderItem(fragment({ photo_url: '/api/media/a', photo_asset_id: 'asset-1' }), { onUpdate })

    await openEditor(user)
    await user.click(screen.getByRole('button', { name: '移除照片' }))
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(onUpdate).toHaveBeenCalledWith(10, expect.objectContaining({
      photo_asset_id: null,
      photo_url: null,
    }))
  })

  test('replaces the photo with an immediate upload', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    vi.mocked(uploadApi.upload).mockResolvedValue({
      url: '/api/media/new',
      asset_id: 'asset-new',
      photo_description: '一张新照片',
    })
    renderItem(fragment({ photo_url: '/api/media/old', photo_asset_id: 'asset-old' }), { onUpdate })

    await openEditor(user)
    const file = new File(['x'], 'new.png', { type: 'image/png' })
    const sheet = screen.getByText('编辑随记', { selector: '.bs-title' }).closest('.bs-sheet')!
    fireEvent.change(sheet.querySelector('input[type="file"]')!, { target: { files: [file] } })

    await waitFor(() => expect(uploadApi.upload).toHaveBeenCalledWith(file, { describe: true }))
    await user.click(await screen.findByRole('button', { name: '保存' }))

    expect(onUpdate).toHaveBeenCalledWith(10, expect.objectContaining({
      photo_asset_id: 'asset-new',
      photo_url: '/api/media/new',
      photo_description: '一张新照片',
    }))
  })
})

describe('FragmentItem deletion', () => {
  test('requires confirmation and keeps the record when delete rejects', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn().mockRejectedValue(new Error('offline'))
    renderItem(fragment(), { onDelete })

    await openEditor(user)
    await user.click(screen.getByRole('button', { name: '删除' }))
    const confirmBtn = await screen.findByRole('button', { name: '确认删除' })
    expect(confirmBtn).toBeInTheDocument()
    expect(onDelete).not.toHaveBeenCalled()

    await user.click(confirmBtn)
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(10))

    // delete rejected: record is still rendered and sheet stays open
    expect(screen.getAllByText('中午阳光很软').length).toBeGreaterThan(0)
    expect(screen.getByText('编辑随记', { selector: '.bs-title' })).toBeInTheDocument()
  })

  test('closes the sheet after a confirmed successful delete', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn().mockResolvedValue(undefined)
    renderItem(fragment(), { onDelete })

    await openEditor(user)
    await user.click(screen.getByRole('button', { name: '删除' }))
    await user.click(await screen.findByRole('button', { name: '确认删除' }))

    await waitFor(() =>
      expect(screen.queryByText('编辑随记', { selector: '.bs-title' })).not.toBeInTheDocument(),
    )
  })
})
