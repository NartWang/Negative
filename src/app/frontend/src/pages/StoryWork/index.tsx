import { useEffect, useMemo, useRef, useState } from 'react'
import { storyWorksApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import { ArrowLeft, Eye } from '../../components/Icon'
import PictureBookReader from '../../components/PictureBookReader'
import PublishSheet from '../../components/PublishSheet'
import PicturebookVideo from '../../components/PicturebookVideo'
import VisibilitySheet from '../../components/VisibilitySheet'
import type { StoryWork as StoryWorkSummary, StoryWorkDetail } from '../../types'
import './style.css'

interface Props {
  workId: number
  onBack: () => void
  onOpenDraft: (workId: number) => void
}

function formatDateRange(work: StoryWorkDetail): string {
  const start = work.display_start_date ?? work.source_start_date
  const end = work.display_end_date ?? work.source_end_date
  if (!start) return '未选择日期'
  if (!end || end === start) return start
  return `${start} - ${end}`
}

function workForVisibility(work: StoryWorkDetail): StoryWorkSummary {
  return {
    id: work.id,
    owner_user_id: work.owner_user_id,
    source_diary_id: null,
    title: work.title,
    medium: 'picture_book',
    narrative_mode: 'time_story',
    style: work.style,
    selected_segments: work.selected_segments,
    forbidden_content: null,
    status: work.status,
    assets: [],
    created_at: work.created_at,
    updated_at: work.updated_at,
  }
}

export default function StoryWork({ workId, onBack, onOpenDraft }: Props) {
  const toast = useToast()
  const [work, setWork] = useState<StoryWorkDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [duplicating, setDuplicating] = useState(false)
  const [visibilityOpen, setVisibilityOpen] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const visibilityTriggerRef = useRef<HTMLButtonElement | null>(null)
  const publishTriggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    storyWorksApi.get(workId)
      .then(result => {
        if (!cancelled) setWork(result)
      })
      .catch(() => {
        if (!cancelled) setError('故事暂时打不开')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [workId])

  const visibilityWork = useMemo(() => work ? workForVisibility(work) : null, [work])

  const duplicateDraft = async () => {
    if (!work || duplicating) return
    setDuplicating(true)
    setError(null)
    try {
      const draft = await storyWorksApi.duplicate(work.id)
      onOpenDraft(draft.id)
    } catch {
      setError('创建草稿失败')
    } finally {
      setDuplicating(false)
    }
  }

  const openVisibility = (trigger: HTMLButtonElement) => {
    visibilityTriggerRef.current = trigger
    setVisibilityOpen(true)
  }

  const closeVisibility = () => {
    setVisibilityOpen(false)
    window.setTimeout(() => visibilityTriggerRef.current?.focus(), 0)
  }

  const openPublish = (trigger: HTMLButtonElement) => {
    publishTriggerRef.current = trigger
    setPublishOpen(true)
  }

  const closePublish = () => {
    setPublishOpen(false)
    window.setTimeout(() => publishTriggerRef.current?.focus(), 0)
  }

  const handlePublished = (state: { status: 'ready' | 'published' }) => {
    setWork(current => (current ? { ...current, status: state.status } : current))
    toast.success('已发布到回响')
  }

  if (loading) {
    return (
      <main className="story-work-page">
        <button type="button" className="story-work-back" onClick={onBack} aria-label="返回故事列表">
          <ArrowLeft />
        </button>
        <div className="story-work-state" role="status">正在读取故事…</div>
      </main>
    )
  }

  if (error || !work) {
    return (
      <main className="story-work-page">
        <button type="button" className="story-work-back" onClick={onBack} aria-label="返回故事列表">
          <ArrowLeft />
        </button>
        <div className="story-work-state error" role="alert">
          <strong>{error ?? '故事不存在'}</strong>
          <button type="button" onClick={onBack}>回到故事列表</button>
        </div>
      </main>
    )
  }

  return (
    <main className="story-work-page">
      <header className="story-work-hero">
        <div className="story-work-topbar">
          <button type="button" className="story-work-back" onClick={onBack} aria-label="返回故事列表">
            <ArrowLeft />
          </button>
          {work.status === 'ready' && (
            <button
              type="button"
              className="story-work-publish"
              onClick={event => openPublish(event.currentTarget)}
            >
              发布到回响
            </button>
          )}
          {work.status === 'published' && (
            <button
              type="button"
              className="story-work-visibility"
              onClick={event => openVisibility(event.currentTarget)}
            >
              <Eye />
              已发布 · 可见范围
            </button>
          )}
        </div>
        <time dateTime={work.display_start_date ?? work.source_start_date ?? undefined}>
          {formatDateRange(work)}
        </time>
        <h1>{work.title}</h1>
        <button
          type="button"
          className="story-work-edit"
          onClick={duplicateDraft}
          disabled={duplicating}
        >
          {duplicating ? '创建草稿中' : '编辑并重新生成'}
        </button>
        {error && <p className="story-work-error" role="alert">{error}</p>}
      </header>

      <section className="story-work-section" aria-labelledby="story-work-narrative-title">
        <div className="story-work-section-heading">
          <p>NARRATIVE</p>
          <h2 id="story-work-narrative-title">长故事</h2>
        </div>
        <p className="story-work-narrative">{work.narrative_text || '还没有故事文本。'}</p>
      </section>

      <section className="story-work-section" aria-labelledby="story-work-book-title">
        <div className="story-work-section-heading">
          <p>PICTUREBOOK</p>
          <h2 id="story-work-book-title">绘本</h2>
        </div>
        <PictureBookReader pages={work.pages} title={work.title} />
      </section>

      {work.picturebook_job?.status === 'done' && (
        <section className="story-work-section" aria-labelledby="story-work-video-title">
          <div className="story-work-section-heading">
            <p>MOTION</p>
            <h2 id="story-work-video-title">动态绘本</h2>
          </div>
          <PicturebookVideo
            source={{ kind: 'job', id: work.picturebook_job.id }}
            title={work.title}
          />
        </section>
      )}

      <PublishSheet
        open={publishOpen}
        work={visibilityWork}
        onClose={closePublish}
        onPublished={handlePublished}
      />
      {work.status === 'published' && (
        <VisibilitySheet
          open={visibilityOpen}
          work={visibilityWork}
          onClose={closeVisibility}
          onSaved={() => toast.success('可见范围已保存')}
        />
      )}
    </main>
  )
}
