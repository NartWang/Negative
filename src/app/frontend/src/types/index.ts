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
  photo_asset_id?: string | null
  photo_description: string | null
  mood_tag: string | null
  record_time: string | null
  created_at: string
}

export interface FragmentCreatePayload {
  date: string
  content?: string
  photo_url?: string | null
  photo_asset_id?: string | null
  photo_description?: string
  mood_tag?: string
  record_time?: string
}

export interface FragmentUpdatePayload {
  content?: string
  photo_url?: string | null
  photo_asset_id?: string | null
  photo_description?: string
  mood_tag?: string
  record_time?: string
}

export interface DiaryNotebookIndexEntry {
  diary_id: number
  date: string
}

export interface DiaryNotebookIndex {
  items: DiaryNotebookIndexEntry[]
  total: number
}

export interface DiaryImage {
  id: number
  diary_id: number
  style: string
  style_prompt: string | null
  url: string
  asset_id?: string | null
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

export type EmotionMode = 'real' | 'imagery'
/** The four picturebook styles, each backed by its own prompt pair. */
export type DrawStyle = 'crayon' | 'watercolor' | 'sketch' | 'pixel'
export type RewriteDirection = 'warmer' | 'humor' | 'concise' | 'poetic' | 'custom'

export type PicturebookStatus = 'running' | 'done' | 'failed'
export type PicturebookStage =
  | 'queued' | 'character' | 'story' | 'prompts' | 'rendering' | 'done' | 'failed'

export interface ReadablePicturebookPage {
  page_index: number
  image_url: string | null
  caption: string
  asset_id?: string | null
}

export interface PicturebookPage extends ReadablePicturebookPage {
  image_id: string
  status: 'pending' | 'rendering' | 'ready' | 'failed'
  error: string | null
}

export interface PicturebookJob {
  id: number
  diary_id: number | null
  work_id?: number | null
  style: DrawStyle
  status: PicturebookStatus
  stage: PicturebookStage
  stage_label: string
  error: string | null
  total_pages: number
  ready_pages: number
  created_at: string
  updated_at: string
  pages: PicturebookPage[]
}

export interface PicturebookJobSummary {
  id: number
  status: PicturebookStatus
  stage: PicturebookStage
  total_pages: number
  ready_pages: number
}

export type PicturebookVideoStatus = 'running' | 'done' | 'failed'
export type PicturebookVideoStage =
  | 'queued' | 'frames' | 'submitting' | 'rendering' | 'stitching' | 'done' | 'failed'

// ---------------------------------------------------------------------------
// 底片夹 film folder
// ---------------------------------------------------------------------------

export type FilmFolderMedium = 'picturebook' | 'motion_comic'
export type FilmFolderWorkKind = 'daily_picturebook' | 'time_story' | null

export interface FilmFolderItem {
  id: number
  source_kind: 'canonical_work' | 'historical_job' | 'video_job'
  work_kind: FilmFolderWorkKind
  style?: string | null
  stage?: string | null
  title: string
  display_start_date: string
  display_end_date: string
  cover_url: string | null
  completed_at: string
  published?: boolean
  /** motion comics only */
  video_url?: string
  /** demo seed: 底片示例作品,只读,不显示删除/发布按钮 */
  is_demo_seed?: boolean
  read_only?: boolean
}

export interface ActiveGeneration {
  id: number
  stage: string
  status: string
  total: number
  ready: number
  updated_at: string
}

export interface FilmFolderResponse {
  active_generation: ActiveGeneration | null
  unfinished_count: number
  items: FilmFolderItem[]
  /** 该分区当前用户剩余可新建次数(绘本 / 漫剧),0 表示已用完 */
  remaining?: number
}

export interface MotionComicDraft {
  id: number
  source_kind: 'work' | 'job'
  source_id: number
  title: string
  page_sequence: number[]
  video_job_id: number | null
  created_at: string
  updated_at: string
}

export interface UnfinishedPicturebook {
  /** canonical 作品项为 work_id;历史任务项为原任务 id。 */
  id: number
  /** 失败任务的显式标识;从未开始的作品为 null。 */
  job_id: number | null
  source_kind: 'canonical_work' | 'historical_job'
  work_kind: FilmFolderWorkKind
  style?: string | null
  stage?: string | null
  title: string
  display_start_date: string | null
  display_end_date: string | null
  error: string | null
  updated_at: string
}

export interface UnfinishedMotionComic {
  id: number
  source_kind: 'work' | 'job'
  source_id: number
  title: string
  video_job_id: number | null
  status: 'draft' | 'failed'
  style?: string | null
  display_start_date?: string | null
  display_end_date?: string | null
  error: string | null
  updated_at: string
}

export interface FilmFolderPicturebookDetail extends FilmFolderItem {
  pages: ReadablePicturebookPage[]
}

export interface FilmFolderMotionComicDetail {
  id: number
  title: string
  display_start_date: string | null
  display_end_date: string | null
  cover_url: string | null
  completed_at: string
  duration_seconds: number | null
  video_url: string
}

export interface DayExportAvailability {
  has_diary: boolean
  has_picturebooks: boolean
}

/**
 * A film can be keyed by the picturebook job itself or by the story work that
 * owns it, mirroring `CompletedPicturebook.source_kind`.
 */
export type PicturebookVideoSourceKind = 'job' | 'work'

export interface PicturebookVideoSource {
  kind: PicturebookVideoSourceKind
  id: number
}

/**
 * One shot between two adjacent pages: page k is its first frame, page k+1 its
 * last frame. N pages therefore yield N-1 segments, and every segment is boxed
 * in by artwork that already exists.
 */
export interface PicturebookVideoSegment {
  segment_index: number
  first_page_index: number
  last_page_index: number
  status: 'pending' | 'rendering' | 'ready' | 'failed' | 'timeout'
  error: string | null
}

export interface PicturebookVideoJob {
  id: number
  picturebook_job_id: number
  work_id: number | null
  style: DrawStyle
  status: PicturebookVideoStatus
  stage: PicturebookVideoStage
  stage_label: string
  error: string | null
  include_cover: boolean
  segment_duration: number
  ratio: string
  total_segments: number
  ready_segments: number
  duration_seconds: number | null
  /** Served by the backend behind the session cookie; null until finished. */
  video_url: string | null
  created_at: string
  updated_at: string
  segments: PicturebookVideoSegment[]
}

export interface UploadResult {
  url: string
  asset_id: string
  photo_description: string | null
}

export interface UploadOptions {
  describe?: boolean
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
  asset_id?: string | null
  caption: string | null
  created_at: string
}

export type CharacterSourceType = '' | 'preset' | 'photo_generated'

export interface CharacterProfile {
  user_id: number
  source_photo_url: string | null
  reference_image_url: string | null
  character_description: string
  nickname: string
  display_action: string | null
  source_type: CharacterSourceType
  version: number
  created_at: string | null
  updated_at: string | null
}

export interface StoryWorkAsset {
  id: number
  work_id?: number
  ordinal?: number
  asset_type: 'text' | 'image' | 'video'
  url: string | null
  asset_id?: string | null
  text: string | null
  prompt?: string | null
  created_at?: string
}

export interface StoryWork {
  id: number
  owner_user_id: number
  source_diary_id: number | null
  date?: string
  title: string
  medium: 'picture_book' | 'comic' | 'motion_comic' | 'weekly'
  narrative_mode: string
  style: string
  selected_segments: string[]
  forbidden_content: string | null
  render_prompt?: string | null
  status: 'draft' | 'ready' | 'published' | 'failed'
  assets: StoryWorkAsset[]
  created_at: string
  updated_at: string
}

export type StoryWorkKind = 'daily_picturebook' | 'time_story'
export type StoryWorkStatus = 'draft' | 'ready' | 'published' | 'failed'
export type StoryWorkflowStage =
  | 'sources_selected'
  | 'storylines_ready'
  | 'narrative_editing'
  | 'narrative_confirmed'
  | 'rendering'
  | 'render_failed'
  | 'ready'

export interface StorylineCandidate {
  id: string
  title: string
  summary: string
  tone?: string | null
  source_dates?: string[]
}

export interface StoryWorkDiarySource {
  id: number
  date: string
  status: Diary['status']
  text: string
}

export interface StoryWorkDetail {
  id: number
  owner_user_id: number
  kind: StoryWorkKind
  status: StoryWorkStatus
  stage: StoryWorkflowStage
  title: string
  style: DrawStyle
  selected_segments: string[]
  source_diary_ids: number[]
  source_diaries: StoryWorkDiarySource[]
  source_snapshot: {
    diaries: Array<{
      id: number
      date: string
      status: Diary['status']
      body: string
    }>
  }
  source_snapshot_hash: string
  source_start_date: string | null
  source_end_date: string | null
  display_start_date: string | null
  display_end_date: string | null
  storyline_candidates?: StorylineCandidate[]
  selected_storyline?: StorylineCandidate | null
  selected_storyline_id?: string | null
  narrative_text?: string
  generation_error: string | null
  active_picturebook_job: PicturebookJobSummary | null
  picturebook_job: PicturebookJobSummary | null
  pages: PicturebookPage[]
  created_at: string
  updated_at: string
}

export interface StoryDraftList {
  items: StoryWorkDetail[]
}

export interface CreateStoryDraftRequest {
  kind: StoryWorkKind
  source_diary_ids: number[]
  selected_segments?: string[]
  style?: DrawStyle
  title?: string
  source_start_date?: string
  source_end_date?: string
}

export type UpdateStoryWorkRequest = Partial<
  Pick<StoryWorkDetail, 'title' | 'style' | 'selected_storyline_id' | 'narrative_text'>
>

export interface UpdateStoryWorkSourcesRequest {
  source_diary_ids: number[]
  selected_segments: string[]
}

export type StoryChapterSourceKind = 'time_story' | 'legacy_weekly'

type StoryChapterBase = {
  start_date: string
  end_date: string
  title: string
  summary: string
  cover_url: string | null
  content_types: ReadonlyArray<'photo' | 'text' | 'diary' | 'picturebook' | 'story'>
}

export type StoryChapter =
  | (StoryChapterBase & {
    kind: 'day'
    date: string
  })
  | (StoryChapterBase & {
    kind: 'range_work'
    source_kind: StoryChapterSourceKind
    source_id: number
  })

export type StoryDayTimelineSchedule = {
  kind: 'schedule'
  id: number
  clock: string
  date: string
  title: string
  completed: boolean
  feeling: string | null
}

export type StoryDayTimelineFragment = {
  kind: 'fragment'
  id: number
  clock: string
  date: string
  content: string | null
  photo_url: string | null
  photo_asset_id?: string | null
  photo_description: string | null
  mood_tag: string | null
  created_at: string
}

export type StoryDayTimelineEntry = StoryDayTimelineSchedule | StoryDayTimelineFragment

export interface CompletedPicturebook {
  source_kind: 'canonical_work' | 'historical_job'
  source_id: number
  title: string
  source_start_date: string
  source_end_date: string
  start_date: string
  end_date: string
  date: string
  style: string
  cover_url: string | null
  total_pages: number
  ready_pages?: number
  pages: ReadablePicturebookPage[]
  created_at?: string
  updated_at?: string
}

export type StoryDayDetail = StoryChapter & {
  kind: 'day'
  date: string
  timeline: StoryDayTimelineEntry[]
  schedules: Schedule[]
  fragments: Fragment[]
  diaries: Diary[]
  picturebooks: CompletedPicturebook[]
  story_works: StoryWork[]
  draft_count: number
}

export interface SubscriptionProfile {
  id: number
  nickname: string
  avatar_url: string | null
}

export interface Subscription {
  id: number
  owner_user_id: number
  subscriber_user_id: number
  status: 'active' | 'revoked'
  owner?: SubscriptionProfile
  subscriber?: SubscriptionProfile
  created_at: string
  revoked_at?: string | null
}

export interface WorkAudience {
  id: number
  subscription_id: number
  owner_user_id: number
  subscriber_user_id: number
  status: 'active' | 'revoked'
  selected: boolean
  created_at: string
  revoked_at?: string | null
  granted_at?: string | null
  audience_status?: 'active' | 'revoked' | null
  audience_revoked_at?: string | null
  subscriber: SubscriptionProfile
}

export interface InteractionProfile extends SubscriptionProfile {}

export interface WorkComment {
  id: string
  work_id: number
  viewer_user_id: number
  author_user_id: number
  author: InteractionProfile
  viewer: InteractionProfile
  body: string
  created_at: string
}

export interface PublishedStoryAsset {
  id: number
  ordinal: number
  asset_type: 'text' | 'image' | 'video'
  url: string | null
  asset_id: string | null
  text: string | null
}

export interface PublicationWorkState {
  id: number
  status: 'ready' | 'published'
  published_at: string | null
  unpublished_at: string | null
}

export interface PublicationResult {
  work: PublicationWorkState
  audience: { items: WorkAudience[] }
}

export interface StoryFeedBase {
  id: number
  title: string
  medium: StoryWork['medium']
  narrative_mode: string
  style: string
  published_at: string
  owner: SubscriptionProfile
  assets: PublishedStoryAsset[]
  mine: boolean
}

export type ResonanceFeedItem = StoryFeedBase &
  (
    | {
        mine: true
        audience_count: number
        likes: InteractionProfile[]
        comments: WorkComment[]
        liked_by_me?: never
      }
    | {
        mine: false
        audience_count?: never
        likes?: never
        liked_by_me: boolean
        comments: WorkComment[]
      }
  )

export interface ResonanceFeedPage {
  items: ResonanceFeedItem[]
  next_cursor: string | null
}

export interface CollectedStoryOwner {
  owner: SubscriptionProfile
  story_count: number
  latest_published_at: string
  latest_work: Pick<StoryFeedBase, 'id' | 'title' | 'style' | 'assets'> | null
}

export interface CollectionsPage {
  items: CollectedStoryOwner[]
  next_cursor: string | null
}

export interface CollectionDetailPage {
  owner: SubscriptionProfile
  items: ResonanceFeedItem[]
  next_cursor: string | null
}

export type PublishedStoryDetail = ResonanceFeedItem

export interface InteractionSummaryItem {
  kind: 'like' | 'comment'
  work_id: number
  work_title: string
  actor: InteractionProfile
  body: string | null
  created_at: string
}

export interface InteractionSummary {
  items: InteractionSummaryItem[]
}

export interface DiarySourceSelection {
  schedule_ids: number[]
  fragment_ids: number[]
}

export interface DiaryEditorRequest {
  date: string
  selection?: DiarySourceSelection
}

export type StoryViewRequest =
  | { kind: 'day'; date: string }
  | { kind: 'create_menu'; date?: string }
  | { kind: 'daily_picturebook'; date?: string; workId?: number }
  | { kind: 'time_story'; workId?: number }
  | { kind: 'motion_comic'; draftId?: number }
  | { kind: 'story_work'; workId: number; from?: 'resonance' }
  | { kind: 'legacy_weekly'; comicId: number }
  | { kind: 'story_drafts' }
  | { kind: 'unfinished'; medium: FilmFolderMedium }
  | {
    kind: 'film_picturebook'
    sourceKind: 'canonical_work' | 'historical_job'
    sourceId: number
  }
  | { kind: 'film_motion_comic'; videoJobId: number }
  | {
    kind: 'picturebook_reader'
    title: string
    pages: ReadablePicturebookPage[]
    returnDate?: string
    returnWorkId?: number
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
