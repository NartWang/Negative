import { describe, expect, test } from 'vitest'
import {
  PICTUREBOOK_NOMINAL_TOTAL_MS,
  interpolateProgress,
  motionComicProgress,
  picturebookProgress,
  picturebookProgressWindow,
} from './generationProgress'

describe('picturebookProgress', () => {
  test('stage floors match the spec', () => {
    expect(picturebookProgress({ stage: 'queued', ready: 0, total: 9, done: false })).toBe(0)
    expect(picturebookProgress({ stage: 'character', ready: 0, total: 9, done: false })).toBe(3)
    expect(picturebookProgress({ stage: 'story', ready: 0, total: 9, done: false })).toBe(8)
    expect(picturebookProgress({ stage: 'prompts', ready: 0, total: 9, done: false })).toBe(15)
  })

  test('rendering interpolates by ready pages', () => {
    expect(
      picturebookProgress({ stage: 'rendering', ready: 1, total: 9, done: false }),
    ).toBeCloseTo(20 + (1 / 9) * 80, 5)
    expect(
      picturebookProgress({ stage: 'rendering', ready: 9, total: 9, done: false }),
    ).toBe(99)
  })

  test('done reaches 100 only when confirmed', () => {
    expect(picturebookProgress({ stage: 'done', ready: 9, total: 9, done: true })).toBe(100)
    expect(picturebookProgress({ stage: 'done', ready: 9, total: 9, done: false })).toBe(100)
  })

  test('zero total never divides by zero', () => {
    expect(picturebookProgress({ stage: 'rendering', ready: 0, total: 0, done: false })).toBe(20)
  })
})

describe('motionComicProgress', () => {
  test('stage floors match the spec', () => {
    expect(motionComicProgress({ stage: 'queued', ready: 0, total: 8, done: false })).toBe(0)
    expect(motionComicProgress({ stage: 'frames', ready: 0, total: 8, done: false })).toBe(5)
    expect(motionComicProgress({ stage: 'submitting', ready: 0, total: 8, done: false })).toBe(10)
    expect(motionComicProgress({ stage: 'stitching', ready: 8, total: 8, done: false })).toBe(95)
  })

  test('rendering interpolates and never shows 100 while stitching', () => {
    expect(
      motionComicProgress({ stage: 'rendering', ready: 4, total: 8, done: false }),
    ).toBeCloseTo(15 + 0.5 * 75, 5)
    expect(
      motionComicProgress({ stage: 'rendering', ready: 8, total: 8, done: false }),
    ).toBeLessThanOrEqual(99)
    expect(motionComicProgress({ stage: 'done', ready: 8, total: 8, done: true })).toBe(100)
  })
})

describe('picturebookProgressWindow', () => {
  test('rendering exposes the real floor, next page boundary and nominal interval', () => {
    const window = picturebookProgressWindow({
      stage: 'rendering', ready: 2, total: 9, done: false,
    })
    expect(window.real).toBeCloseTo(20 + (2 / 9) * 80, 5)
    expect(window.next).toBeCloseTo(20 + (3 / 9) * 80, 5)
    expect(window.nominalMs).toBeCloseTo(PICTUREBOOK_NOMINAL_TOTAL_MS / 9, 5)
  })

  test('non-rendering stages stay flat without a nominal interval', () => {
    for (const stage of ['queued', 'character', 'story', 'prompts']) {
      const window = picturebookProgressWindow({ stage, ready: 0, total: 9, done: false })
      expect(window.next).toBe(window.real)
      expect(window.nominalMs).toBeNull()
    }
  })

  test('a done input stays flat at 100', () => {
    const window = picturebookProgressWindow({
      stage: 'rendering', ready: 9, total: 9, done: true,
    })
    expect(window.real).toBe(100)
    expect(window.next).toBe(100)
    expect(window.nominalMs).toBeNull()
  })

  test('all pages ready but unconfirmed caps the next milestone at 99', () => {
    const window = picturebookProgressWindow({
      stage: 'rendering', ready: 9, total: 9, done: false,
    })
    expect(window.real).toBe(99)
    expect(window.next).toBe(99)
    expect(window.nominalMs).toBeCloseTo(PICTUREBOOK_NOMINAL_TOTAL_MS / 9, 5)
  })

  test('zero or invalid totals never divide by zero', () => {
    const window = picturebookProgressWindow({
      stage: 'rendering', ready: 0, total: 0, done: false,
    })
    expect(window.real).toBe(20)
    expect(window.next).toBe(20)
    expect(window.nominalMs).toBeNull()
  })

  test('nominal total is the 180-second contract', () => {
    expect(PICTUREBOOK_NOMINAL_TOTAL_MS).toBe(180_000)
  })
})

describe('interpolateProgress', () => {
  test('monotonic and capped before the next milestone', () => {
    expect(interpolateProgress(28, 36, 0, 20_000)).toBe(28)
    const mid = interpolateProgress(28, 36, 10_000, 20_000)
    expect(mid).toBeGreaterThan(28)
    expect(mid).toBeLessThanOrEqual(36)
    expect(interpolateProgress(28, 36, 60_000, 20_000)).toBe(36)
  })

  test('never exceeds 99 even with huge elapsed time', () => {
    expect(interpolateProgress(98.5, 100, 999_999, 1000)).toBe(99)
  })

  test('zero nominal duration returns the floor', () => {
    expect(interpolateProgress(40, 50, 100, 0)).toBe(40)
  })
})
