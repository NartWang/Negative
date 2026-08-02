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
  last_sent_at: string | null
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

export interface GenerateRequest {
  date: string
  emotion_mode: EmotionMode
  custom_emotion_prompt?: string
}

export interface UploadResult {
  url: string
  photo_description: string | null
}

export interface User {
  id: number
  nickname: string
  avatar_url: string | null
  signature: string
  created_at: string
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
  last_sent_at: string | null
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
  user_b: { id: number; nickname: string }
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
  last_sent_at?: string | null
}

export interface EmailConfig {
  configured: boolean
  from_name: string
  from_addr: string | null
}
