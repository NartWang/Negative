import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import DateBar from './index'
import { DateProvider } from '../../contexts/DateContext'
import { ToastProvider } from '../../contexts/ToastContext'
import { streaksApi } from '../../api/client'
import type { StreakInfo } from '../../types'
import { getLocalDateStr, parseLocalDate, weekdayLabel, addDays } from '../../utils/date'

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    streaksApi: {
      ...actual.streaksApi,
      get: vi.fn(),
    },
  }
})

const streakInfo = (overrides: Partial<StreakInfo> = {}): StreakInfo => ({
  current_streak: 0,
  longest_streak: 0,
  calendar_data: {},
  ...overrides,
} as StreakInfo)

function renderDateBar(props: React.ComponentProps<typeof DateBar> = {}) {
  return render(
    <ToastProvider>
      <DateProvider>
        <DateBar {...props} />
      </DateProvider>
    </ToastProvider>,
  )
}

describe('DateBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(streaksApi.get).mockResolvedValue(streakInfo())
  })

  test('date button shows the formatted date and weekday', () => {
    const today = getLocalDateStr()
    const expectedWeekday = weekdayLabel(parseLocalDate(today))

    renderDateBar()

    const dateButton = screen.getByRole('button', { name: '选择日期' })
    expect(dateButton).toHaveTextContent(today)
    expect(dateButton).toHaveTextContent(expectedWeekday)
    expect(expectedWeekday).toMatch(/^周[日一二三四五六]$/)
  })

  test('clicking the date opens the calendar dialog and picking a day closes it', async () => {
    const user = userEvent.setup()
    renderDateBar()

    await user.click(screen.getByRole('button', { name: '选择日期' }))
    expect(screen.getByRole('dialog', { name: '选择日期' })).toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: '9' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '选择日期' })).not.toBeInTheDocument(),
    )

    const expected = parseLocalDate(getLocalDateStr())
    expected.setDate(9)
    expect(
      screen.getByRole('button', { name: '选择日期' }),
    ).toHaveTextContent(getLocalDateStr(expected))
  })

  test('prev/next day arrows shift the displayed date', async () => {
    const user = userEvent.setup()
    const today = getLocalDateStr()
    renderDateBar()

    await user.click(screen.getByRole('button', { name: '前一天' }))
    expect(screen.getByRole('button', { name: '选择日期' })).toHaveTextContent(
      addDays(today, -1),
    )

    await user.click(screen.getByRole('button', { name: '后一天' }))
    await user.click(screen.getByRole('button', { name: '后一天' }))
    expect(screen.getByRole('button', { name: '选择日期' })).toHaveTextContent(
      addDays(today, 1),
    )
  })

  test('回到今天 appears only for non-today and resets the date', async () => {
    const user = userEvent.setup()
    renderDateBar()

    expect(screen.queryByRole('button', { name: '回到今天' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '前一天' }))
    const backToday = screen.getByRole('button', { name: '回到今天' })
    expect(backToday).toBeInTheDocument()

    await user.click(backToday)
    expect(screen.getByRole('button', { name: '选择日期' })).toHaveTextContent(
      getLocalDateStr(),
    )
    expect(screen.queryByRole('button', { name: '回到今天' })).not.toBeInTheDocument()
  })

  test('notebook entry button invokes onOpenNotebook once', async () => {
    const user = userEvent.setup()
    const onOpenNotebook = vi.fn()
    renderDateBar({ onOpenNotebook })

    const entry = screen.getByRole('button', { name: '打开故事' })
    expect(entry).toHaveTextContent('故事')
    await user.click(entry)

    expect(onOpenNotebook).toHaveBeenCalledTimes(1)
  })
})
