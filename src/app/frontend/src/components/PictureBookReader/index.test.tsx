import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import PictureBookReader from './index'
import type { PicturebookPage } from '../../types'

const makePages = (): PicturebookPage[] =>
  Array.from({ length: 9 }, (_, pageIndex) => ({
    page_index: pageIndex,
    image_id: pageIndex === 0 ? 'cover' : `page-${pageIndex}`,
    caption: pageIndex === 0 ? '星星船的封面' : `星星船第 ${pageIndex} 幕`,
    image_url: `https://example.test/book-${pageIndex}.jpg`,
    status: 'ready',
    error: null,
  }))

function renderReader(pages = makePages()) {
  render(<PictureBookReader pages={pages} title="星星船" />)
  return screen.getByRole('region', { name: '星星船' })
}

describe('PictureBookReader', () => {
  test('starts on the cover and keeps previous disabled at the boundary', () => {
    const reader = renderReader()

    expect(within(reader).getByRole('img', { name: '星星船的封面' })).toHaveAttribute(
      'src',
      'https://example.test/book-0.jpg',
    )
    expect(within(reader).getByText('封面')).toBeInTheDocument()
    expect(within(reader).getByText('星星船的封面')).toBeInTheDocument()
    expect(within(reader).getByRole('button', { name: '上一页' })).toBeDisabled()
    expect(within(reader).getByRole('button', { name: '下一页' })).not.toBeDisabled()
    expect(reader.querySelector('.picturebook-reader-grid')).not.toBeInTheDocument()
  })

  test('next and previous icon buttons navigate through pages and disable at the end', async () => {
    const user = userEvent.setup()
    const reader = renderReader()

    await user.click(within(reader).getByRole('button', { name: '下一页' }))
    expect(within(reader).getByText('第 1 页，共 8 页')).toBeInTheDocument()
    expect(reader.querySelector('.picturebook-reader-count')).not.toBeInTheDocument()
    expect(within(reader).queryByText('2 / 9')).not.toBeInTheDocument()
    expect(within(reader).getByRole('img', { name: '星星船第 1 幕' })).toHaveAttribute(
      'src',
      'https://example.test/book-1.jpg',
    )
    expect(within(reader).getByRole('button', { name: '上一页' })).not.toBeDisabled()

    for (let i = 0; i < 7; i += 1) {
      await user.click(within(reader).getByRole('button', { name: '下一页' }))
    }
    expect(within(reader).getByText('第 8 页，共 8 页')).toBeInTheDocument()
    expect(within(reader).getByRole('button', { name: '下一页' })).toBeDisabled()

    await user.click(within(reader).getByRole('button', { name: '上一页' }))
    expect(within(reader).getByText('第 7 页，共 8 页')).toBeInTheDocument()
  })

  test('left and right keyboard navigation works after the reader is focused', async () => {
    const user = userEvent.setup()
    const reader = renderReader()

    reader.focus()
    await user.keyboard('{ArrowRight}')
    expect(within(reader).getByText('第 1 页，共 8 页')).toBeInTheDocument()

    await user.keyboard('{ArrowLeft}')
    expect(within(reader).getByText('封面')).toBeInTheDocument()
  })

  test('horizontal pointer drag only turns pages past a deliberate threshold', async () => {
    const user = userEvent.setup()
    const reader = renderReader()
    const stage = within(reader).getByTestId('picturebook-reader-stage')

    await user.pointer([
      { target: stage, coords: { clientX: 240 }, keys: '[MouseLeft>]' },
      { target: stage, coords: { clientX: 205 } },
      { target: stage, coords: { clientX: 205 }, keys: '[/MouseLeft]' },
    ])
    expect(within(reader).getByText('封面')).toBeInTheDocument()

    await user.pointer([
      { target: stage, coords: { clientX: 240 }, keys: '[MouseLeft>]' },
      { target: stage, coords: { clientX: 120 } },
      { target: stage, coords: { clientX: 120 }, keys: '[/MouseLeft]' },
    ])
    expect(within(reader).getByText('第 1 页，共 8 页')).toBeInTheDocument()

    await user.pointer([
      { target: stage, coords: { clientX: 120 }, keys: '[MouseLeft>]' },
      { target: stage, coords: { clientX: 245 } },
      { target: stage, coords: { clientX: 245 }, keys: '[/MouseLeft]' },
    ])
    expect(within(reader).getByText('封面')).toBeInTheDocument()
  })

  test('image errors preserve the caption and controls while offering reload', async () => {
    const user = userEvent.setup()
    const onReloadImage = vi.fn()
    render(<PictureBookReader pages={makePages()} title="星星船" onReloadImage={onReloadImage} />)
    const reader = screen.getByRole('region', { name: '星星船' })

    fireEvent.error(within(reader).getByRole('img', { name: '星星船的封面' }))

    expect(within(reader).getByText('星星船的封面')).toBeInTheDocument()
    expect(within(reader).getByRole('button', { name: '上一页' })).toBeDisabled()
    const reload = within(reader).getByRole('button', { name: '重新加载图片' })
    expect(reload).toBeInTheDocument()

    await user.click(reload)
    expect(onReloadImage).toHaveBeenCalledWith(expect.objectContaining({ page_index: 0 }))
  })

  test('sorts by page index without dropping or reordering pages', async () => {
    const user = userEvent.setup()
    const shuffled = [makePages()[2], makePages()[0], makePages()[1]]
    const reader = renderReader(shuffled)

    expect(within(reader).getByRole('img', { name: '星星船的封面' })).toBeInTheDocument()
    await user.click(within(reader).getByRole('button', { name: '下一页' }))
    expect(within(reader).getByRole('img', { name: '星星船第 1 幕' })).toBeInTheDocument()
    await user.click(within(reader).getByRole('button', { name: '下一页' }))
    expect(within(reader).getByRole('img', { name: '星星船第 2 幕' })).toBeInTheDocument()
    expect(within(reader).getByRole('button', { name: '下一页' })).toBeDisabled()
  })
})
