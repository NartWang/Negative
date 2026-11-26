import { useEffect, useRef, useState, useCallback } from 'react'
import { diaryApi, imageApi, picturebookApi, storyApi } from '../../api/client'
import type {
  Diary,
  DiaryImage,
  DiarySourceSelection,
  DrawStyle,
  EmotionMode,
  PicturebookJob,
} from '../../types'
import { useToast } from '../../contexts/ToastContext'
import Modal from '../../components/Modal'
import ImageCandidates from '../../components/ImageCandidates'
import PictureBook from '../../components/PictureBook'
import WorkSaveSheet from '../../components/WorkSaveSheet'
import BottomSheet from '../../components/BottomSheet'
import CheckinCalendar from '../../components/CheckinCalendar'
import { CalendarDays } from 'lucide-react'
import {
  getDrawStylePreference,
  getEmotionModePreference,
} from '../../utils/userPreferences'
import { addDays } from '../../utils/date'
import './style.css'

interface Props {
  userId?: number
  date: string
  selection?: DiarySourceSelection
  onBack: () => void
  onChangeDate: (date: string) => void
}

interface PendingWorkSave {
  diaryId: number
  date: string
  text: string
  images: Array<{ id: number; url: string; asset_id?: string | null }>
  selectedImageIds: number[]
}

type ContentMutationKind = 'ai-fill'

export default function DiaryEditor({ userId, date, selection: sourceSelection, onBack, onChangeDate }: Props) {
  const toast = useToast()
  const [diary, setDiary] = useState<Diary | null>(null)
  const [text, setText] = useState('')
  const [savingFlag, setSavingFlag] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [contentMutationKind, setContentMutationKind] = useState<ContentMutationKind | null>(null)
  const [showOverwriteModal, setShowOverwriteModal] = useState(false)
  const [emotionMode, setEmotionMode] = useState<EmotionMode>(() => getEmotionModePreference(userId))

  const [drawStyle] = useState(() => getDrawStylePreference(userId))
  const [candidates, setCandidates] = useState<DiaryImage[]>([])
  const [kept, setKept] = useState<number[]>([])
  const [book, setBook] = useState<PicturebookJob | null>(null)
  const [finishing, setFinishing] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [dateSwitching, setDateSwitching] = useState(false)
  const [navigationError, setNavigationError] = useState<string | null>(null)
  const [pendingWorkSave, setPendingWorkSave] = useState<PendingWorkSave | null>(null)
  const [initialLoadError, setInitialLoadError] = useState<string | null>(null)
  const [datePickerOpen, setDatePickerOpen] = useState(false)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const saveTimerRef = useRef<number | null>(null)
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve())
  const mountedRef = useRef(true)
  const contentMutationGenerationRef = useRef(0)
  const contentMutationPromiseRef = useRef<Promise<void> | null>(null)
  const contentMutationBusy = contentMutationKind !== null
  const aiFilling = contentMutationKind === 'ai-fill'
  const editorLocked = finishing || leaving || dateSwitching || contentMutationBusy || Boolean(pendingWorkSave)

  const queueDiaryUpdate = useCallback((
    diaryId: number,
    data: Parameters<typeof diaryApi.update>[1],
  ) => {
    const update = saveQueueRef.current.then(
      () => diaryApi.update(diaryId, data),
      () => diaryApi.update(diaryId, data),
    )
    saveQueueRef.current = update.then(() => undefined, () => undefined)
    return update
  }, [])

  const runContentMutation = useCallback(async <T,>(
    kind: ContentMutationKind,
    operation: () => Promise<T>,
    applyResult: (result: T) => void,
  ) => {
    if (contentMutationPromiseRef.current) return
    const generation = ++contentMutationGenerationRef.current
    if (mountedRef.current) setContentMutationKind(kind)
    const task = (async () => {
      const result = await operation()
      if (!mountedRef.current || contentMutationGenerationRef.current !== generation) return
      applyResult(result)
    })()
    const tracked = task.finally(() => {
      if (contentMutationPromiseRef.current === tracked) {
        contentMutationPromiseRef.current = null
      }
      if (mountedRef.current && contentMutationGenerationRef.current === generation) {
        setContentMutationKind(null)
      }
    })
    contentMutationPromiseRef.current = tracked
    await tracked
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      contentMutationGenerationRef.current += 1
    }
  }, [])

  // Load or create diary for this date. Retry always re-runs GET first and only
  // falls back to createBlank on a successful empty GET — never on a failed one.
  const loadGenerationRef = useRef(0)
  const loadDiary = useCallback(async (targetDate: string) => {
    const generation = ++loadGenerationRef.current
    setDiary(null)
    setText('')
    setCandidates([])
    setKept([])
    setBook(null)
    setSavingFlag('idle')
    setInitialLoadError(null)
    try {
      const existing = await diaryApi.get(targetDate)
      const d = existing ?? await diaryApi.createBlank(targetDate)
      if (loadGenerationRef.current !== generation) return
      setDiary(d)
      setText(d.draft_text ?? d.text ?? '')
      const keptIds = (d.images || []).filter(i => i.kept === 1).map(i => i.id)
      setCandidates(d.images || [])
      setKept(keptIds)
    } catch {
      if (loadGenerationRef.current !== generation) return
      setInitialLoadError('加载日记失败，请检查网络后重试')
    }
  }, [])

  useEffect(() => {
    void loadDiary(date)
  }, [date, loadDiary])

  // Restore an in-flight or finished picturebook when the editor reopens.
  useEffect(() => {
    if (!diary) return
    let cancelled = false
    picturebookApi.latest(diary.id)
      .then(job => { if (!cancelled && job) setBook(job) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [diary?.id])

  // Poll while the book is being written and rendered (minutes, not seconds).
  useEffect(() => {
    if (!book || book.status !== 'running') return
    const jobId = book.id
    const timer = window.setInterval(async () => {
      try {
        const next = await picturebookApi.get(jobId)
        if (mountedRef.current) setBook(next)
      } catch { /* transient: keep polling */ }
    }, 4000)
    return () => window.clearInterval(timer)
  }, [book?.id, book?.status])

  // Auto-save draft 600ms after last edit
  useEffect(() => {
    if (!diary) return
    if (finishing || leaving || contentMutationBusy || pendingWorkSave) return
    if (text === (diary.draft_text ?? diary.text ?? '')) return
    setSavingFlag('saving')
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        const updated = await queueDiaryUpdate(diary.id, { draft_text: text, text })
        setDiary(updated)
        setSavingFlag('saved')
        window.setTimeout(() => setSavingFlag('idle'), 1200)
      } catch {
        toast.error('草稿保存失败')
        setSavingFlag('idle')
      }
    }, 600)
    return () => { if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current) }
  }, [
    text, diary, toast, queueDiaryUpdate, finishing, leaving,
    contentMutationBusy, pendingWorkSave,
  ])

  const requestAiFill = useCallback(() => {
    if (contentMutationPromiseRef.current || pendingWorkSave || finishing || leaving) return
    if (text.trim() && diary) {
      setShowOverwriteModal(true)
    } else {
      doAiFill()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, diary, pendingWorkSave, finishing, leaving, emotionMode])

  const doAiFill = async () => {
    if (!diary || contentMutationPromiseRef.current || pendingWorkSave) return
    setShowOverwriteModal(false)
    try {
      await runContentMutation(
        'ai-fill',
        async () => {
          if (saveTimerRef.current) {
            window.clearTimeout(saveTimerRef.current)
            saveTimerRef.current = null
          }
          await queueDiaryUpdate(diary.id, { text, draft_text: text })
          return diaryApi.aiFill(diary.id, {
            emotion_mode: emotionMode,
            ...(sourceSelection ?? {}),
          })
        },
        updated => {
          setDiary(updated)
          setText(updated.draft_text ?? updated.text ?? '')
          toast.success('AI 已为你写好初稿')
        },
      )
    } catch (e: any) {
      if (mountedRef.current) {
        toast.error(e?.message?.includes('当天没有') ? '当天没有任何记录，无法生成' : 'AI 生成失败')
      }
    }
  }

  const retryPicturebook = async () => {
    if (!book) return
    try {
      setBook(await picturebookApi.retry(book.id))
      toast.info('正在重画没成功的页')
    } catch {
      toast.error('重试失败')
    }
  }

  const toggleKeep = (id: number) => {
    setKept(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const finishDiary = async () => {
    if (!diary || finishing || leaving || contentMutationPromiseRef.current || pendingWorkSave) return
    const capturedText = text
    const capturedKept = [...kept]
    setFinishing(true)
    setNavigationError(null)
    try {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current)
        saveTimerRef.current = null
      }
      const confirmed = await queueDiaryUpdate(diary.id, {
        text: capturedText,
        draft_text: capturedText,
        status: 'confirmed',
      })
      const { images } = await imageApi.keep(diary.id, capturedKept)
      setDiary({ ...confirmed, images })
      setCandidates(current => current.map(image => ({
        ...image,
        kept: capturedKept.includes(image.id) ? 1 : 0,
      })))
      const availableImages = images.map(image => ({
        id: image.id,
        url: image.url,
        asset_id: image.asset_id,
      }))
      setPendingWorkSave({
        diaryId: diary.id,
        date: diary.date,
        text: capturedText,
        images: availableImages,
        selectedImageIds: availableImages.filter(image => image.asset_id).map(image => image.id),
      })
      toast.success('日记已完成，仍为私密')
    } catch (e: any) {
      toast.error(e?.message ?? '完成日记失败')
    } finally {
      setFinishing(false)
    }
  }

  const saveStoryDraft = async (_imageIds: number[]) => {
    if (!pendingWorkSave) throw new Error('没有可保存的日记')
    const sourceImageAssetIds = pendingWorkSave.images
      .filter(image => _imageIds.includes(image.id) && image.asset_id)
      .map(image => image.asset_id as string)
    await storyApi.createWork({
      source_diary_id: pendingWorkSave.diaryId,
      source_fragment_ids: sourceSelection?.fragment_ids ?? [],
      source_image_asset_ids: sourceImageAssetIds,
      selected_segments: [pendingWorkSave.text],
      medium: 'picture_book',
      narrative_mode: 'true_record',
      style: drawStyle,
      title: `${pendingWorkSave.date} 的故事`,
    })
    toast.success('已保存到故事，可继续生成绘本或漫剧')
  }

  const handleBack = async () => {
    if (!diary || finishing || leaving || contentMutationPromiseRef.current || pendingWorkSave) return
    const capturedText = text
    setLeaving(true)
    setNavigationError(null)
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    try {
      const updated = await queueDiaryUpdate(diary.id, {
        text: capturedText,
        draft_text: capturedText,
      })
      setDiary(updated)
      onBack()
    } catch {
      setNavigationError('离开前保存失败，请重试')
      setLeaving(false)
    }
  }

  const flushDraftBeforeNavigation = useCallback(async () => {
    if (!diary) return
    const capturedText = text
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    setSavingFlag('saving')
    const updated = await queueDiaryUpdate(diary.id, {
      text: capturedText,
      draft_text: capturedText,
    })
    if (mountedRef.current) {
      setDiary(updated)
      setSavingFlag('saved')
      window.setTimeout(() => {
        if (mountedRef.current) setSavingFlag('idle')
      }, 1200)
    }
  }, [diary, queueDiaryUpdate, text])

  const switchDate = useCallback(async (nextDate: string) => {
    if (!nextDate || nextDate === date || editorLocked || contentMutationPromiseRef.current) return
    setDateSwitching(true)
    setNavigationError(null)
    try {
      await flushDraftBeforeNavigation()
      onChangeDate(nextDate)
    } catch {
      setNavigationError('切换日期前保存失败，请重试')
    } finally {
      if (mountedRef.current) setDateSwitching(false)
    }
  }, [date, editorLocked, flushDraftBeforeNavigation, onChangeDate])

  if (!diary) {
    if (initialLoadError) {
      return (
        <div className="diary-editor loading">
          <div role="alert" className="load-error" style={{ margin: 20 }}>
            <p>{initialLoadError}</p>
            <div className="load-error-actions">
              <button type="button" onClick={() => void loadDiary(date)}>重试</button>
              <button type="button" onClick={onBack}>返回记录页</button>
            </div>
          </div>
        </div>
      )
    }
    return (
      <div className="diary-editor loading">
        <button className="back-btn" onClick={onBack}>← 返回</button>
        <p className="muted" style={{ padding: 20 }}>加载中…</p>
      </div>
    )
  }

  return (
    <div className="diary-editor">
      <header className="de-header">
        <button className="back-btn" onClick={handleBack} disabled={editorLocked}>← 返回</button>
        <div className="de-date">
          <div className="de-date-controls">
            <button
              type="button"
              className="de-date-step"
              aria-label="前一天"
              onClick={() => switchDate(addDays(date, -1))}
              disabled={editorLocked}
            >
              ‹
            </button>
            <button
              type="button"
              className="de-date-input"
              aria-label="日记日期"
              onClick={() => setDatePickerOpen(true)}
              disabled={editorLocked}
            >
              <span>{date.replace(/-/g, '/')}</span>
              <CalendarDays aria-hidden="true" />
            </button>
            <button
              type="button"
              className="de-date-step"
              aria-label="后一天"
              onClick={() => switchDate(addDays(date, 1))}
              disabled={editorLocked}
            >
              ›
            </button>
          </div>
          <div className="de-save-state">
            {dateSwitching && '切换日期中…'}
            {!dateSwitching && contentMutationBusy && 'AI 生成中…'}
            {!dateSwitching && !contentMutationBusy && savingFlag === 'saving' && '保存中…'}
            {!dateSwitching && !contentMutationBusy && savingFlag === 'saved' && '草稿已保存'}
            {!dateSwitching && !contentMutationBusy && savingFlag === 'idle' && (diary.status === 'confirmed' ? '已完成' : '私密草稿')}
          </div>
        </div>
        <button className="save-btn pressable" onClick={finishDiary} disabled={editorLocked}>
          {finishing ? '正在完成…' : '完成日记'}
        </button>
      </header>

      <BottomSheet open={datePickerOpen} onClose={() => setDatePickerOpen(false)} title="选择日记日期">
        <CheckinCalendar
          markerMode="fragments"
          selectedDate={date}
          onSelectDate={nextDate => {
            setDatePickerOpen(false)
            if (nextDate !== date) void switchDate(nextDate)
          }}
        />
      </BottomSheet>

      {navigationError && <p className="de-navigation-error" role="alert">{navigationError}</p>}

      <fieldset className="de-workspace" disabled={editorLocked}>
        <div className="de-toolbar">
          <button className="tool-btn pressable" onClick={requestAiFill} disabled={contentMutationBusy}>
            {aiFilling ? '生成中...' : '一键生成'}
          </button>
          <div className="de-style-selector" role="radiogroup" aria-label="日记风格">
            <span className="de-style-title">日记风格</span>
            <div className="de-style-options">
              <label className="de-style-option">
                <input
                  type="radio"
                  name="diary-style"
                  value="real"
                  checked={emotionMode === 'real'}
                  disabled={editorLocked}
                  onChange={() => setEmotionMode('real')}
                />
                <span>真实</span>
              </label>
              <label className="de-style-option">
                <input
                  type="radio"
                  name="diary-style"
                  value="imagery"
                  checked={emotionMode === 'imagery'}
                  disabled={editorLocked}
                  onChange={() => setEmotionMode('imagery')}
                />
                <span>意象</span>
              </label>
            </div>
          </div>
        </div>

        <textarea
          ref={textareaRef}
          className="de-textarea"
          value={text}
          onChange={e => {
            setText(e.target.value)
            setNavigationError(null)
          }}
          placeholder="今天的故事，从这里开始..."
        />

        {candidates.length > 0 && (
          <section className="de-section">
            <h3>画面（点击勾选保留）</h3>
            <ImageCandidates candidates={candidates} kept={kept} onToggle={toggleKeep} />
          </section>
        )}

        {book && (
          <section className="de-section">
            <h3>历史绘本</h3>
            <PictureBook job={book} onRetry={retryPicturebook} />
          </section>
        )}
      </fieldset>

      <Modal
        open={showOverwriteModal}
        onClose={() => setShowOverwriteModal(false)}
        title="文本框已有内容"
        description="AI 生成会覆盖当前内容。是否继续？"
        confirmText="覆盖生成"
        danger
        onConfirm={doAiFill}
      />

      <WorkSaveSheet
        open={Boolean(pendingWorkSave)}
        kind="diary"
        title={`${pendingWorkSave?.date ?? diary.date} 的日记`}
        summary={pendingWorkSave?.text ?? ''}
        images={pendingWorkSave?.images ?? []}
        selectedImageIds={pendingWorkSave?.selectedImageIds ?? []}
        onClose={() => {
          setPendingWorkSave(null)
          onBack()
        }}
        onConfirm={saveStoryDraft}
      />
    </div>
  )
}
