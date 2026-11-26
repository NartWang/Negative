import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import FragmentComposer from './index'
import { fragmentsApi, uploadApi } from '../../api/client'
import type { Fragment } from '../../types'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fragmentsApi: {
      ...actual.fragmentsApi,
      create: vi.fn(),
    },
    uploadApi: {
      ...actual.uploadApi,
      upload: vi.fn(),
    },
  }
})

const fragment = (overrides: Partial<Fragment> = {}): Fragment => ({
  id: 10,
  date: '2026-08-08',
  content: '早餐很好吃',
  photo_url: null,
  photo_asset_id: null,
  photo_description: null,
  mood_tag: null,
  record_time: '09:10',
  created_at: '2026-08-08T01:10:00Z',
  ...overrides,
})

function renderComposer({
  date = '2026-08-08',
  onCreated = vi.fn(),
}: { date?: string; onCreated?: (fragment: Fragment) => void } = {}) {
  render(<FragmentComposer date={date} onCreated={onCreated} />)
  return { onCreated }
}

function pickPhoto(file = new File(['photo-bytes'], 'photo.jpg', { type: 'image/jpeg' })) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  fireEvent.change(input, { target: { files: [file] } })
  return input
}

describe('FragmentComposer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-08T06:32:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  test('defaults the time input to the current Shanghai clock', () => {
    renderComposer()

    expect(screen.getByLabelText('记录时间')).toHaveValue('14:32')
  })

  test('submits edited clock with text and resets to the current clock', async () => {
    vi.mocked(fragmentsApi.create).mockResolvedValue(fragment({ record_time: '09:10' }))
    const onCreated = vi.fn()
    const user = userEvent.setup()
    renderComposer({ date: '2026-08-08', onCreated })

    expect(screen.getByLabelText('记录时间')).toHaveValue('14:32')
    await user.type(screen.getByLabelText('记录此刻的随记'), '早餐很好吃')
    fireEvent.change(screen.getByLabelText('记录时间'), { target: { value: '09:10' } })
    await user.click(screen.getByRole('button', { name: '记下这一刻' }))

    expect(fragmentsApi.create).toHaveBeenCalledWith(expect.objectContaining({
      date: '2026-08-08',
      content: '早餐很好吃',
      record_time: '09:10',
    }))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ record_time: '09:10' }),
    ))
    expect(screen.getByLabelText('记录此刻的随记')).toHaveValue('')
    expect(screen.getByLabelText('记录时间')).toHaveValue('14:32')
  })

  test('submits a photo-only fragment after the upload succeeds', async () => {
    vi.mocked(uploadApi.upload).mockResolvedValue({
      url: '/api/media/abc',
      asset_id: 'asset-1',
      photo_description: '一杯咖啡',
    })
    vi.mocked(fragmentsApi.create).mockResolvedValue(fragment({
      content: '',
      photo_url: '/api/media/abc',
      photo_asset_id: 'asset-1',
    }))
    const onCreated = vi.fn()
    const user = userEvent.setup()
    renderComposer({ date: '2026-08-08', onCreated })

    expect(screen.getByRole('button', { name: '记下这一刻' })).toBeDisabled()

    pickPhoto()
    await screen.findByRole('img', { name: '待保存的照片' })
    expect(screen.getByRole('button', { name: '记下这一刻' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '记下这一刻' }))

    expect(fragmentsApi.create).toHaveBeenCalledWith(expect.objectContaining({
      date: '2026-08-08',
      content: '',
      photo_url: '/api/media/abc',
      photo_asset_id: 'asset-1',
    }))
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
  })

  test('keeps submit disabled when text is empty and no photo is attached', () => {
    renderComposer()

    expect(screen.getByRole('button', { name: '记下这一刻' })).toBeDisabled()
  })

  test('keeps text and time but clears the file input when the upload fails', async () => {
    vi.mocked(uploadApi.upload).mockRejectedValue(new Error('offline'))
    const user = userEvent.setup()
    renderComposer()

    await user.type(screen.getByLabelText('记录此刻的随记'), '早餐很好吃')
    fireEvent.change(screen.getByLabelText('记录时间'), { target: { value: '09:10' } })
    const fileInput = pickPhoto()

    expect(await screen.findByText('请重新选择照片')).toBeInTheDocument()
    expect(screen.getByLabelText('记录此刻的随记')).toHaveValue('早餐很好吃')
    expect(screen.getByLabelText('记录时间')).toHaveValue('09:10')
    expect(fileInput).toHaveValue('')
    expect(screen.getByRole('button', { name: '记下这一刻' })).toBeEnabled()
  })
})
