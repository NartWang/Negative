import { useEffect, useMemo, useRef, useState } from 'react'
import { diaryApi, picturebookApi, storyWorksApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import { getDrawStylePreference } from '../../utils/userPreferences'
import { customRange, datesBetweenInclusive, previousWeekRange, thisWeekRange } from '../../utils/week'
import { ArrowLeft } from '../Icon'
import PictureBook from '../PictureBook'
import PictureBookReader from '../PictureBookReader'
import StyleSelector from '../StyleSelector'
import type { Diary, DrawStyle, PicturebookJob, StoryWorkDetail, StorylineCandidate } from '../../types'
import './style.css'

interface Props {
  userId?: number
  workId?: number
  onBack: () => void
}

type RangeMode = 'this_week' | 'previous_week' | 'custom'

function diaryBody(diary: Diary): string {
  return (diary.text || diary.draft_text || '').trim()
}

function diaryUsesDraft(diary: Diary): boolean {
  return diary.status === 'draft' || (!diary.text && Boolean(diary.draft_text?.trim()))
}

function defaultTitle(start: string, end: string): string {
  return `${start} 至 ${end} 的时光故事`
}

function formatDateRange(work: StoryWorkDetail): string {
  const start = work.display_start_date ?? work.source_start_date
  const end = work.display_end_date ?? work.source_end_date
  if (!start) return '未选择日期'
  if (!end || end === start) return start
  return `${start} - ${end}`
}

function candidatesOf(work: StoryWorkDetail | null): StorylineCandidate[] {
  return work?.storyline_candidates ?? []
}

function selectedStorylineIdOf(work: StoryWorkDetail | null): string | null {
  return work?.selected_storyline?.id ?? work?.selected_storyline_id ?? null
}

export default function TimeStoryWizard({ userId, workId, onBack }: Props) {
  const toast = useToast()
  const initialRange = useMemo(() => thisWeekRange(), [])
  const [loading, setLoading] = useState(true)
  const [rangeMode, setRangeMode] = useState<RangeMode>('this_week')
  const [range, setRange] = useState(initialRange)
  const [customStart, setCustomStart] = useState(initialRange.start)
  const [customEnd, setCustomEnd] = useState(initialRange.end)
  const [diaries, setDiaries] = useState<Diary[]>([])
  const [selectedDiaryIds, setSelectedDiaryIds] = useState<number[]>([])
  const [style, setStyle] = useState<DrawStyle>(() => getDrawStylePreference(userId))
  const [work, setWork] = useState<StoryWorkDetail | null>(null)
  const [job, setJob] = useState<PicturebookJob | null>(null)
  const [narrativeDraft, setNarrativeDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rangeValid, setRangeValid] = useState(true)
  const [narrativeSaveFailed, setNarrativeSaveFailed] = useState(false)
  const savedNarrativeRef = useRef('')

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
          const text = result.narrative_text ?? ''
          savedNarrativeRef.current = text
          setNarrativeDraft(text)
          setNarrativeSaveFailed(false)
          const summary = result.active_picturebook_job ?? result.picturebook_job
          if (!summary) return
          picturebookApi.get(summary.id)
            .then(next => {
              if (!cancelled) setJob(next)
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
        setDiaries(items)
      })
      .catch(() => {
        if (!cancelled) setError('日记暂时加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [workId])

  useEffect(() => {
    if (!job || job.status !== 'running') return
    let cancelled = false
    const timer = window.setInterval(async () => {
      try {
        const next = await picturebookApi.get(job.id)
        if (!cancelled) setJob(next)
      } catch {
        // Progress polling should tolerate transient network failures.
      }
    }, 4000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [job?.id, job?.status])

  useEffect(() => {
    if (!work || work.stage !== 'narrative_editing') return
    if (narrativeDraft === savedNarrativeRef.current) return
    const timer = window.setTimeout(async () => {
      try {
        const updated = await storyWorksApi.update(work.id, { narrative_text: narrativeDraft })
        setWork(current => current?.id === updated.id
          ? { ...current, narrative_text: updated.narrative_text ?? narrativeDraft }
          : current)
        savedNarrativeRef.current = updated.narrative_text ?? narrativeDraft
        setNarrativeSaveFailed(false)
      } catch {
        setNarrativeSaveFailed(true)
        setError('自动保存失败，请重试后再继续')
      }
    }, 600)
    return () => window.clearTimeout(timer)
  }, [narrativeDraft, work])

  const availableDiaries = useMemo(() => {
    const validDates = new Set(datesBetweenInclusive(range.start, range.end))
    return diaries
      .filter(item => validDates.has(item.date) && diaryBody(item))
      .sort((left, right) => left.date.localeCompare(right.date))
  }, [diaries, range.end, range.start])

  const availableDiaryIds = useMemo(
    () => availableDiaries.map(item => item.id),
    [availableDiaries],
  )

  const effectiveSelectedDiaryIds = useMemo(() => {
    const availableIds = new Set(availableDiaryIds)
    const kept = selectedDiaryIds.filter(id => availableIds.has(id))
    return kept.length > 0 ? kept : availableDiaryIds
  }, [availableDiaryIds, selectedDiaryIds])

  const orderedSelectedDiaryIds = useMemo(
    () => availableDiaries
      .map(item => item.id)
      .filter(id => effectiveSelectedDiaryIds.includes(id)),
    [availableDiaries, effectiveSelectedDiaryIds],
  )

  useEffect(() => {
    setSelectedDiaryIds(current => {
      const availableIds = new Set(availableDiaryIds)
      const kept = current.filter(id => availableIds.has(id))
      if (kept.length > 0) return kept.length === current.length ? current : kept
      if (availableDiaryIds.length === 0) return current.length === 0 ? current : []
      return availableDiaryIds
    })
  }, [availableDiaryIds])

  const chooseRangeMode = (mode: RangeMode) => {
    setRangeMode(mode)
    setError(null)
    setRangeValid(true)
    if (mode === 'this_week') setRange(thisWeekRange())
    if (mode === 'previous_week') setRange(previousWeekRange())
    if (mode === 'custom') {
      try {
        setRange(customRange(customStart, customEnd))
        setRangeValid(true)
      } catch (e: any) {
        setRangeValid(false)
        setError(e?.message ?? '日期范围不可用')
      }
    }
  }

  const applyCustomRange = (start: string, end: string) => {
    setCustomStart(start)
    setCustomEnd(end)
    if (rangeMode !== 'custom') return
    try {
      setRange(customRange(start, end))
      setRangeValid(true)
      setError(null)
    } catch (e: any) {
      setRangeValid(false)
      setError(e?.message ?? '日期范围不可用')
    }
  }

  const toggleDiary = (id: number) => {
    setSelectedDiaryIds(current => {
      const availableIds = new Set(availableDiaryIds)
      const kept = current.filter(item => availableIds.has(item))
      const baseline = kept.length > 0 ? kept : availableDiaryIds
      if (baseline.includes(id)) {
        if (baseline.length <= 1) return baseline
        return baseline.filter(item => item !== id)
      }
      return availableDiaryIds.filter(item => baseline.includes(item) || item === id)
    })
  }

  const createDraft = async () => {
    if (busy || !rangeValid || orderedSelectedDiaryIds.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const created = await storyWorksApi.createDraft({
        kind: 'time_story',
        source_start_date: range.start,
        source_end_date: range.end,
        source_diary_ids: orderedSelectedDiaryIds,
        style,
        title: defaultTitle(range.start, range.end),
      })
      setWork(created)
      setNarrativeDraft(created.narrative_text ?? '')
      savedNarrativeRef.current = created.narrative_text ?? ''
    } catch (e: any) {
      setError(e?.message ?? '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const generateStorylines = async (replace = false) => {
    if (!work || busy) return
    setBusy(true)
    setError(null)
    try {
      const updated = await storyWorksApi.generateStorylines(work.id, replace ? { replace: true } : {})
      setWork(updated)
      setError(updated.generation_error ?? null)
    } catch (e: any) {
      setError(e?.message ?? '故事线生成失败')
    } finally {
      setBusy(false)
    }
  }

  const selectStoryline = async (id: string) => {
    if (!work || busy) return
    setBusy(true)
    setError(null)
    try {
      const updated = await storyWorksApi.update(work.id, { selected_storyline_id: id })
      setWork(updated)
    } catch (e: any) {
      setError(e?.message ?? '故事线保存失败')
    } finally {
      setBusy(false)
    }
  }

  const generatePicturebookFromStoryline = async () => {
    if (!work || !selectedStorylineIdOf(work) || busy) return
    setBusy(true)
    setError(null)
    try {
      const narrated = work.stage === 'narrative_editing' && work.narrative_text?.trim()
        ? work
        : await storyWorksApi.generateNarrative(work.id)
      if (narrated.generation_error || !narrated.narrative_text?.trim()) {
        setWork(narrated)
        throw new Error(narrated.generation_error || '故事文本暂时没有生成成功')
      }
      const confirmed = narrated.stage === 'narrative_confirmed'
        ? narrated
        : await storyWorksApi.confirmNarrative(narrated.id)
      const styled = confirmed.style === style
        ? confirmed
        : await storyWorksApi.update(confirmed.id, { style })
      setWork(styled)
      setNarrativeDraft(styled.narrative_text ?? '')
      savedNarrativeRef.current = styled.narrative_text ?? ''
      setJob(await storyWorksApi.startPicturebook(styled.id))
      toast.info('绘本开始生成')
    } catch (e: any) {
      setError(e?.message ?? '绘本生成失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  const changeStyle = (nextStyle: DrawStyle) => {
    if (busy) return
    setStyle(nextStyle)
    setError(null)
  }

  const startPicturebook = async () => {
    if (!work || busy) return
    setBusy(true)
    setError(null)
    try {
      const styled = work.style === style
        ? work
        : await storyWorksApi.update(work.id, { style })
      setWork(styled)
      setJob(await storyWorksApi.startPicturebook(styled.id))
      toast.info('绘本开始生成')
    } catch (e: any) {
      setError(e?.message ?? '启动失败')
    } finally {
      setBusy(false)
    }
  }

  const retryPicturebook = async () => {
    if (!work || busy) return
    setBusy(true)
    try {
      setJob(await storyWorksApi.startPicturebook(work.id))
      toast.info('正在重画没成功的页')
    } catch {
      toast.error('重试失败')
    } finally {
      setBusy(false)
    }
  }

  const editConfirmedNarrative = async () => {
    if (!work || busy) return
    setBusy(true)
    setError(null)
    try {
      const updated = await storyWorksApi.update(work.id, { narrative_text: narrativeDraft })
      setWork(updated)
      savedNarrativeRef.current = updated.narrative_text ?? narrativeDraft
    } catch {
      setError('暂时不能编辑故事文本')
    } finally {
      setBusy(false)
    }
  }

  const hasUnsavedNarrative = Boolean(
    work?.stage === 'narrative_editing'
    && narrativeDraft !== savedNarrativeRef.current,
  )

  const guardedBack = () => {
    if (hasUnsavedNarrative || narrativeSaveFailed) {
      setError('故事文本还没保存成功，请先确认或等待保存完成')
      return
    }
    onBack()
  }

  if (loading) {
    return (
      <main className="time-story-wizard">
        <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div className="tsw-state" role="status">正在读取时光故事…</div>
      </main>
    )
  }

  if (job) {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>时光故事</h1>
            <p>{work?.title ?? '绘本生成中'}</p>
          </div>
        </header>
        <PictureBook job={job} onRetry={retryPicturebook} />
      </main>
    )
  }

  if (work?.stage === 'ready' || work?.status === 'ready') {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>时光故事</h1>
            <p>{formatDateRange(work)}</p>
          </div>
        </header>
        <PictureBookReader pages={work.pages} title={work.title} />
      </main>
    )
  }

  const candidates = candidatesOf(work)
  const selectedStorylineId = selectedStorylineIdOf(work)

  if (work && (work.stage === 'sources_selected' || work.stage === 'storylines_ready')) {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>选择故事线</h1>
            <p>{formatDateRange(work)}</p>
          </div>
        </header>
        {error && <p className="tsw-error" role="alert">{error}</p>}
        {candidates.length === 0 ? (
          <section className="tsw-panel">
            <h2>生成三条故事线</h2>
            <p className="tsw-muted">会根据所选日记整理三种叙事方向。</p>
            <button type="button" className="tsw-primary" onClick={() => generateStorylines()} disabled={busy}>
              {busy ? '生成中…' : '生成故事线'}
            </button>
          </section>
        ) : (
          <>
            <section className="tsw-panel">
              <div className="tsw-panel-title">
                <h2>三条故事线</h2>
                <span>请选择一条 · 三选一</span>
              </div>
              <div className="tsw-candidates">
                {candidates.map(candidate => (
                  <button
                    key={candidate.id}
                    type="button"
                    role="radio"
                    aria-checked={selectedStorylineId === candidate.id}
                    className={`tsw-candidate ${selectedStorylineId === candidate.id ? 'active' : ''}`}
                    disabled={busy}
                    onClick={() => selectStoryline(candidate.id)}
                  >
                    <strong>{candidate.title}</strong>
                    <span>{candidate.summary}</span>
                    {candidate.source_dates?.length ? <small>{candidate.source_dates.join(' / ')}</small> : null}
                    {candidate.tone && <small>{candidate.tone}</small>}
                  </button>
                ))}
              </div>
            </section>
            <section className="tsw-panel">
              <h2>选择绘本风格</h2>
              <p className="tsw-muted">选择一种画面风格，再把这条故事线变成绘本。</p>
              <StyleSelector value={style} onChange={changeStyle} disabled={busy} />
            </section>
            <div className="tsw-footer">
              <button
                type="button"
                className="tsw-primary"
                onClick={generatePicturebookFromStoryline}
                disabled={!selectedStorylineId || busy}
              >
                {busy ? '正在生成绘本…' : '生成绘本'}
              </button>
            </div>
          </>
        )}
      </main>
    )
  }

  if (work?.stage === 'narrative_editing') {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>生成绘本</h1>
            <p>{formatDateRange(work)}</p>
          </div>
        </header>
        {error && <p className="tsw-error" role="alert">{error}</p>}
        <section className="tsw-panel">
          <h2>选择绘本风格</h2>
          <StyleSelector value={style} onChange={changeStyle} disabled={busy} />
        </section>
        <div className="tsw-footer">
          <button
            type="button"
            className="tsw-primary"
            onClick={generatePicturebookFromStoryline}
            disabled={!narrativeDraft.trim() || busy}
          >
            {busy ? '正在生成绘本…' : '生成绘本'}
          </button>
        </div>
      </main>
    )
  }

  if (work?.stage === 'rendering') {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>绘本生成中</h1>
            <p>{work.title}</p>
          </div>
        </header>
        {error && <p className="tsw-error" role="alert">{error}</p>}
        <section className="tsw-panel">
          <h2>正在生成绘本</h2>
          <p className="tsw-muted">绘本任务已经启动，稍后返回这里查看进度。</p>
        </section>
      </main>
    )
  }

  if (work?.stage === 'render_failed') {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>绘本生成失败</h1>
            <p>{work.title}</p>
          </div>
        </header>
        {error && <p className="tsw-error" role="alert">{error}</p>}
        <section className="tsw-panel">
          <h2>可以重试生成</h2>
          <p className="tsw-muted">{work.generation_error ?? '上一次生成没有完成。'}</p>
        </section>
        <div className="tsw-footer">
          <button type="button" className="tsw-primary" onClick={retryPicturebook} disabled={busy}>
            {busy ? '重试中…' : '重试绘本'}
          </button>
        </div>
      </main>
    )
  }

  if (work?.stage === 'narrative_confirmed') {
    return (
      <main className="time-story-wizard">
        <header className="tsw-header">
          <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
            <ArrowLeft />
          </button>
          <div>
            <h1>选择绘本风格</h1>
            <p>{work.title}</p>
          </div>
        </header>
        {error && <p className="tsw-error" role="alert">{error}</p>}
        <section className="tsw-panel">
          <h2>已确认文本</h2>
          <p className="tsw-narrative-preview">{work.narrative_text || narrativeDraft}</p>
          <button type="button" className="tsw-link-button" onClick={editConfirmedNarrative}>
            编辑故事文本
          </button>
        </section>
        <section className="tsw-panel">
          <h2>绘本风格</h2>
          <StyleSelector value={style} onChange={changeStyle} disabled={busy} />
        </section>
        <div className="tsw-footer">
          <button type="button" className="tsw-primary" onClick={startPicturebook} disabled={busy}>
            {busy ? '正在生成绘本…' : '生成绘本'}
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className="time-story-wizard">
      <header className="tsw-header">
        <button type="button" className="tsw-back" onClick={guardedBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div>
          <h1>选择日记范围</h1>
          <p>把一段时间整理成一本绘本</p>
        </div>
      </header>

      {error && <p className="tsw-error" role="alert">{error}</p>}

      <section className="tsw-panel">
        <h2>范围</h2>
        <div className="tsw-segmented" aria-label="选择范围">
          <button type="button" aria-pressed={rangeMode === 'this_week'} onClick={() => chooseRangeMode('this_week')}>
            本周
          </button>
          <button
            type="button"
            aria-pressed={rangeMode === 'previous_week'}
            onClick={() => chooseRangeMode('previous_week')}
          >
            上周
          </button>
          <button type="button" aria-pressed={rangeMode === 'custom'} onClick={() => chooseRangeMode('custom')}>
            自选
          </button>
        </div>
        {rangeMode === 'custom' && (
          <div className="tsw-custom-range">
            <label>
              开始
              <input type="date" value={customStart} onChange={event => applyCustomRange(event.target.value, customEnd)} />
            </label>
            <label>
              结束
              <input type="date" value={customEnd} onChange={event => applyCustomRange(customStart, event.target.value)} />
            </label>
          </div>
        )}
        <p className="tsw-muted">{range.start} - {range.end}</p>
      </section>

      <section className="tsw-panel">
        <h2>日记</h2>
        {availableDiaries.length === 0 ? (
          <p className="tsw-muted">这个范围里没有有正文的日记。</p>
        ) : (
          <div className="tsw-diary-list">
            {availableDiaries.map(diary => {
              const selected = effectiveSelectedDiaryIds.includes(diary.id)
              const onlySelected = selected && orderedSelectedDiaryIds.length === 1
              return (
                <button
                  key={diary.id}
                  type="button"
                  role="checkbox"
                  aria-checked={selected}
                  disabled={onlySelected}
                  className={`tsw-diary ${selected ? 'active' : ''}`}
                  onClick={() => toggleDiary(diary.id)}
                >
                  <span className="tsw-check" aria-hidden="true">{selected ? '✓' : ''}</span>
                  <span>
                    <strong>{diary.date}</strong>
                    <em>{diaryUsesDraft(diary) ? '草稿' : '已保存'}</em>
                    <small>{diaryBody(diary)}</small>
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </section>

      <div className="tsw-footer">
        <button
          type="button"
          className="tsw-primary"
          onClick={createDraft}
          disabled={!rangeValid || orderedSelectedDiaryIds.length === 0 || busy}
        >
          {busy ? '创建中…' : '继续'}
        </button>
      </div>
    </main>
  )
}
