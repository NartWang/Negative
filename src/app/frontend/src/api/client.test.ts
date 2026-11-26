import { beforeEach, describe, expect, test, vi } from 'vitest'
import {
  ApiError,
  diaryApi,
  fragmentsApi,
  isGenerationSlotConflict,
  storyApi,
  storyWorksApi,
  subscriptionsApi,
  uploadApi,
} from './client'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function pathWithSearch(input: RequestInfo | URL): string {
  const url = input instanceof Request
    ? new URL(input.url, window.location.origin)
    : new URL(String(input), window.location.origin)
  return `${url.pathname}${url.search}`
}

function methodOf(input: RequestInfo | URL, init?: RequestInit): string {
  if (input instanceof Request) return input.method.toUpperCase()
  return (init?.method ?? 'GET').toUpperCase()
}

function bodyOf(init?: RequestInit): unknown {
  return JSON.parse(String(init?.body ?? '{}'))
}

describe('personal space api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], next_cursor: null })))
  })

  test('sends selected diary source ids to ai fill', async () => {
    await diaryApi.aiFill(10, {
      emotion_mode: 'real',
      schedule_ids: [1, 2],
      fragment_ids: [3],
    })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/diary/10/ai-fill')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({
      emotion_mode: 'real',
      schedule_ids: [1, 2],
      fragment_ids: [3],
    })
  })

  test('requests photo description only when upload opts in', async () => {
    const file = new File(['image'], 'moment.png', { type: 'image/png' })

    await uploadApi.upload(file, { describe: true })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/upload?describe=true')
    expect(methodOf(input, init)).toBe('POST')
    expect(init?.body).toBeInstanceOf(FormData)
  })

  test('replaces a work audience with a complete subscription id set', async () => {
    await storyApi.replaceAudience(42, [7, 9])

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/story/works/42/audience')
    expect(methodOf(input, init)).toBe('PUT')
    expect(bodyOf(init)).toEqual({ subscription_ids: [7, 9] })
  })

  test('reads the resonance feed with page size', async () => {
    await storyApi.resonanceFeed('opaque-cursor', 30)

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/story/feed?cursor=opaque-cursor&page_size=30')
    expect(methodOf(input, init)).toBe('GET')
  })

  test('publishes, comments, and loads collections with exact contracts', async () => {
    await storyApi.publish(42, [7, 9])
    let [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/story/works/42/publication')
    expect(methodOf(input, init)).toBe('PUT')
    expect(bodyOf(init)).toEqual({ subscription_ids: [7, 9] })

    await storyApi.unpublish(42)
    ;[input, init] = vi.mocked(fetch).mock.calls[1]
    expect(pathWithSearch(input)).toBe('/api/story/works/42/publication')
    expect(methodOf(input, init)).toBe('DELETE')

    await storyApi.addComment(42, {
      client_request_id: 'c-1',
      body: '真好',
      viewer_user_id: 8,
    })
    ;[input, init] = vi.mocked(fetch).mock.calls[2]
    expect(pathWithSearch(input)).toBe('/api/story/works/42/comments')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({
      client_request_id: 'c-1',
      body: '真好',
      viewer_user_id: 8,
    })

    await storyApi.collection(8, { order: 'asc', cursor: 'next' })
    ;[input] = vi.mocked(fetch).mock.calls[3]
    expect(pathWithSearch(input)).toBe('/api/story/collections/8?order=asc&cursor=next')

    await storyApi.publishedWork(42)
    ;[input, init] = vi.mocked(fetch).mock.calls[4]
    expect(pathWithSearch(input)).toBe('/api/story/published/42')
    expect(methodOf(input, init)).toBe('GET')

    await storyApi.like(42)
    ;[input, init] = vi.mocked(fetch).mock.calls[5]
    expect(methodOf(input, init)).toBe('PUT')

    await storyApi.interactions(50)
    ;[input] = vi.mocked(fetch).mock.calls[6]
    expect(pathWithSearch(input)).toBe('/api/story/interactions?page_size=50')
  })

  test('removes a subscription relationship', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))

    await subscriptionsApi.remove(8)

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/subscriptions/8')
    expect(methodOf(input, init)).toBe('DELETE')
  })

  test('creates a daily picturebook draft with source diary ids', async () => {
    await storyWorksApi.createDraft({
      kind: 'daily_picturebook',
      source_diary_ids: [11],
      selected_segments: ['第一段。'],
      style: 'watercolor',
      title: '今天的绘本',
    })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/story/works/drafts')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({
      kind: 'daily_picturebook',
      source_diary_ids: [11],
      selected_segments: ['第一段。'],
      style: 'watercolor',
      title: '今天的绘本',
    })
  })

  test('updates daily picturebook sources with the workflow payload shape', async () => {
    await storyWorksApi.updateSources(42, {
      source_diary_ids: [12],
      selected_segments: ['换一段。'],
    })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/story/works/42/sources')
    expect(methodOf(input, init)).toBe('PUT')
    expect(bodyOf(init)).toEqual({
      source_diary_ids: [12],
      selected_segments: ['换一段。'],
    })
  })

  test('starts a work-backed picturebook without changing the route body by accident', async () => {
    await storyWorksApi.startPicturebook(42, { replace: true })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/story/works/42/picturebook')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({ replace: true })
  })

  test('creates a fragment passing record_time through verbatim', async () => {
    await fragmentsApi.create({
      date: '2026-08-09',
      content: '清晨的咖啡',
      record_time: '07:30',
    })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/fragments')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({
      date: '2026-08-09',
      content: '清晨的咖啡',
      record_time: '07:30',
    })
  })

  test('updates a fragment passing record_time and photo clearing fields verbatim', async () => {
    await fragmentsApi.update(5, {
      record_time: '21:45',
      photo_url: null,
      photo_asset_id: null,
    })

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/fragments/5')
    expect(methodOf(input, init)).toBe('PUT')
    expect(bodyOf(init)).toEqual({
      record_time: '21:45',
      photo_url: null,
      photo_asset_id: null,
    })
  })

  test('fetches the diary notebook index', async () => {
    await diaryApi.notebookIndex()

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/diary/notebook/index')
    expect(methodOf(input, init)).toBe('GET')
  })

  test('fetches a diary notebook detail by id', async () => {
    await diaryApi.notebookDetail(17)

    const [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/diary/notebook/17')
    expect(methodOf(input, init)).toBe('GET')
  })
})

describe('film folder api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [] })))
  })

  test('reads collections, unfinished lists, details and time stories', async () => {
    const { filmFolderApi } = await import('./client')

    await filmFolderApi.picturebooks()
    let [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/film-folder/picturebooks')
    expect(methodOf(input, init)).toBe('GET')

    await filmFolderApi.motionComics()
    ;[input] = vi.mocked(fetch).mock.calls[1]
    expect(pathWithSearch(input)).toBe('/api/film-folder/motion-comics')

    await filmFolderApi.unfinishedPicturebooks()
    ;[input] = vi.mocked(fetch).mock.calls[2]
    expect(pathWithSearch(input)).toBe('/api/film-folder/picturebooks/unfinished')

    await filmFolderApi.unfinishedMotionComics()
    ;[input] = vi.mocked(fetch).mock.calls[3]
    expect(pathWithSearch(input)).toBe('/api/film-folder/motion-comics/unfinished')

    await filmFolderApi.picturebookDetail('canonical_work', 42)
    ;[input] = vi.mocked(fetch).mock.calls[4]
    expect(pathWithSearch(input)).toBe('/api/film-folder/picturebooks/canonical_work/42')

    await filmFolderApi.motionComicDetail(501)
    ;[input] = vi.mocked(fetch).mock.calls[5]
    expect(pathWithSearch(input)).toBe('/api/film-folder/motion-comics/501')

    await filmFolderApi.timeStories()
    ;[input] = vi.mocked(fetch).mock.calls[6]
    expect(pathWithSearch(input)).toBe('/api/film-folder/time-stories')
  })

  test('creates, reads and updates motion drafts with exact bodies', async () => {
    const { filmFolderApi } = await import('./client')

    await filmFolderApi.createMotionDraft({
      source_kind: 'work',
      source_id: 42,
      title: '晚霞',
      page_sequence: [1, 2, 4, 3],
    })
    let [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/film-folder/motion-comics/drafts')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({
      source_kind: 'work',
      source_id: 42,
      title: '晚霞',
      page_sequence: [1, 2, 4, 3],
    })

    await filmFolderApi.getMotionDraft(7)
    ;[input, init] = vi.mocked(fetch).mock.calls[1]
    expect(pathWithSearch(input)).toBe('/api/film-folder/motion-comics/drafts/7')
    expect(methodOf(input, init)).toBe('GET')

    await filmFolderApi.updateMotionDraft(7, { page_sequence: [2, 1] })
    ;[input, init] = vi.mocked(fetch).mock.calls[2]
    expect(pathWithSearch(input)).toBe('/api/film-folder/motion-comics/drafts/7')
    expect(methodOf(input, init)).toBe('PUT')
    expect(bodyOf(init)).toEqual({ page_sequence: [2, 1] })
  })

  test('selected day pdf posts JSON and legacy posts no body', async () => {
    const { exportApi } = await import('./client')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = pathWithSearch(input)
      if (path.endsWith('/availability')) {
        return jsonResponse({ has_diary: true, has_picturebooks: false })
      }
      return new Response(new Blob(['pdf']))
    }))

    await exportApi.downloadSelectedDayPdf('2026-08-08', {
      include_diary: true,
      include_picturebooks: false,
    })
    let [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/export/day/2026-08-08/pdf')
    expect(methodOf(input, init)).toBe('POST')
    expect(bodyOf(init)).toEqual({ include_diary: true, include_picturebooks: false })
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')

    await exportApi.downloadDayPdf('2026-08-08')
    ;[input, init] = vi.mocked(fetch).mock.calls[1]
    expect(pathWithSearch(input)).toBe('/api/export/day/2026-08-08/pdf')
    expect(init?.body).toBeUndefined()

    await exportApi.downloadTimeStoryPdf(42)
    ;[input, init] = vi.mocked(fetch).mock.calls[2]
    expect(pathWithSearch(input)).toBe('/api/export/time-story/42/pdf')
    expect(methodOf(input, init)).toBe('POST')

    await exportApi.dayAvailability('2026-08-08')
    ;[input, init] = vi.mocked(fetch).mock.calls[3]
    expect(pathWithSearch(input)).toBe('/api/export/day/2026-08-08/availability')
    expect(methodOf(input, init)).toBe('GET')
  })

  test('video start includes draft_id only when supplied', async () => {
    const { picturebookVideoApi } = await import('./client')

    await picturebookVideoApi.start(
      { kind: 'work', id: 42 },
      { page_indexes: [1, 2, 3], draft_id: 7 },
    )
    let [input, init] = vi.mocked(fetch).mock.calls[0]
    expect(pathWithSearch(input)).toBe('/api/picturebook-video/work/42')
    expect(bodyOf(init)).toEqual({ page_indexes: [1, 2, 3], draft_id: 7 })

    await picturebookVideoApi.start({ kind: 'job', id: 9 }, { page_indexes: [1, 2] })
    ;[input, init] = vi.mocked(fetch).mock.calls[1]
    expect(pathWithSearch(input)).toBe('/api/picturebook-video/picturebook/9')
    expect(bodyOf(init)).toEqual({ page_indexes: [1, 2] })
  })
})

describe('ApiError structured detail', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('preserves nested generation-slot conflict detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(
      { detail: { detail: 'generation slot is occupied', category: 'picturebook', active_job_id: 77 } },
      409,
    )))
    const { diaryApi: api } = await import('./client')
    const error = await api.get('2026-08-08').catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).message).toBe('generation slot is occupied')
    expect((error as ApiError).detail).toEqual({
      detail: 'generation slot is occupied',
      category: 'picturebook',
      active_job_id: 77,
    })
    expect(isGenerationSlotConflict(error, 'picturebook')).toBe(true)
    expect(isGenerationSlotConflict(error, 'motion_comic')).toBe(false)
  })

  test('a plain string 409 detail is not a generation-slot conflict', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(
      { detail: 'diary source is unavailable' },
      409,
    )))
    const { diaryApi: api } = await import('./client')
    const error = await api.get('2026-08-08').catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('diary source is unavailable')
    expect(isGenerationSlotConflict(error, 'picturebook')).toBe(false)
  })

  test('non-ApiError and non-409 values are never slot conflicts', () => {
    expect(isGenerationSlotConflict(new Error('x'), 'picturebook')).toBe(false)
    expect(isGenerationSlotConflict(null, 'picturebook')).toBe(false)
    expect(isGenerationSlotConflict(new ApiError(500, 'x'), 'picturebook')).toBe(false)
    expect(isGenerationSlotConflict(
      new ApiError(409, 'x', { category: 'picturebook', active_job_id: '77' }),
      'picturebook',
    )).toBe(false)
  })
})
