export interface Schedule {
  id: number
  date: string
  time: string | null
  title: string
  completed: boolean
  feeling: string | null
  created_at: string
}

export interface Fragment {
  id: number
  date: string
  content: string | null
  photo_url: string | null
  photo_description: string | null
  mood_tag: string | null
  created_at: string
}

export interface DiaryImage {
  id: number
  diary_id: number
  style: string
  style_prompt: string | null
  url: string
  created_at: string
  kept: number
}

export interface Diary {
  id: number
  date: string
  text: string
  draft_text: string | null
  emotion_mode: string | null
  status: 'draft' | 'confirmed'
  source: 'manual' | 'ai' | 'hybrid'
  images: DiaryImage[]
  created_at: string
  confirmed_at: string | null
}

export interface StreakInfo {
  current_streak: number
  calendar_data: Record<string, { has_schedule: boolean; has_fragment: boolean }>
}

export interface Profile {
  id: number
  nickname: string
  avatar_url: string | null
  signature: string
  created_at: string
}

export interface AuthProfile {
  id: number
  nickname: string
  avatar_url: string | null
  signature: string | null
  created_at: string
}

export interface RoomMember {
  id: number
  nickname: string
  avatar_url: string | null
  role: 'owner' | 'member'
  slot: 1 | 2
}

export interface Room {
  id: string
  status: 'active'
  state: 'waiting' | 'paired'
  waiting: boolean
  created_at: string
  members: RoomMember[]
  partner: RoomMember | null
}

export interface Invite {
  code: string
  expires_at: string
}

export interface RoomPostAuthor {
  nickname: string
  avatar_url: string | null
}

export interface RoomComment {
  id: string
  author: RoomPostAuthor
  body: string
  created_at: string
  mine: boolean
}

export interface RoomNoteSnapshot {
  type: 'note'
  body: string
}

export interface RoomDiarySnapshot {
  type: 'diary'
  date: string
  text: string
  emotion_mode: string | null
  images: Array<{ style: string; url: string }>
}

export interface RoomComicSnapshot {
  type: 'weekly_comic'
  week_start: string
  week_end: string
  style: string | null
  caption: string | null
  image_url: string
}

export type RoomPostSnapshot = RoomNoteSnapshot | RoomDiarySnapshot | RoomComicSnapshot

export interface RoomPost {
  id: string
  source_type: 'note' | 'diary' | 'weekly_comic'
  source_id?: number
  author: RoomPostAuthor
  mine: boolean
  snapshot: RoomPostSnapshot
  media_urls: string[]
  published_at: string
  like_count: number
  liked_by_me: boolean
  comment_count: number
  comments_truncated: boolean
  comments: RoomComment[]
}

export interface RoomFeed {
  items: RoomPost[]
  next_cursor: string | null
}

export interface RoomTemperatureSnapshot {
  date: string
  score: number
  label: string
  color: string
  nickname: string
}

export type RoomTemperatureSubject =
  | { status: 'unavailable'; snapshot?: never }
  | { status: 'available'; snapshot: RoomTemperatureSnapshot }

export interface RoomTemperatures {
  own: RoomTemperatureSubject
  partner: RoomTemperatureSubject
}

export interface RoomLikeResult {
  liked: boolean
  like_count: number
}

export interface Stats {
  diary_count: number
  fragment_count: number
  longest_streak: number
  month_checkins: number
  month_days: number
}

export type EmotionMode = 'real' | 'warm' | 'humor' | 'poetic' | 'custom'
export type DrawStyle = 'grid4' | 'comic' | 'watercolor' | 'pixel' | 'ghibli' | 'custom'
export type RewriteDirection = 'warmer' | 'humor' | 'concise' | 'poetic' | 'custom'

export interface UploadResult {
  url: string
  photo_description: string | null
}

export interface Thermometer {
  score: number
  label: '凉' | '温凉' | '温热' | '温暖' | '炽热' | string
  color: string
  comment: string
  quant_score: number
  ai_score: number
  inputs: {
    fragments_count: number
    schedules_total: number
    schedules_completed: number
    consecutive_days: number
  }
}

export interface WeeklyComic {
  id: number
  user_id: number
  week_start: string
  week_end: string
  style: string | null
  style_prompt: string | null
  prompt: string | null
  url: string
  caption: string | null
  created_at: string
}

export interface TimelineEvent {
  type: 'schedule' | 'fragment'
  id: number
  time: string
  // schedule:
  title?: string
  completed?: boolean
  feeling?: string | null
  // fragment:
  content?: string | null
  mood_tag?: string | null
  photo_description?: string | null
}

export interface DualTimelinePayload {
  date: string
  user_a: { id: number; nickname: string }
  user_b: { id: number; nickname: string } | null
  summary: string
  events_a: TimelineEvent[]
  events_b: TimelineEvent[]
}

export interface DualTimelineComic {
  id: number
  date: string
  user_a_id: number
  user_b_id: number
  selected_events_json: string | null
  style: string | null
  style_prompt: string | null
  prompt: string | null
  url: string
  caption: string | null
  created_at: string
}
