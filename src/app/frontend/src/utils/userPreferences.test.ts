import { beforeEach, describe, expect, test } from 'vitest'
import {
  DEFAULT_DRAW_STYLE,
  getDrawStylePreference,
  getEmotionModePreference,
  setUserPreference,
  userPreferenceKey,
} from './userPreferences'

describe('emotion mode preferences', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  test.each(['real', 'imagery'] as const)('keeps a stored %s value', mode => {
    setUserPreference(7, 'emotionMode', mode)

    expect(getEmotionModePreference(7)).toBe(mode)
  })

  test.each(['warm', 'humor', 'poetic', 'custom'])(
    'migrates the legacy %s value to imagery',
    legacyMode => {
      localStorage.setItem(userPreferenceKey(7, 'emotionMode'), legacyMode)

      expect(getEmotionModePreference(7)).toBe('imagery')
    },
  )

  test('uses real for a missing or unknown value', () => {
    expect(getEmotionModePreference(7)).toBe('real')

    localStorage.setItem(userPreferenceKey(7, 'emotionMode'), 'unexpected')
    expect(getEmotionModePreference(7)).toBe('real')
  })

  test('uses real when no user is active', () => {
    expect(getEmotionModePreference(undefined)).toBe('real')
  })
})

describe('draw style preferences', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  test('keeps a stored four-style value', () => {
    setUserPreference(7, 'drawStyle', 'sketch')

    expect(getDrawStylePreference(7)).toBe('sketch')
  })

  test('retires old ghibli preferences to the default style', () => {
    localStorage.setItem(userPreferenceKey(7, 'drawStyle'), 'ghibli')

    expect(getDrawStylePreference(7)).toBe(DEFAULT_DRAW_STYLE)
  })

  test('uses the default when no user is active', () => {
    expect(getDrawStylePreference(undefined)).toBe(DEFAULT_DRAW_STYLE)
  })
})
