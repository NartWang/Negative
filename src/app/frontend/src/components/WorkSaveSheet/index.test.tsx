import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import WorkSaveSheet from './index'
import type { WorkSaveImage } from './index'

const image = (overrides: Partial<WorkSaveImage> = {}): WorkSaveImage => ({
  id: 1,
  url: 'https://example.test/img-1.png',
  asset_id: 'asset-1',
  alt: '画面 1',
  ...overrides,
})

function renderSheet(overrides: {
  open?: boolean
  images?: WorkSaveImage[]
  selectedImageIds?: number[]
  kind?: 'diary' | 'weekly_comic'
  onConfirm?: (imageIds: number[]) => Promise<void> | void
  onClose?: () => void
} = {}) {
  const onConfirm = overrides.onConfirm ?? vi.fn(() => Promise.resolve())
  const onClose = overrides.onClose ?? vi.fn()
  render(
    <WorkSaveSheet
      open={overrides.open ?? true}
      kind={overrides.kind ?? 'diary'}
      title="2026-08-04 的故事"
      summary="今天阳光很软"
      images={overrides.images ?? [image()]}
      selectedImageIds={overrides.selectedImageIds}
      onClose={onClose}
      onConfirm={onConfirm}
    />,
  )
  return { onConfirm, onClose }
}

describe('WorkSaveSheet private work builder', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('renders private-by-default wording without publish/send/revoke language', () => {
    renderSheet()

    expect(screen.getByText(/保存作品/)).toBeInTheDocument()
    expect(screen.getByText(/放入故事架/)).toBeInTheDocument()
    expect(screen.getByText(/默认仅自己可见/)).toBeInTheDocument()
    expect(screen.queryByText('发布')).not.toBeInTheDocument()
    expect(screen.queryByText('发送')).not.toBeInTheDocument()
    expect(screen.queryByText('撤回')).not.toBeInTheDocument()
    expect(screen.queryByText('发布到我们')).not.toBeInTheDocument()
  })

  test('images without asset_id render disabled with a regenerate explanation', () => {
    const images = [
      image({ id: 1, asset_id: 'asset-1' }),
      image({ id: 2, asset_id: null, alt: '画面 2' }),
    ]
    renderSheet({ images, selectedImageIds: [1, 2] })

    const available = screen.getByLabelText('选择画面 1') as HTMLInputElement
    const disabled = screen.getByLabelText('画面 2 暂不可作为作品素材') as HTMLInputElement
    expect(available).not.toBeDisabled()
    expect(disabled).toBeDisabled()
    expect(screen.getByText('需重新生成后可加入作品')).toBeInTheDocument()
  })

  test('save success calls onConfirm with the selected images that have an asset_id then closes', async () => {
    const images = [
      image({ id: 1, asset_id: 'asset-1' }),
      image({ id: 2, asset_id: 'asset-2', alt: '画面 2' }),
      image({ id: 3, asset_id: null, alt: '画面 3' }),
    ]
    const { onConfirm, onClose } = renderSheet({
      images,
      selectedImageIds: [1, 2, 3],
    })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '保存到故事' }))

    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith([1, 2]))
    expect(onClose).toHaveBeenCalled()
  })

  test('save failure retains input and shows an error without closing', async () => {
    const { onConfirm, onClose } = renderSheet({
      onConfirm: vi.fn(() => Promise.reject(new Error('网络超时'))),
    })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '保存到故事' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('网络超时')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '保存到故事' })).not.toBeDisabled()
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  test('close button dismisses the sheet', async () => {
    const { onClose } = renderSheet()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: '暂不保存' }))

    expect(onClose).toHaveBeenCalledOnce()
  })
})