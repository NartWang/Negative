import type {
  Schedule, Fragment, Diary, DiaryImage, StreakInfo,
  Profile, Stats, GenerateRequest, UploadResult, RewriteDirection,
  WeeklyComic, Thermometer,
  TimelineEvent, DualTimelinePayload, DualTimelineComic,
} from '../types'
import { getActiveUserId } from '../contexts/UserContext'

// 开发环境通过 Vite 代理访问本地后端，生产环境直接访问后端地址
const API_HOST = import.meta.env.PROD
  ? (import.meta.env.VITE_API_HOST || 'http://47.110.85.59:8000')
  : ''
const BASE = `${API_HOST}/api`

function withUser(qs: URLSearchParams = new URLSearchParams()): URLSearchParams {
  qs.set('user_id', String(getActiveUserId()))
  return qs
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    let detail = text
    try { detail = JSON.parse(text).detail ?? text } catch {}
    throw new Error(detail || `${res.status}`)
  }
  if (res.status === 204) return undefined as unknown as T
  return res.json()
}

// Users
export const usersApi = {
  list: () => request<{ id: number; nickname: string; avatar_url: string | null; signature: string; created_at: string }[]>('/users'),
}

// Schedules
export const schedulesApi = {
  create: (data: { date: string; time?: string; title: string; feeling?: string }) =>
    request<Schedule>('/schedules', {
      method: 'POST',
      body: JSON.stringify({ ...data, user_id: getActiveUserId() }),
    }),
  list: (date: string) => {
    const qs = withUser(); qs.set('date', date)
    return request<Schedule[]>(`/schedules?${qs}`)
  },
  update: (id: number, data: { time?: string; title?: string; completed?: boolean; feeling?: string }) =>
    request<{ message: string }>(`/schedules/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) =>
    request<{ message: string }>(`/schedules/${id}`, { method: 'DELETE' }),
}

// Fragments
export const fragmentsApi = {
  create: (data: { date: string; content?: string; photo_url?: string; photo_description?: string; mood_tag?: string }) =>
    request<Fragment>('/fragments', {
      method: 'POST',
      body: JSON.stringify({ ...data, user_id: getActiveUserId() }),
    }),
  list: (date: string) => {
    const qs = withUser(); qs.set('date', date)
    return request<Fragment[]>(`/fragments?${qs}`)
  },
  update: (id: number, data: { content?: string; photo_url?: string; photo_description?: string; mood_tag?: string }) =>
    request<Fragment>(`/fragments/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) =>
    request<{ message: string }>(`/fragments/${id}`, { method: 'DELETE' }),
}

// Streaks
export const streaksApi = {
  get: () => {
    const qs = withUser()
    return request<StreakInfo>(`/streaks?${qs}`)
  },
}

// Diary
export const diaryApi = {
  createBlank: (date: string) =>
    request<Diary>('/diary', {
      method: 'POST',
      body: JSON.stringify({ date, user_id: getActiveUserId() }),
    }),
  generate: (data: GenerateRequest) =>
    request<Diary>('/diary/generate', {
      method: 'POST',
      body: JSON.stringify({ ...data, user_id: getActiveUserId() }),
    }),
  aiFill: (id: number, data: { emotion_mode: string; custom_emotion_prompt?: string }) =>
    request<Diary>(`/diary/${id}/ai-fill`, { method: 'POST', body: JSON.stringify(data) }),
  aiRewrite: (id: number, data: { paragraph: string; direction: RewriteDirection; custom_prompt?: string }) =>
    request<{ original: string; rewritten: string; direction: string }>(
      `/diary/${id}/ai-rewrite`, { method: 'POST', body: JSON.stringify(data) },
    ),
  get: (date: string) => {
    const qs = withUser(); qs.set('date', date)
    return request<Diary | null>(`/diary?${qs}`)
  },
  list: (params: { status?: 'draft' | 'confirmed' | 'all'; page?: number } = {}) => {
    const qs = withUser()
    if (params.status) qs.set('status', params.status)
    if (params.page) qs.set('page', String(params.page))
    return request<Diary[]>(`/diary/list?${qs}`)
  },
  update: (id: number, data: { text?: string; draft_text?: string; status?: 'draft' | 'confirmed'; source?: string }) =>
    request<Diary>(`/diary/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
}

// Image
export const imageApi = {
  batchGenerate: (diaryId: number, data: { style: string; custom_style_prompt?: string; paragraphs: string[]; n: number }) =>
    request<{ candidates: DiaryImage[] }>(
      `/image/diary/${diaryId}/images/batch`, { method: 'POST', body: JSON.stringify(data) },
    ),
  keep: (diaryId: number, keepIds: number[]) =>
    request<{ images: DiaryImage[] }>(
      `/image/diary/${diaryId}/images`, { method: 'PUT', body: JSON.stringify({ keep_ids: keepIds }) },
    ),
}

// Upload
export const uploadApi = {
  upload: async (file: File): Promise<UploadResult> => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/upload`, { method: 'POST', body: formData })
    if (!res.ok) throw new Error('Upload failed')
    return res.json()
  },
}

// Profile
export const profileApi = {
  get: () => {
    const qs = withUser()
    return request<Profile>(`/profile?${qs}`)
  },
  update: (data: Partial<Pick<Profile, 'nickname' | 'avatar_url' | 'signature'>>) => {
    const qs = withUser()
    return request<Profile>(`/profile?${qs}`, { method: 'PUT', body: JSON.stringify(data) })
  },
}

// Stats
export const statsApi = {
  get: () => {
    const qs = withUser()
    return request<Stats>(`/stats?${qs}`)
  },
}

// Export
export const exportApi = {
  pdfUrl: () => `/api/export/pdf?user_id=${getActiveUserId()}`,
}

// Thermometer
export const thermometerApi = {
  get: (date: string) => {
    const qs = withUser(); qs.set('date', date)
    return request<Thermometer>(`/thermometer?${qs}`)
  },
}

// Weekly Comic
export const weeklyComicApi = {
  generate: (data: {
    week_start: string
    week_end: string
    style: string
    custom_style_prompt?: string
  }) =>
    request<WeeklyComic>('/weekly-comic/generate', {
      method: 'POST',
      body: JSON.stringify({ ...data, user_id: getActiveUserId() }),
    }),
  list: () => {
    const qs = withUser()
    return request<WeeklyComic[]>(`/weekly-comic/list?${qs}`)
  },
  delete: (id: number) =>
    request<{ message: string }>(`/weekly-comic/${id}`, { method: 'DELETE' }),
}

// Dual Timeline
const FAMILY_USER_ID = 2

export const dualTimelineApi = {
  get: (date: string, userA?: number) => {
    const qs = new URLSearchParams()
    qs.set('date', date)
    qs.set('user_a', String(userA ?? getActiveUserId()))
    qs.set('user_b', String(FAMILY_USER_ID))
    return request<DualTimelinePayload>(`/dual-timeline?${qs}`)
  },
  generate: (data: {
    date: string
    selected_a: TimelineEvent[]
    selected_b: TimelineEvent[]
    style: string
    custom_style_prompt?: string
  }) =>
    request<DualTimelineComic>('/dual-timeline/comic/generate', {
      method: 'POST',
      body: JSON.stringify({
        ...data,
        user_a: getActiveUserId(),
        user_b: FAMILY_USER_ID,
      }),
    }),
  list: () => {
    const qs = withUser()
    return request<DualTimelineComic[]>(`/dual-timeline/comic/list?${qs}`)
  },
  delete: (id: number) =>
    request<{ message: string }>(`/dual-timeline/comic/${id}`, { method: 'DELETE' }),
}

// Letter (DingTalk webhook) — 保留兼容
export type LetterType = 'diary' | 'comic' | 'test'

export const letterApi = {
  send: (data: {
    webhook: string
    type: LetterType
    id?: number
    title: string
    body: string
  }) =>
    request<{ ok: boolean; sent_at: string }>('/letter/send', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

// Share (v3.7) — 分享链接
export interface ShareInfo {
  share_code: string
  share_url: string
}

export const shareApi = {
  create: (data: { type: string; id: number; user_id?: number }) =>
    request<ShareInfo>('/share/create', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  unseenReactions: (user_id?: number) => {
    const qs = new URLSearchParams()
    if (user_id) qs.set('user_id', String(user_id))
    else qs.set('user_id', String(getActiveUserId()))
    return request<{ unseen_count: number }>(`/share/reactions/unseen?${qs}`)
  },
  markSeen: (user_id?: number) => {
    const qs = new URLSearchParams()
    if (user_id) qs.set('user_id', String(user_id))
    else qs.set('user_id', String(getActiveUserId()))
    return request<{ ok: boolean }>('/share/reactions/mark-seen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: user_id ?? getActiveUserId() }),
    })
  },
}

// Email (v3.7)
export interface EmailConfig {
  configured: boolean
  from_name: string
  from_addr: string | null
}

export const emailApi = {
  send: (data: { to: string; subject: string; body: string; share_url?: string }) =>
    request<{ ok: boolean; message: string }>('/email/send', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  config: () => request<EmailConfig>('/email/config'),
}

// Nagging Transformer (v3.6)
export interface NaggingItem {
  id: number
  from: string
  received_at: string
  kind: string
  text: string
}

export interface NaggingCards {
  help_request: string
  co_challenge: string
  warm_echo: string
}

export const transformApi = {
  inbox: () => request<NaggingItem[]>('/transform/nagging/inbox'),
  transform: (data: { nag_id?: number; nag_text?: string; relation?: string }) =>
    request<{ nag_text: string; cards: NaggingCards }>('/transform/nagging/transform', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}
