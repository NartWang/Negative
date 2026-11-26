import type { DrawStyle, EmotionMode } from '../types'

export type UserPreferenceName =
  | 'emotionMode'
  | 'drawStyle'
  | 'customDraw'

export const DEFAULT_DRAW_STYLE: DrawStyle = 'watercolor'

const DRAW_STYLES = new Set<DrawStyle>([
  'crayon',
  'watercolor',
  'sketch',
  'pixel',
])

export function userPreferenceKey(
  userId: number,
  name: UserPreferenceName,
): string {
  return `zhiji:user:${userId}:${name}`
}

export function getUserPreference(
  userId: number | undefined,
  name: UserPreferenceName,
): string | null {
  if (userId === undefined) return null
  return localStorage.getItem(userPreferenceKey(userId, name))
}

export function getDrawStylePreference(userId: number | undefined): DrawStyle {
  const value = getUserPreference(userId, 'drawStyle')
  return DRAW_STYLES.has(value as DrawStyle) ? (value as DrawStyle) : DEFAULT_DRAW_STYLE
}

export function getEmotionModePreference(userId: number | undefined): EmotionMode {
  const value = getUserPreference(userId, 'emotionMode')
  if (value === 'imagery') return 'imagery'
  if (value === 'warm' || value === 'humor' || value === 'poetic' || value === 'custom') {
    return 'imagery'
  }
  return 'real'
}

export function setUserPreference(
  userId: number | undefined,
  name: UserPreferenceName,
  value: string,
): void {
  if (userId === undefined) return
  localStorage.setItem(userPreferenceKey(userId, name), value)
}
