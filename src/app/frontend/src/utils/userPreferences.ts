export type UserPreferenceName =
  | 'emotionMode'
  | 'drawStyle'
  | 'reminderTime'
  | 'lastReminderDate'
  | 'customEmotion'
  | 'customDraw'

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

export function setUserPreference(
  userId: number | undefined,
  name: UserPreferenceName,
  value: string,
): void {
  if (userId === undefined) return
  localStorage.setItem(userPreferenceKey(userId, name), value)
}
