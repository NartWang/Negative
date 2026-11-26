import { describe, expect, test } from 'vitest'
import {
  customRange,
  datesBetweenInclusive,
  previousWeekRange,
  thisWeekRange,
  weekStartOf,
} from './week'

describe('Asia/Shanghai week ranges', () => {
  test('uses Monday through Sunday for this week without depending on machine timezone', () => {
    const anchor = new Date('2026-08-02T16:30:00.000Z')

    expect(thisWeekRange(anchor)).toEqual({
      start: '2026-08-03',
      end: '2026-08-09',
    })
    expect(weekStartOf('2026-08-09')).toBe('2026-08-03')
  })

  test('returns the full previous Monday-Sunday range in Asia/Shanghai', () => {
    const anchor = new Date('2026-08-08T03:00:00.000Z')

    expect(previousWeekRange(anchor)).toEqual({
      start: '2026-07-27',
      end: '2026-08-02',
    })
  })

  test('keeps custom ranges inclusive and caps them at 31 days', () => {
    expect(customRange('2026-08-01', '2026-08-31')).toEqual({
      start: '2026-08-01',
      end: '2026-08-31',
    })
    expect(datesBetweenInclusive('2026-08-29', '2026-09-02')).toEqual([
      '2026-08-29',
      '2026-08-30',
      '2026-08-31',
      '2026-09-01',
      '2026-09-02',
    ])
    expect(() => customRange('2026-08-01', '2026-09-01')).toThrow('自选范围最长 31 天')
  })
})
