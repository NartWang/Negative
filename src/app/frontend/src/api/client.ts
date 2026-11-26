import type {
  AuthProfile, Diary, DiaryImage, DiaryNotebookIndex, DualTimelineComic, DualTimelinePayload,
  CharacterProfile, CompletedPicturebook, DiarySourceSelection, Fragment,
  FragmentCreatePayload, FragmentUpdatePayload, Invite, Profile,
  EmotionMode, PicturebookJob, PicturebookVideoJob, PicturebookVideoSource,
  RewriteDirection, Room, RoomComment, RoomFeed,
  RoomLikeResult, RoomPost, RoomTemperatures, RoomTemperatureSnapshot,
  Schedule, Stats, StoryDayDetail, StoryWork, StreakInfo, Subscription,
  Thermometer, TimelineEvent, UploadOptions, UploadResult, WeeklyComic, WorkAudience,
  StoryChapter, CreateStoryDraftRequest, StoryDraftList, StoryWorkDetail,
  UpdateStoryWorkRequest, UpdateStoryWorkSourcesRequest,
  PublicationResult, ResonanceFeedPage, PublishedStoryDetail, CollectionsPage,
  CollectionDetailPage, WorkComment, InteractionSummary,
  DayExportAvailability, FilmFolderMotionComicDetail, FilmFolderPicturebookDetail,
  FilmFolderResponse, MotionComicDraft, UnfinishedMotionComic, UnfinishedPicturebook,
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
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail: unknown = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface GenerationSlotConflictDetail {
  detail: string
  category: string
  active_job_id: number
}

function isSlotConflictDetail(
  detail: unknown,
  category: string,
): detail is GenerationSlotConflictDetail {
  if (typeof detail !== 'object' || detail === null) return false
  const candidate = detail as Record<string, unknown>
  return (
    candidate.category === category
    && typeof candidate.active_job_id === 'number'
  )
}

/**
 * 结构化 409:同一分区已有任务在跑。只有 category 与 active_job_id
 * 同时命中才视为槽位冲突,其他 409(如来源不可用)一律不算。
 */
export function isGenerationSlotConflict(
  error: unknown,
  category: 'picturebook' | 'motion_comic',
): boolean {
  return (
    error instanceof ApiError
    && error.status === 409
    && isSlotConflictDetail(error.detail, category)
  )
}

/** 返回当前占用生成槽位的任务 id，普通错误则返回 null。 */
export function generationSlotConflictJobId(
  error: unknown,
  category: 'picturebook' | 'motion_comic',
): number | null {
  if (!isGenerationSlotConflict(error, category)) return null
  return (error as ApiError).detail
    ? ((error as ApiError).detail as GenerationSlotConflictDetail).active_job_id
    : null
}

async function responseError(res: Response, url: string): Promise<ApiError> {
  const text = await res.text()
  let message = text
  let detail: unknown = null
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed.detail === 'string') {
      message = parsed.detail
      detail = parsed.detail
    } else if (typeof parsed.detail === 'object' && parsed.detail !== null) {
      // 结构化 detail(如分区槽位冲突):人读文案只取内层字符串。
      detail = parsed.detail
      const nested = (parsed.detail as Record<string, unknown>).detail
      message = typeof nested === 'string' ? nested : text
    }
  } catch {
    // A non-JSON upstream error still gets a stable HTTP status.
  }
  if (res.status === 401) notifyUnauthorized(url)
  return new ApiError(res.status, message || `请求失败（${res.status}）`, detail)
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
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers,
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
  create: (data: FragmentCreatePayload) =>
    request<Fragment>('/fragments', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  list: (date: string) => {
    const qs = new URLSearchParams({ date })
    return request<Fragment[]>(`/fragments?${qs}`)
  },
  update: (id: number, data: FragmentUpdatePayload) =>
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
  aiFill: (id: number, data: {
    emotion_mode: EmotionMode
  } & Partial<DiarySourceSelection>) =>
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
  delete: (id: number) =>
    request<void>(`/diary/${id}`, { method: 'DELETE' }),
  notebookIndex: () => request<DiaryNotebookIndex>('/diary/notebook/index'),
  notebookDetail: (id: number) => request<Diary>(`/diary/notebook/${id}`),
}

export const imageApi = {
  batchGenerate: (diaryId: number, data: { style: string; custom_style_prompt?: string; paragraphs: string[] }) =>
    request<{ candidates: DiaryImage[] }>(
      `/image/diary/${diaryId}/images/batch`, { method: 'POST', body: JSON.stringify(data) },
    ),
  keep: (diaryId: number, keepIds: number[]) =>
    request<{ images: DiaryImage[] }>(
      `/image/diary/${diaryId}/images`, { method: 'PUT', body: JSON.stringify({ keep_ids: keepIds }) },
    ),
}

export const uploadApi = {
  upload: async (file: File, options: UploadOptions = {}): Promise<UploadResult> => {
    const formData = new FormData()
    formData.append('file', file)
    const suffix = options.describe ? '?describe=true' : ''
    return request<UploadResult>(`/upload${suffix}`, { method: 'POST', body: formData })
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
  downloadDayPdf: (date: string) =>
    requestBlob(`/export/day/${encodeURIComponent(date)}/pdf`, { method: 'POST' }),
  dayAvailability: (date: string) =>
    request<DayExportAvailability>(
      `/export/day/${encodeURIComponent(date)}/availability`,
    ),
  downloadSelectedDayPdf: (
    date: string,
    selection: { include_diary: boolean; include_picturebooks: boolean },
  ) =>
    requestBlob(`/export/day/${encodeURIComponent(date)}/pdf`, {
      method: 'POST',
      body: JSON.stringify(selection),
    }),
  downloadTimeStoryPdf: (workId: number) =>
    requestBlob(`/export/time-story/${workId}/pdf`, { method: 'POST' }),
  downloadPicturebookPdf: (
    sourceKind: 'canonical_work' | 'historical_job',
    sourceId: number,
  ) => requestBlob(`/export/picturebook/${sourceKind}/${sourceId}/pdf`, { method: 'POST' }),
  downloadMotionComic: (videoJobId: number) =>
    requestBlob(`/picturebook-video/${videoJobId}/file`),
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

export const picturebookApi = {
  /** Start or resume the picturebook for a diary; returns immediately. */
  start: (diaryId: number, style: string) =>
    request<PicturebookJob>(`/picturebook/diary/${diaryId}`, {
      method: 'POST',
      body: JSON.stringify({ style }),
    }),
  get: (jobId: number) => request<PicturebookJob>(`/picturebook/${jobId}`),
  latest: (diaryId: number, style?: string) =>
    request<PicturebookJob | null>(
      `/picturebook/diary/${diaryId}/latest${style ? `?style=${style}` : ''}`
    ),
  /** Re-render only the pages that failed; the written story is reused. */
  retry: (jobId: number) =>
    request<PicturebookJob>(`/picturebook/${jobId}/retry`, { method: 'POST' }),
}

const videoSourcePath = (source: PicturebookVideoSource) =>
  `/picturebook-video/${source.kind === 'work' ? 'work' : 'picturebook'}/${source.id}`

export const picturebookVideoApi = {
  /**
   * Chain a finished picturebook into one continuous film.
   * Pages are paired (k, k+1), so all N-1 segments render in parallel and the
   * whole film takes about as long as a single segment.
   *
   * `page_indexes` lets the wizard pick a subset and reorder it; the segments
   * follow that exact order.
   */
  start: (
    source: PicturebookVideoSource,
    options: {
      include_cover?: boolean
      segment_duration?: number
      ratio?: string
      page_indexes?: number[]
      draft_id?: number
    } = {},
  ) => {
    const body: Record<string, unknown> = { ...options }
    if (options.draft_id === undefined) delete body.draft_id
    return request<PicturebookVideoJob>(videoSourcePath(source), {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  get: (videoJobId: number) =>
    request<PicturebookVideoJob>(`/picturebook-video/${videoJobId}`),
  latest: (source: PicturebookVideoSource) =>
    request<PicturebookVideoJob | null>(`${videoSourcePath(source)}/latest`),
  /** Re-render only the segments that failed; finished ones are reused. */
  retry: (videoJobId: number) =>
    request<PicturebookVideoJob>(`/picturebook-video/${videoJobId}/retry`, {
      method: 'POST',
    }),
}

export const characterApi = {
  get: () => request<CharacterProfile>('/character-profile'),
  update: (data: {
    source_photo_url?: string | null
    reference_image_url?: string | null
    character_description?: string
    nickname?: string
    display_action?: string | null
    source_type?: string
  }) => request<CharacterProfile>('/character-profile', {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  /** Turn an authorized photo into a Q-version pixel character master. */
  generate: (data: {
    source_photo_asset_id?: string | null
    source_photo_url?: string | null
    character_description?: string
    nickname?: string
  }) => request<CharacterProfile>('/character-profile/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
}

export const storyApi = {
  chapters: () => request<{ items: StoryChapter[]; draft_count: number }>('/story/chapters'),
  day: (date: string) => request<StoryDayDetail>(`/story/days/${encodeURIComponent(date)}`),
  picturebooks: () => request<{ items: CompletedPicturebook[] }>('/story/picturebooks'),
  listWorks: () => request<StoryWork[]>('/story/works'),
  createWork: (data: {
    source_diary_id?: number | null
    source_fragment_ids?: number[]
    source_image_asset_ids?: string[]
    source_weekly_comic_ids?: number[]
    selected_segments: string[]
    medium: StoryWork['medium']
    narrative_mode: string
    style: string
    forbidden_content?: string
    title?: string
  }) => request<StoryWork>('/story/works', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  deleteWork: (id: number) => request<void>(`/story/works/${id}`, { method: 'DELETE' }),
  getAudience: (id: number) =>
    request<{ items: WorkAudience[] }>(`/story/works/${id}/audience`),
  replaceAudience: (id: number, subscriptionIds: number[]) =>
    request<{ items: WorkAudience[] }>(`/story/works/${id}/audience`, {
      method: 'PUT',
      body: JSON.stringify({ subscription_ids: subscriptionIds }),
    }),
  publish: (id: number, subscriptionIds: number[]) =>
    request<PublicationResult>(`/story/works/${id}/publication`, {
      method: 'PUT',
      body: JSON.stringify({ subscription_ids: subscriptionIds }),
    }),
  unpublish: (id: number) =>
    request<void>(`/story/works/${id}/publication`, { method: 'DELETE' }),
  resonanceFeed: (cursor?: string | null, pageSize?: number) => {
    const qs = new URLSearchParams()
    if (cursor) qs.set('cursor', cursor)
    if (pageSize) qs.set('page_size', String(pageSize))
    const suffix = qs.size ? `?${qs}` : ''
    return request<ResonanceFeedPage>(`/story/feed${suffix}`)
  },
  publishedWork: (id: number) =>
    request<PublishedStoryDetail>(`/story/published/${id}`),
  collections: (cursor?: string | null, pageSize?: number) => {
    const qs = new URLSearchParams()
    if (cursor) qs.set('cursor', cursor)
    if (pageSize) qs.set('page_size', String(pageSize))
    const suffix = qs.size ? `?${qs}` : ''
    return request<CollectionsPage>(`/story/collections${suffix}`)
  },
  collection: (
    ownerUserId: number,
    options: { order?: 'asc' | 'desc'; cursor?: string | null; pageSize?: number } = {},
  ) => {
    const qs = new URLSearchParams()
    if (options.order) qs.set('order', options.order)
    if (options.cursor) qs.set('cursor', options.cursor)
    if (options.pageSize) qs.set('page_size', String(options.pageSize))
    const suffix = qs.size ? `?${qs}` : ''
    return request<CollectionDetailPage>(`/story/collections/${ownerUserId}${suffix}`)
  },
  like: (id: number) =>
    request<{ liked: boolean }>(`/story/works/${id}/like`, { method: 'PUT' }),
  unlike: (id: number) =>
    request<{ liked: boolean }>(`/story/works/${id}/like`, { method: 'DELETE' }),
  comments: (id: number) =>
    request<{ items: WorkComment[] }>(`/story/works/${id}/comments`),
  addComment: (
    id: number,
    data: { client_request_id: string; body: string; viewer_user_id?: number | null },
  ) =>
    request<WorkComment>(`/story/works/${id}/comments`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  interactions: (pageSize?: number) => {
    const suffix = pageSize ? `?page_size=${pageSize}` : ''
    return request<InteractionSummary>(`/story/interactions${suffix}`)
  },
}

export const storyWorksApi = {
  createDraft: (data: CreateStoryDraftRequest) =>
    request<StoryWorkDetail>('/story/works/drafts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listDrafts: () => request<StoryDraftList>('/story/works/drafts'),
  get: (id: number) => request<StoryWorkDetail>(`/story/works/${id}`),
  update: (id: number, data: UpdateStoryWorkRequest) =>
    request<StoryWorkDetail>(`/story/works/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  updateSources: (id: number, data: UpdateStoryWorkSourcesRequest) =>
    request<StoryWorkDetail>(`/story/works/${id}/sources`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  duplicate: (id: number) =>
    request<StoryWorkDetail>(`/story/works/${id}/duplicate-draft`, { method: 'POST' }),
  generateStorylines: (id: number, data: { replace?: boolean } = {}) =>
    request<StoryWorkDetail>(`/story/works/${id}/storylines`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  generateNarrative: (id: number, data: { replace?: boolean } = {}) =>
    request<StoryWorkDetail>(`/story/works/${id}/narrative`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  confirmNarrative: (id: number) =>
    request<StoryWorkDetail>(`/story/works/${id}/confirm-narrative`, { method: 'POST' }),
  startPicturebook: (id: number, data: { replace?: boolean } = {}) =>
    request<PicturebookJob>(`/story/works/${id}/picturebook`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

export const subscriptionsApi = {
  following: () => request<Subscription[]>('/subscriptions/following'),
  audience: () => request<Subscription[]>('/subscriptions/audience'),
  createInvite: () => request<{ id: string; code: string; expires_at: string }>('/subscription-invites', {
    method: 'POST',
  }),
  joinInvite: (code: string) => request<Subscription>('/subscription-invites/join', {
    method: 'POST',
    body: JSON.stringify({ code }),
  }),
  remove: (id: number) =>
    request<void>(`/subscriptions/${id}`, { method: 'DELETE' }),
}

export const filmFolderApi = {
  picturebooks: () => request<FilmFolderResponse>('/film-folder/picturebooks'),
  motionComics: () => request<FilmFolderResponse>('/film-folder/motion-comics'),
  timeStories: () =>
    request<{ items: import('../types').FilmFolderItem[] }>('/film-folder/time-stories'),
  unfinishedPicturebooks: () =>
    request<{ items: UnfinishedPicturebook[] }>('/film-folder/picturebooks/unfinished'),
  unfinishedMotionComics: () =>
    request<{ items: UnfinishedMotionComic[] }>('/film-folder/motion-comics/unfinished'),
  picturebookDetail: (sourceKind: 'canonical_work' | 'historical_job', sourceId: number) =>
    request<FilmFolderPicturebookDetail>(
      `/film-folder/picturebooks/${sourceKind}/${sourceId}`,
    ),
  deletePicturebook: (sourceKind: 'canonical_work' | 'historical_job', sourceId: number) =>
    request<void>(`/film-folder/picturebooks/${sourceKind}/${sourceId}`, { method: 'DELETE' }),
  motionComicDetail: (videoJobId: number) =>
    request<FilmFolderMotionComicDetail>(`/film-folder/motion-comics/${videoJobId}`),
  createMotionDraft: (data: {
    source_kind: 'work' | 'job'
    source_id: number
    title?: string
    page_sequence: number[]
  }) =>
    request<MotionComicDraft>('/film-folder/motion-comics/drafts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getMotionDraft: (draftId: number) =>
    request<MotionComicDraft>(`/film-folder/motion-comics/drafts/${draftId}`),
  updateMotionDraft: (
    draftId: number,
    data: { title?: string; page_sequence?: number[] },
  ) =>
    request<MotionComicDraft>(`/film-folder/motion-comics/drafts/${draftId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteMotionDraft: (draftId: number) =>
    request<void>(`/film-folder/motion-comics/drafts/${draftId}`, { method: 'DELETE' }),
}
