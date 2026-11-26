import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import StoryCreateMenu from './index'
import { getLocalDateStr } from '../../utils/date'

function renderMenu(props: Partial<React.ComponentProps<typeof StoryCreateMenu>> = {}) {
  const onClose = vi.fn()
  const onCreateDiary = vi.fn()
  const onCreateDailyPicturebook = vi.fn()
  const onCreateTimeStory = vi.fn()
  const onCreateMotionComic = vi.fn()
  render(
    <StoryCreateMenu
      open
      onClose={onClose}
      onCreateDiary={onCreateDiary}
      onCreateDailyPicturebook={onCreateDailyPicturebook}
      onCreateTimeStory={onCreateTimeStory}
      onCreateMotionComic={onCreateMotionComic}
      {...props}
    />,
  )
  return { onClose, onCreateDiary, onCreateDailyPicturebook, onCreateTimeStory, onCreateMotionComic }
}

describe('StoryCreateMenu', () => {
  test('shows exactly the three top-level creation entries', () => {
    renderMenu({ date: '2026-08-08' })

    const sheet = screen.getByRole('dialog', { name: '创建故事' })
    const buttons = within(sheet).getAllByRole('button')

    expect(buttons.map(button => button.textContent)).toEqual([
      expect.stringContaining('生成日记'),
      expect.stringContaining('生成绘本'),
      expect.stringContaining('生成漫剧'),
    ])
    expect(screen.queryByText('当日绘本')).not.toBeInTheDocument()
  })

  test('routes diary creation to the provided date and falls back to today', async () => {
    const user = userEvent.setup()
    const { onCreateDiary, onClose } = renderMenu()

    await user.click(screen.getByRole('button', { name: /生成日记/ }))

    expect(onCreateDiary).toHaveBeenCalledWith(getLocalDateStr())
    expect(onClose).toHaveBeenCalledOnce()
  })

  test('branches picturebook creation before opening daily picturebook', async () => {
    const user = userEvent.setup()
    const { onCreateDailyPicturebook, onClose } = renderMenu({ date: '2026-08-07' })

    await user.click(screen.getByRole('button', { name: /生成绘本/ }))

    expect(screen.getByRole('button', { name: /当日绘本/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /时光故事/ })).toBeEnabled()
    expect(onCreateDailyPicturebook).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /当日绘本/ }))

    expect(onCreateDailyPicturebook).toHaveBeenCalledWith('2026-08-07')
    expect(onClose).toHaveBeenCalledOnce()
  })

  test('opens the time story wizard from the picturebook branch', async () => {
    const user = userEvent.setup()
    const { onCreateTimeStory, onClose } = renderMenu({ date: '2026-08-07' })

    await user.click(screen.getByRole('button', { name: /生成绘本/ }))
    await user.click(screen.getByRole('button', { name: /时光故事/ }))

    expect(onCreateTimeStory).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })

  test('opens the motion comic preparation wizard from the third command', async () => {
    const user = userEvent.setup()
    const { onCreateMotionComic, onClose } = renderMenu({ date: '2026-08-08' })

    await user.click(screen.getByRole('button', { name: /生成漫剧/ }))

    expect(onCreateMotionComic).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
  })
})
