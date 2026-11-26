import { describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import MonthlyWorkCollection, {
  formatItemDate,
  groupByMonth,
} from './index'
import type { FilmFolderItem } from '../../types'

function item(partial: Partial<FilmFolderItem>): FilmFolderItem {
  return {
    id: 1,
    source_kind: 'canonical_work',
    work_kind: 'daily_picturebook',
    title: '作品',
    display_start_date: '2026-08-08',
    display_end_date: '2026-08-08',
    cover_url: null,
    completed_at: '2026-08-08T13:00:00Z',
    ...partial,
  }
}

describe('groupByMonth', () => {
  test('groups by display_end_date month, newest month first', () => {
    const groups = groupByMonth([
      item({ id: 1, display_end_date: '2026-06-02', completed_at: '2026-06-02T10:00:00Z' }),
      item({ id: 2, display_end_date: '2026-08-01', completed_at: '2026-08-01T10:00:00Z' }),
      item({ id: 3, display_end_date: '2026-08-09', completed_at: '2026-08-09T10:00:00Z' }),
    ])
    expect(groups.map(group => group.month)).toEqual(['2026-08', '2026-06'])
    expect(groups[0].items.map(entry => entry.id)).toEqual([3, 2])
  })

  test('within a month sorts by completed_at desc then id desc', () => {
    const groups = groupByMonth([
      item({ id: 5, completed_at: '2026-08-01T10:00:00Z' }),
      item({ id: 7, completed_at: '2026-08-03T10:00:00Z' }),
      item({ id: 6, completed_at: '2026-08-03T10:00:00Z' }),
    ])
    expect(groups[0].items.map(entry => entry.id)).toEqual([7, 6, 5])
  })
})

describe('formatItemDate', () => {
  test('single day and range formats', () => {
    expect(formatItemDate(item({}))).toBe('2026-08-08')
    expect(
      formatItemDate(
        item({ display_start_date: '2026-08-01', display_end_date: '2026-08-05' }),
      ),
    ).toBe('2026-08-01 ~ 2026-08-05')
  })
})

describe('MonthlyWorkCollection', () => {
  test('renders month headings and clickable cards carrying stable ids', () => {
    const onOpen = vi.fn()
    render(
      <MonthlyWorkCollection
        items={[
          item({ id: 3, title: '八月晚霞', display_end_date: '2026-08-09' }),
          item({ id: 1, title: '六月雨', display_start_date: '2026-06-02', display_end_date: '2026-06-02' }),
        ]}
        onOpen={onOpen}
        emptyHint="还没有作品"
      />,
    )
    expect(screen.getByText('2026年8月')).toBeTruthy()
    expect(screen.getByText('2026年6月')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /打开《八月晚霞》/ }))
    expect(onOpen).toHaveBeenCalledWith(
      expect.objectContaining({ id: 3, source_kind: 'canonical_work' }),
    )
  })

  test('shows the empty hint when there is nothing', () => {
    render(
      <MonthlyWorkCollection items={[]} onOpen={() => undefined} emptyHint="还没有绘本" />,
    )
    expect(screen.getByText('还没有绘本')).toBeTruthy()
  })
})
