import type {
  AuthProfile, Diary, DiaryImage, DualTimelineComic, DualTimelinePayload,
  Fragment, Invite, Profile, RewriteDirection, Room, RoomComment, RoomFeed,
  RoomLikeResult, RoomPost, RoomTemperatures, RoomTemperatureSnapshot,
  Schedule, Stats, StreakInfo, Thermometer, TimelineEvent, UploadResult, WeeklyComic,
} from '../types'

const BASE = '/api'
const UNAUTHENTICATED_PATHS = new Set(['/me', '/auth/me', '/auth/login', '/auth/register'])
const unauthorizedListeners = new Set<() => void>()

export function subscribeUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener)
  return () => unauthorizedListeners.delete(listener)
}

function notifyUnauthorized(url: string): void {
  const path = url.split('?', 1)[0]
  if (UNAUTHENTICATED_PATHS.has(path)) return
  for (const listener of [...unauthorizedListeners]) listener()
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function responseError(res: Response, url: string): Promise<ApiError> {
  const text = await res.text()
  let detail = text
  try {
    const parsed = JSON.parse(text)
    detail = typeof parsed.detail === 'string' ? parsed.detail : text
  } catch {
    // A non-JSON upstream error still gets a stable HTTP status.
  }
  if (res.status === 401) notifyUnauthorized(url)
  return new ApiError(res.status, detail || `请求失败（${res.status}）`)
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers,
    credentials: 'same-origin',
  })
  if (!res.ok) {
    throw await responseError(res, url)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

async function requestBlob(url: string, options: RequestInit = {}): Promise<Blob> {
  const res = await fetch(`${BASE}${url}`, {
    ...options,
    credentials: 'same-origin',
  })
  if (!res.ok) throw await responseError(res, url)
  return res.blob()
}

export const authApi = {
  me: () => request<AuthProfile>('/me'),
  register: (data: { username: string; password: string; nickname: string }) =>
    request<AuthProfile>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  login: (data: { username: string; password: string }) =>
    request<AuthProfile>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  logout: () => request<void>('/auth/session', { method: 'DELETE' }),
}

export const roomsApi = {
  current: (signal?: AbortSignal) => request<Room | null>('/rooms/current', { signal }),
  create: () => request<Room>('/rooms', { method: 'POST' }),
  createInvite: (roomId: string) =>
    request<Invite>(`/rooms/${roomId}/invites`, { method: 'POST' }),
  join: (code: string) => request<Room>('/room-invites/join', {
    method: 'POST',
    body: JSON.stringify({ code }),
  }),
  leave: (roomId: string) =>
    request<void>(`/rooms/${roomId}/leave`, { method: 'POST' }),
  feed: (roomId: string, cursor?: string) => {
    const qs = new URLSearchParams()
    if (cursor) qs.set('cursor', cursor)
    return request<RoomFeed>(`/rooms/${roomId}/feed${qs.size ? `?${qs}` : ''}`)
  },
  createNote: (roomId: string, body: string) =>
    request<RoomPost>(`/rooms/${roomId}/posts/notes`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    }),
  publishDiary: (roomId: string, diaryId: number, imageIds: number[]) =>
    request<RoomPost>(`/rooms/${roomId}/posts/diaries/${diaryId}`, {
      method: 'PUT',
      body: JSON.stringify({ image_ids: imageIds }),
    }),
  publishComic: (roomId: string, comicId: number) =>
    request<RoomPost>(`/rooms/${roomId}/posts/comics/${comicId}`, { method: 'PUT' }),
  withdrawPost: (roomId: string, postId: string) =>
    request<void>(`/rooms/${roomId}/posts/${postId}`, { method: 'DELETE' }),
  likePost: (roomId: string, postId: string) =>
    request<RoomLikeResult>(`/rooms/${roomId}/posts/${postId}/like`, { method: 'PUT' }),
  unlikePost: (roomId: string, postId: string) =>
    request<RoomLikeResult>(`/rooms/${roomId}/posts/${postId}/like`, { method: 'DELETE' }),
  createComment: (
    roomId: string,
    postId: string,
    data: { client_request_id: string; body: string },
  ) => request<RoomComment>(`/rooms/${roomId}/posts/${postId}/comments`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  temperatures: (roomId: string, date: string) => {
    const qs = new URLSearchParams({ date })
    return request<RoomTemperatures>(`/rooms/${roomId}/temperatures?${qs}`)
  },
  publishTemperature: (roomId: string, date: string) =>
    request<RoomTemperatureSnapshot>(`/rooms/${roomId}/temperatures/${date}`, { method: 'PUT' }),
  revokeTemperature: (roomId: string, date: string) =>
    request<void>(`/rooms/${roomId}/temperatures/${date}`, { method: 'DELETE' }),
}

export const schedulesApi = {
  create: (data: { date: string; time?: string; title: string; feeling?: string }) =>
    request<Schedule>('/schedules', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  list: (date: string) => {
    const qs = new URLSearchParams({ date })
    return request<Schedule[]>(`/schedules?${qs}`)
  },
  update: (id: number, data: { time?: string; title?: string; completed?: boolean; feeling?: string }) =>
    request<{ message: string }>(`/schedules/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) =>
    request<{ message: string }>(`/schedules/${id}`, { method: 'DELETE' }),
}

export const fragmentsApi = {
  create: (data: { date: string; content?: string; photo_url?: string; photo_description?: string; mood_tag?: string }) =>
    request<Fragment>('/fragments', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  list: (date: string) => {
    const qs = new URLSearchParams({ date })
    return request<Fragment[]>(`/fragments?${qs}`)
  },
  update: (id: number, data: { content?: string; photo_url?: string; photo_description?: string; mood_tag?: string }) =>
    request<Fragment>(`/fragments/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: number) =>
    request<{ message: string }>(`/fragments/${id}`, { method: 'DELETE' }),
}

export const streaksApi = {
  get: () => request<StreakInfo>('/streaks'),
}

export const diaryApi = {
  createBlank: (date: string) =>
    request<Diary>('/diary', {
      method: 'POST',
      body: JSON.stringify({ date }),
    }),
  aiFill: (id: number, data: { emotion_mode: string; custom_emotion_prompt?: string }) =>
    request<Diary>(`/diary/${id}/ai-fill`, { method: 'POST', body: JSON.stringify(data) }),
  aiRewrite: (id: number, data: { paragraph: string; direction: RewriteDirection; custom_prompt?: string }) =>
    request<{ original: string; rewritten: string; direction: string }>(
      `/diary/${id}/ai-rewrite`, { method: 'POST', body: JSON.stringify(data) },
    ),
  get: (date: string) => {
    const qs = new URLSearchParams({ date })
    return request<Diary | null>(`/diary?${qs}`)
  },
  list: (params: { status?: 'draft' | 'confirmed' | 'all'; page?: number } = {}) => {
    const qs = new URLSearchParams()
    if (params.status) qs.set('status', params.status)
    if (params.page) qs.set('page', String(params.page))
    const suffix = qs.size ? `?${qs}` : ''
    return request<Diary[]>(`/diary/list${suffix}`)
  },
  update: (id: number, data: { text?: string; draft_text?: string; status?: 'draft' | 'confirmed'; source?: string }) =>
    request<Diary>(`/diary/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
}

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

export const uploadApi = {
  upload: async (file: File): Promise<UploadResult> => {
    const formData = new FormData()
    formData.append('file', file)
    return request<UploadResult>('/upload', { method: 'POST', body: formData })
  },
}

export const profileApi = {
  get: () => request<Profile>('/profile'),
  update: (data: Partial<Pick<Profile, 'nickname' | 'avatar_url' | 'signature'>>) =>
    request<Profile>('/profile', { method: 'PUT', body: JSON.stringify(data) }),
}

export const statsApi = {
  get: () => request<Stats>('/stats'),
}

export const exportApi = {
  downloadPdf: () => requestBlob('/export/pdf', { method: 'POST' }),
}

export const thermometerApi = {
  get: (date: string) => {
    const qs = new URLSearchParams({ date })
    return request<Thermometer>(`/thermometer?${qs}`)
  },
}

export const weeklyComicApi = {
  generate: (data: {
    week_start: string
    week_end: string
    style: string
    custom_style_prompt?: string
  }) => request<WeeklyComic>('/weekly-comic/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  list: () => request<WeeklyComic[]>('/weekly-comic/list'),
  delete: (id: number) =>
    request<{ message: string }>(`/weekly-comic/${id}`, { method: 'DELETE' }),
}

export const dualTimelineApi = {
  get: (date: string) => {
    const qs = new URLSearchParams({ date })
    return request<DualTimelinePayload>(`/dual-timeline?${qs}`)
  },
  generate: (data: {
    date: string
    selected_a: TimelineEvent[]
    selected_b: TimelineEvent[]
    style: string
    custom_style_prompt?: string
  }) => request<DualTimelineComic>('/dual-timeline/comic/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  list: () => request<DualTimelineComic[]>('/dual-timeline/comic/list'),
  delete: (id: number) =>
    request<{ message: string }>(`/dual-timeline/comic/${id}`, { method: 'DELETE' }),
}

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
