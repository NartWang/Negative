import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import SafeImage from './index'

describe('SafeImage', () => {
  test('shows the fallback placeholder after the image errors', () => {
    render(<SafeImage src="/api/media/broken" alt="随记照片" />)

    fireEvent.error(screen.getByAltText('随记照片'))

    expect(screen.queryByRole('img', { name: '随记照片' })).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: '照片暂时无法显示' })).toBeInTheDocument()
  })

  test('renders the image again when src changes after a failure', () => {
    const { rerender } = render(<SafeImage src="/api/media/broken" alt="随记照片" />)

    fireEvent.error(screen.getByAltText('随记照片'))
    expect(screen.getByRole('img', { name: '照片暂时无法显示' })).toBeInTheDocument()

    rerender(<SafeImage src="/api/media/fresh" alt="随记照片" />)

    expect(screen.getByAltText('随记照片')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: '照片暂时无法显示' })).not.toBeInTheDocument()
  })

  test('uses a custom fallback label when provided', () => {
    render(<SafeImage src="/api/media/broken" alt="随记照片" fallbackLabel="日记图片暂时无法显示" />)

    fireEvent.error(screen.getByAltText('随记照片'))

    expect(screen.getByRole('img', { name: '日记图片暂时无法显示' })).toBeInTheDocument()
  })
})
