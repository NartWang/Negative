import { useEffect, useMemo, useState } from 'react'
import { diaryApi, storyWorksApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import { ArrowLeft, BookOpen, PenLine } from '../../components/Icon'
import type { Diary, StoryWorkDetail, StoryWorkflowStage, StoryWorkKind } from '../../types'
import './style.css'

interface Props {
  onBack: () => void
  onOpenDiaryDraft: (date: string) => void
  onOpenStoryDraft: (workId: number, kind: StoryWorkKind) => void
}

const KIND_LABELS: Record<StoryWorkKind, string> = {
  daily_picturebook: '当日绘本',
  time_story: '时间故事',
}

const STAGE_LABELS: Record<StoryWorkflowStage, string> = {
  sources_selected: '已选日记',
  storylines_ready: '故事线已生成',
  narrative_editing: '叙事编辑中',
  narrative_confirmed: '叙事已确认',
  rendering: '生成中',
  render_failed: '渲染失败',
  ready: '已完成',
}

function diaryDraftBody(diary: Diary): string {
  return (diary.draft_text || diary.text || '').trim()
}

function formatDateRange(work: StoryWorkDetail): string {
  const start = work.display_start_date ?? work.source_start_date
  const end = work.display_end_date ?? work.source_end_date
  if (!start) return '未选择日期'
  if (!end || end === start) return start
  return `${start} - ${end}`
}

export default function StoryDrafts({ onBack, onOpenDiaryDraft, onOpenStoryDraft }: Props) {
  const toast = useToast()
  const [diaryDrafts, setDiaryDrafts] = useState<Diary[]>([])
  const [storyDrafts, setStoryDrafts] = useState<StoryWorkDetail[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      diaryApi.list({ status: 'draft' }),
      storyWorksApi.listDrafts(),
    ])
      .then(([diaries, works]) => {
        if (cancelled) return
        setDiaryDrafts(
          diaries
            .filter(item => item.status === 'draft' && diaryDraftBody(item))
            .sort((left, right) => right.date.localeCompare(left.date)),
        )
        setStoryDrafts(
          works.items
            .filter(item => item.status === 'draft')
            .sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
        )
      })
      .catch(() => {
        if (!cancelled) toast.error('草稿暂时加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [toast])

  const empty = useMemo(
    () => !loading && diaryDrafts.length === 0 && storyDrafts.length === 0,
    [diaryDrafts.length, loading, storyDrafts.length],
  )

  return (
    <main className="story-drafts-page">
      <header className="story-drafts-header">
        <button type="button" className="story-drafts-back" onClick={onBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div>
          <h1>草稿箱</h1>
          <p>{loading ? '正在整理草稿…' : `${diaryDrafts.length + storyDrafts.length} 个草稿`}</p>
        </div>
      </header>

      {loading ? (
        <div className="story-drafts-state" role="status">正在整理草稿…</div>
      ) : empty ? (
        <div className="story-drafts-state">还没有草稿</div>
      ) : (
        <div className="story-drafts-list">
          {diaryDrafts.length > 0 && (
            <section className="story-drafts-section" aria-labelledby="story-diary-drafts-title">
              <h2 id="story-diary-drafts-title">日记草稿</h2>
              <div className="story-drafts-items">
                {diaryDrafts.map(item => (
                  <button
                    key={item.id}
                    type="button"
                    className="story-draft-row"
                    onClick={() => onOpenDiaryDraft(item.date)}
                  >
                    <span className="story-draft-icon" aria-hidden="true"><PenLine /></span>
                    <span className="story-draft-main">
                      <strong>{item.date}</strong>
                      <span>{diaryDraftBody(item)}</span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {storyDrafts.length > 0 && (
            <section className="story-drafts-section" aria-labelledby="story-work-drafts-title">
              <h2 id="story-work-drafts-title">故事草稿</h2>
              <div className="story-drafts-items">
                {storyDrafts.map(item => (
                  <button
                    key={item.id}
                    type="button"
                    className="story-draft-row"
                    onClick={() => onOpenStoryDraft(item.id, item.kind)}
                  >
                    <span className="story-draft-icon" aria-hidden="true"><BookOpen /></span>
                    <span className="story-draft-main">
                      <strong>{item.title}</strong>
                      <span>{KIND_LABELS[item.kind]} · {STAGE_LABELS[item.stage]} · {formatDateRange(item)}</span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </main>
  )
}
