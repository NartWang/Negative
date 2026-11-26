import { describe, expect, test } from 'vitest'
import {
  RECORD_TIME_PATTERN,
  currentShanghaiClock,
  fragmentClockTime,
  readableClockTime,
  recordClockTime,
} from './recordTime'

describe('recordClockTime', () => {
  test('formats UTC database timestamps as Shanghai clock time', () => {
    expect(recordClockTime('2026-08-08 07:42:00')).toBe('15:42')
  })

  test('treats timezone-less ISO timestamps as UTC', () => {
    expect(recordClockTime('2026-08-08T07:42:00')).toBe('15:42')
  })

  test('returns empty text for missing values', () => {
    expect(recordClockTime(undefined)).toBe('')
  })
})

describe('RECORD_TIME_PATTERN', () => {
  test('accepts valid HH:MM clock strings', () => {
    expect(RECORD_TIME_PATTERN.test('00:00')).toBe(true)
    expect(RECORD_TIME_PATTERN.test('09:15')).toBe(true)
    expect(RECORD_TIME_PATTERN.test('23:59')).toBe(true)
  })

  test('rejects invalid clock strings', () => {
    expect(RECORD_TIME_PATTERN.test('24:00')).toBe(false)
    expect(RECORD_TIME_PATTERN.test('12:60')).toBe(false)
    expect(RECORD_TIME_PATTERN.test('9:15')).toBe(false)
    expect(RECORD_TIME_PATTERN.test('12:5')).toBe(false)
    expect(RECORD_TIME_PATTERN.test('')).toBe(false)
  })
})

describe('currentShanghaiClock', () => {
  test('returns Shanghai current clock with an injected date', () => {
    expect(currentShanghaiClock(new Date('2026-08-08T06:32:00Z'))).toBe('14:32')
  })
})

describe('fragmentClockTime', () => {
  test('prefers editable record_time over created_at', () => {
    expect(fragmentClockTime({
      record_time: '09:15', created_at: '2026-08-08 07:42:00',
    })).toBe('09:15')
  })

  test('falls back to created_at for unmigrated legacy rows', () => {
    expect(fragmentClockTime({
      record_time: null, created_at: '2026-08-08 07:42:00',
    })).toBe('15:42')
  })

  test('falls back to created_at when record_time is malformed', () => {
    expect(fragmentClockTime({
      record_time: '25:99', created_at: '2026-08-08 07:42:00',
    })).toBe('15:42')
  })
})

describe('readableClockTime', () => {
  test.each([
    ['03:05', '凌晨 3:05'],
    ['08:20', '早上 8:20'],
    ['10:30', '上午 10:30'],
    ['12:10', '中午 12:10'],
    ['15:17', '下午 3:17'],
    ['20:45', '晚上 8:45'],
  ])('turns %s into a clear Chinese period label', (input, expected) => {
    expect(readableClockTime(input)).toBe(expected)
  })
})
