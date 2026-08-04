import { useEffect, useRef, useState, useCallback } from 'react'
import { diaryApi, imageApi, roomsApi } from '../../api/client'
import type { Diary, DiaryImage, DrawStyle, EmotionMode, RewriteDirection } from '../../types'
import { useToast } from '../../contexts/ToastContext'
import BottomSheet from '../../components/BottomSheet'
import Modal from '../../components/Modal'
import ParagraphSelector from '../../components/ParagraphSelector'
import StyleSelector from '../../components/StyleSelector'
import ImageCandidates from '../../components/ImageCandidates'
import PublishSheet from '../../components/PublishSheet'
import { useRoom } from '../../contexts/RoomContext'
import { getUserPreference } from '../../utils/userPreferences'
import './style.css'

interface Props {
  userId?: number
  date: string
  onBack: () => void
}

interface PendingPublication {
  diaryId: number
  date: string
  text: string
  images: Array<{ id: number; url: string }>
  selectedImageIds: number[]
}

type ContentMutationKind = 'ai-fill' | 'rewrite'

const REWRITE_OPTIONS: { key: RewriteDirection; label: string }[] = [
  { key: 'warmer',  label: '更温暖' },
  { key: 'humor',   label: '更幽默' },
  { key: 'concise', label: '更简洁' },
  { key: 'poetic',  label: '更诗意' },
  { key: 'custom',  label: '自定义' },
]

export default function DiaryEditor({ userId, date, onBack }: Props) {
  const toast = useToast()
  const { room } = useRoom()
  const [diary, setDiary] = useState<Diary | null>(null)
  const [text, setText] = useState('')
  const [savingFlag, setSavingFlag] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [contentMutationKind, setContentMutationKind] = useState<ContentMutationKind | null>(null)
  const [showOverwriteModal, setShowOverwriteModal] = useState(false)
  const [showRewriteSheet, setShowRewriteSheet] = useState(false)
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [customRewrite, setCustomRewrite] = useState('')
  const emotionMode = (
    getUserPreference(userId, 'emotionMode') as EmotionMode
  ) || 'warm'

  const [selectedParagraphs, setSelectedParagraphs] = useState<number[]>([])
  const [drawStyle, setDrawStyle] = useState<DrawStyle>(
    (getUserPreference(userId, 'drawStyle') as DrawStyle) || 'ghibli'
  )
  const [customStyle, setCustomStyle] = useState(
    getUserPreference(userId, 'customDraw') || ''
  )
  const [imageCount, setImageCount] = useState<1 | 2 | 4>(4)
  const [candidates, setCandidates] = useState<DiaryImage[]>([])
  const [kept, setKept] = useState<number[]>([])
  const [generatingImages, setGeneratingImages] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [navigationError, setNavigationError] = useState<string | null>(null)
  const [pendingPublication, setPendingPublication] = useState<PendingPublication | null>(null)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const saveTimerRef = useRef<number | null>(null)
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve())
  const mountedRef = useRef(true)
  const contentMutationGenerationRef = useRef(0)
  const contentMutationPromiseRef = useRef<Promise<void> | null>(null)
  const contentMutationBusy = contentMutationKind !== null
  const aiFilling = contentMutationKind === 'ai-fill'
  const rewriting = contentMutationKind === 'rewrite'
  const editorLocked = finishing || leaving || contentMutationBusy || Boolean(pendingPublication)

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

  // Load or create diary for this date
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const existing = await diaryApi.get(date)
        const d = existing ?? await diaryApi.createBlank(date)
        if (cancelled) return
        setDiary(d)
        setText(d.draft_text ?? d.text ?? '')
        const keptIds = (d.images || []).filter(i => i.kept === 1).map(i => i.id)
        setCandidates(d.images || [])
        setKept(keptIds)
      } catch (e) {
        toast.error('加载日记失败')
      }
    })()
    return () => { cancelled = true }
  }, [date, toast])

  // Auto-save draft 600ms after last edit
  useEffect(() => {
    if (!diary) return
    if (finishing || leaving || contentMutationBusy || pendingPublication) return
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
    contentMutationBusy, pendingPublication,
  ])

  const requestAiFill = useCallback(() => {
    if (contentMutationPromiseRef.current || pendingPublication || finishing || leaving) return
    if (text.trim() && diary) {
      setShowOverwriteModal(true)
    } else {
      doAiFill()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, diary, pendingPublication, finishing, leaving])

  const doAiFill = async () => {
    if (!diary || contentMutationPromiseRef.current || pendingPublication) return
    setShowOverwriteModal(false)
    try {
      await runContentMutation(
        'ai-fill',
        async () => {
          if (saveTimerRef.current) {
            window.clearTimeout(saveTimerRef.current)
            saveTimerRef.current = null
          }
          await saveQueueRef.current
          return diaryApi.aiFill(diary.id, { emotion_mode: emotionMode })
        },
        updated => {
          setDiary(updated)
          setText(updated.draft_text ?? updated.text ?? '')
          toast.success('✨ AI 已为你写好初稿')
        },
      )
    } catch (e: any) {
      if (mountedRef.current) {
        toast.error(e?.message?.includes('当天没有') ? '当天没有任何记录，无法生成' : 'AI 生成失败')
      }
    }
  }

  const captureSelection = () => {
    if (contentMutationPromiseRef.current || pendingPublication) return
    const t = textareaRef.current
    if (!t) { setSelection(null); return }
    const start = t.selectionStart
    const end = t.selectionEnd
    if (start === end) {
      toast.info('请先在文本里选中一段')
      return
    }
    const selText = text.slice(start, end).trim()
    if (!selText) return
    setSelection({ start, end, text: selText })
    setShowRewriteSheet(true)
  }

  const applyRewrite = async (direction: RewriteDirection) => {
    if (!diary || !selection || contentMutationPromiseRef.current || pendingPublication) return
    setShowRewriteSheet(false)
    const capturedText = text
    const capturedSelection = selection
    const payload: { paragraph: string; direction: RewriteDirection; custom_prompt?: string } = {
      paragraph: capturedSelection.text,
      direction,
    }
    if (direction === 'custom') payload.custom_prompt = customRewrite
    try {
      await runContentMutation(
        'rewrite',
        async () => {
          if (saveTimerRef.current) {
            window.clearTimeout(saveTimerRef.current)
            saveTimerRef.current = null
          }
          await saveQueueRef.current
          return diaryApi.aiRewrite(diary.id, payload)
        },
        result => {
          const before = capturedText.slice(0, capturedSelection.start)
          const after = capturedText.slice(capturedSelection.end)
          setText(before + result.rewritten + after)
          toast.success('✨ 已改写')
        },
      )
    } catch {
      if (mountedRef.current) toast.error('改写失败')
    } finally {
      if (mountedRef.current) setSelection(null)
    }
  }

  const generateImages = async () => {
    if (!diary || contentMutationPromiseRef.current || pendingPublication) return
    const t = text.trim()
    if (!t) { toast.error('先写点内容再生成画面'); return }
    const paragraphs = (() => {
      const all = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean)
      if (selectedParagraphs.length === 0) return [] // whole diary
      return selectedParagraphs.map(i => all[i]).filter(Boolean)
    })()
    setGeneratingImages(true)
    try {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current)
        saveTimerRef.current = null
      }
      const flushed = await queueDiaryUpdate(diary.id, { text, draft_text: text })
      setDiary(flushed)
      const { candidates: newOnes } = await imageApi.batchGenerate(diary.id, {
        style: drawStyle,
        custom_style_prompt: drawStyle === 'custom' ? customStyle : undefined,
        paragraphs,
        n: imageCount,
      })
      setCandidates(prev => [...prev, ...newOnes])
      toast.success(`✨ 已生成 ${newOnes.length} 张候选画面`)
    } catch (e: any) {
      toast.error(e?.message ?? '生成失败')
    } finally {
      setGeneratingImages(false)
    }
  }

  const toggleKeep = (id: number) => {
    setKept(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const finishDiary = async () => {
    if (!diary || finishing || leaving || contentMutationPromiseRef.current || pendingPublication) return
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
      const availableImages = images.map(image => ({ id: image.id, url: image.url }))
      setPendingPublication({
        diaryId: diary.id,
        date: diary.date,
        text: capturedText,
        images: availableImages,
        selectedImageIds: availableImages.map(image => image.id),
      })
      toast.success('日记已完成，仍为私密')
    } catch (e: any) {
      toast.error(e?.message ?? '完成日记失败')
    } finally {
      setFinishing(false)
    }
  }

  const publishDiary = async (imageIds: number[]) => {
    if (!pendingPublication || !room || room.state !== 'paired') throw new Error('双人房间尚未就绪')
    await roomsApi.publishDiary(room.id, pendingPublication.diaryId, imageIds)
    toast.success(`已发布给${room.partner?.nickname ?? '对方'}`)
  }

  const handleBack = async () => {
    if (!diary || finishing || leaving || contentMutationPromiseRef.current || pendingPublication) return
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

  if (!diary) {
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
          <div>{diary.date}</div>
          <div className="de-save-state">
            {contentMutationBusy && (rewriting ? '正在改写…' : 'AI 生成中…')}
            {!contentMutationBusy && savingFlag === 'saving' && '保存中…'}
            {!contentMutationBusy && savingFlag === 'saved' && '草稿已保存'}
            {!contentMutationBusy && savingFlag === 'idle' && (diary.status === 'confirmed' ? '已完成' : '私密草稿')}
          </div>
        </div>
        <button className="save-btn pressable" onClick={finishDiary} disabled={editorLocked}>
          {finishing ? '正在完成…' : '完成日记'}
        </button>
      </header>

      {navigationError && <p className="de-navigation-error" role="alert">{navigationError}</p>}

      <fieldset className="de-workspace" disabled={editorLocked}>
        <div className="de-toolbar">
          <button className="tool-btn pressable" onClick={requestAiFill} disabled={contentMutationBusy}>
            {aiFilling ? '✨ 生成中...' : '✨ 一键生成'}
          </button>
          <button className="tool-btn pressable" onClick={captureSelection}>✍️ 改写选中</button>
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

        <section className="de-section">
          <h3>为日记生成画面</h3>
          <div className="de-sub">① 选择段落</div>
          <ParagraphSelector text={text} selected={selectedParagraphs} onChange={setSelectedParagraphs} />

          <div className="de-sub">② 选择风格</div>
          <StyleSelector value={drawStyle} onChange={setDrawStyle} customPrompt={customStyle} onCustomChange={setCustomStyle} />

          <div className="de-sub">③ 生成数量</div>
          <div className="de-count">
            {([1, 2, 4] as const).map(n => (
              <button
                key={n}
                className={`count-chip ${imageCount === n ? 'active' : ''}`}
                onClick={() => setImageCount(n)}
              >{n}</button>
            ))}
          </div>

          <button
            className="generate-images-btn pressable"
            aria-label="生成画面"
            onClick={generateImages}
            disabled={generatingImages}
          >
            {generatingImages ? '🎨 绘制中...' : '✨ 生成画面'}
          </button>
        </section>
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

      <BottomSheet open={showRewriteSheet} onClose={() => setShowRewriteSheet(false)} title="改写选中段落">
        <div className="rewrite-options">
          {REWRITE_OPTIONS.map(o => (
            <button key={o.key} className="rewrite-chip" onClick={() => applyRewrite(o.key)}>
              {o.label}
            </button>
          ))}
          <input
            className="rewrite-custom"
            placeholder="自定义改写要求..."
            value={customRewrite}
            onChange={e => setCustomRewrite(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') applyRewrite('custom') }}
          />
        </div>
      </BottomSheet>

      <PublishSheet
        open={Boolean(pendingPublication)}
        kind="diary"
        title={`${pendingPublication?.date ?? diary.date} 的日记`}
        summary={pendingPublication?.text ?? ''}
        images={pendingPublication?.images ?? []}
        selectedImageIds={pendingPublication?.selectedImageIds ?? []}
        onClose={() => {
          setPendingPublication(null)
          onBack()
        }}
        onConfirm={publishDiary}
      />
    </div>
  )
}
