import { useEffect, useMemo, useRef, useState } from 'react'
import {
  diaryApi,
  generationSlotConflictJobId,
  picturebookApi,
  storyWorksApi,
} from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import PictureBook from '../PictureBook'
import StyleSelector from '../StyleSelector'
import { ArrowLeft } from '../Icon'
import { getDrawStylePreference } from '../../utils/userPreferences'
import type { Diary, DrawStyle, PicturebookJob, StoryWorkDetail } from '../../types'
import './style.css'

interface Props {
  userId?: number
  date?: string
  workId?: number
  onBack: () => void
}

function diaryBody(diary: Diary): string {
  return diary.text ?? ''
}

function splitParagraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map(paragraph => paragraph.trim())
    .filter(Boolean)
}

function formatDate(date: string): string {
  const [year, month, day] = date.split('-')
  return `${year}年${Number(month)}月${Number(day)}日`
}

function sortDiaries(diaries: Diary[], preferredDate?: string): Diary[] {
  return [...diaries].sort((left, right) => {
    if (left.date === preferredDate && right.date !== preferredDate) return -1
    if (right.date === preferredDate && left.date !== preferredDate) return 1
    return right.date.localeCompare(left.date)
  })
}

export default function DailyPicturebookWizard({ userId, date, workId, onBack }: Props) {
  const toast = useToast()
  const [loading, setLoading] = useState(true)
  const [diaries, setDiaries] = useState<Diary[]>([])
  const [selectedDiaryId, setSelectedDiaryId] = useState<number | null>(null)
  const [selectedParagraphs, setSelectedParagraphs] = useState<number[]>([])
  const [style, setStyle] = useState<DrawStyle>(() => getDrawStylePreference(userId))
  const [work, setWork] = useState<StoryWorkDetail | null>(null)
  const [job, setJob] = useState<PicturebookJob | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const creatingRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    if (workId) {
      storyWorksApi.get(workId)
        .then(result => {
          if (cancelled) return
          setWork(result)
          setStyle(result.style)
          const summary = result.active_picturebook_job ?? result.picturebook_job
          if (!summary) return
          picturebookApi.get(summary.id)
            .then(nextJob => {
              if (!cancelled) setJob(nextJob)
            })
            .catch(() => {
              if (!cancelled) setError('绘本进度暂时打不开')
            })
        })
        .catch(() => {
          if (!cancelled) setError('草稿暂时打不开')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
      return () => { cancelled = true }
    }

    diaryApi.list({ status: 'all' })
      .then(items => {
        if (cancelled) return
        const available = sortDiaries(
          items.filter(item => splitParagraphs(diaryBody(item)).length > 0),
          date,
        )
        setDiaries(available)
        const initial = available[0] ?? null
        setSelectedDiaryId(initial?.id ?? null)
        setSelectedParagraphs(initial ? splitParagraphs(diaryBody(initial)).map((_, index) => index) : [])
      })
      .catch(() => {
        if (!cancelled) setError('日记暂时加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [date, workId])

  useEffect(() => {
    if (!job || job.status !== 'running') return
    let cancelled = false
    const timer = window.setInterval(async () => {
      try {
        const next = await picturebookApi.get(job.id)
        if (!cancelled) setJob(next)
      } catch {
        // Keep the mounted poll quiet through transient network errors.
      }
    }, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [job?.id, job?.status])

  const selectedDiary = useMemo(
    () => diaries.find(item => item.id === selectedDiaryId) ?? null,
    [diaries, selectedDiaryId],
  )
  const paragraphs = useMemo(
    () => selectedDiary ? splitParagraphs(diaryBody(selectedDiary)) : [],
    [selectedDiary],
  )

  const chooseDiary = (diary: Diary) => {
    const nextParagraphs = splitParagraphs(diaryBody(diary))
    setSelectedDiaryId(diary.id)
    setSelectedParagraphs(nextParagraphs.map((_, index) => index))
  }

  const toggleParagraph = (index: number) => {
    setSelectedParagraphs(current => {
      if (current.includes(index)) {
        if (current.length <= 1) return current
        return current.filter(item => item !== index)
      }
      return [...current, index].sort((left, right) => left - right)
    })
  }

  const createDraftAndStart = async () => {
    if (!selectedDiary || saving || creatingRef.current) return
    const selectedSegments = paragraphs.filter((_, index) => selectedParagraphs.includes(index))
    if (selectedSegments.length === 0) return

    creatingRef.current = true
    setSaving(true)
    setError(null)
    try {
      const created = await storyWorksApi.createDraft({
        kind: 'daily_picturebook',
        source_diary_ids: [selectedDiary.id],
        selected_segments: selectedSegments,
        style,
        title: `${selectedDiary.date} 的绘本`,
      })
      setWork(created)
      const started = await storyWorksApi.startPicturebook(created.id)
      setJob(started)
      toast.info('绘本开始生成')
    } catch (e: any) {
      const activeJobId = generationSlotConflictJobId(e, 'picturebook')
      if (activeJobId !== null) {
        try {
          setJob(await picturebookApi.get(activeJobId))
          setError(null)
          toast.info('已为你打开正在生成的绘本')
        } catch {
          setError('正在生成的绘本暂时打不开，请稍后再试')
        }
      } else {
        setError(e?.message ?? '创建失败')
      }
    } finally {
      setSaving(false)
      creatingRef.current = false
    }
  }

  const retryPicturebook = async () => {
    if (!job) return
    try {
      const targetWorkId = work?.id ?? job.work_id
      setJob(
        targetWorkId
          ? await storyWorksApi.startPicturebook(targetWorkId)
          : await picturebookApi.retry(job.id),
      )
      toast.info('正在重画没成功的页')
    } catch {
      toast.error('重试失败')
    }
  }

  const startExistingWork = async () => {
    if (!work || saving || creatingRef.current) return
    creatingRef.current = true
    setSaving(true)
    setError(null)
    try {
      setJob(await storyWorksApi.startPicturebook(work.id))
      toast.info('绘本开始生成')
    } catch (e: any) {
      const activeJobId = generationSlotConflictJobId(e, 'picturebook')
      if (activeJobId !== null) {
        try {
          setJob(await picturebookApi.get(activeJobId))
          setError(null)
          toast.info('已为你打开正在生成的绘本')
        } catch {
          setError('正在生成的绘本暂时打不开，请稍后再试')
        }
      } else {
        setError(e?.message ?? '启动失败')
      }
    } finally {
      setSaving(false)
      creatingRef.current = false
    }
  }

  if (loading) {
    return (
      <main className="daily-picturebook-wizard">
        <button type="button" className="dpw-back" onClick={onBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div className="dpw-state" role="status">正在读取日记…</div>
      </main>
    )
  }

  if (job) {
    return (
      <main className="daily-picturebook-wizard">
        <header className="dpw-header">
          <button type="button" className="dpw-back" onClick={onBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>当日绘本</h1>
            <p>{work?.title ?? '绘本生成中'}</p>
          </div>
        </header>
        <PictureBook job={job} onRetry={retryPicturebook} />
      </main>
    )
  }

  if (work) {
    return (
      <main className="daily-picturebook-wizard">
        <header className="dpw-header">
          <button type="button" className="dpw-back" onClick={onBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>当日绘本</h1>
            <p>{work.title}</p>
          </div>
        </header>
        <section className="dpw-panel">
          <h2>草稿已准备</h2>
          {error && <p className="dpw-error" role="alert">{error}</p>}
          <button
            type="button"
            className="dpw-primary"
            onClick={startExistingWork}
            disabled={saving}
          >
            {saving ? '启动中…' : '开始生成绘本'}
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="daily-picturebook-wizard">
      <header className="dpw-header">
        <button type="button" className="dpw-back" onClick={onBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div>
          <h1>当日绘本</h1>
          <p>{date ? formatDate(date) : '选择一篇日记'}</p>
        </div>
      </header>

      {error && <p className="dpw-error" role="alert">{error}</p>}

      {diaries.length === 0 ? (
        <section className="dpw-panel">
          <h2>没有可用日记</h2>
          <p className="dpw-muted">先完成一篇有正文的日记。</p>
        </section>
      ) : (
        <>
          <section className="dpw-panel" aria-labelledby="dpw-diary-title">
            <h2 id="dpw-diary-title">选择日记</h2>
            <div className="dpw-diary-list">
              {diaries.map(item => (
                <button
                  key={item.id}
                  type="button"
                  className={`dpw-diary-option ${item.id === selectedDiaryId ? 'active' : ''}`}
                  onClick={() => chooseDiary(item)}
                  aria-pressed={item.id === selectedDiaryId}
                >
                  <strong>{item.date}</strong>
                  <span>{splitParagraphs(diaryBody(item)).length} 段</span>
                </button>
              ))}
            </div>
          </section>

          <section className="dpw-panel" aria-labelledby="dpw-paragraph-title">
            <h2 id="dpw-paragraph-title">选择段落</h2>
            <div className="dpw-paragraphs">
              {paragraphs.map((paragraph, index) => {
                const selected = selectedParagraphs.includes(index)
                const isOnlySelected = selected && selectedParagraphs.length === 1
                return (
                  <button
                    key={`${selectedDiaryId}-${index}`}
                    type="button"
                    role="checkbox"
                    aria-checked={selected}
                    disabled={isOnlySelected}
                    className={`dpw-paragraph ${selected ? 'active' : ''}`}
                    onClick={() => toggleParagraph(index)}
                  >
                    <span className="dpw-check" aria-hidden="true">{selected ? '✓' : ''}</span>
                    <span>{paragraph}</span>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="dpw-panel" aria-labelledby="dpw-style-title">
            <h2 id="dpw-style-title">选择风格</h2>
            <StyleSelector value={style} onChange={setStyle} />
          </section>

          <div className="dpw-footer">
            <button
              type="button"
              className="dpw-primary"
              onClick={createDraftAndStart}
              disabled={!selectedDiary || selectedParagraphs.length === 0 || saving}
            >
              {saving ? '创建中…' : '确认生成绘本'}
            </button>
          </div>
        </>
      )}
    </main>
  )
}
