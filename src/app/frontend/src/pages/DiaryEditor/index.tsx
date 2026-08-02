import { useEffect, useRef, useState, useCallback } from 'react'
import { diaryApi, imageApi } from '../../api/client'
import type { Diary, DiaryImage, DrawStyle, EmotionMode, RewriteDirection } from '../../types'
import { useToast } from '../../contexts/ToastContext'
import BottomSheet from '../../components/BottomSheet'
import Modal from '../../components/Modal'
import ParagraphSelector from '../../components/ParagraphSelector'
import StyleSelector from '../../components/StyleSelector'
import ImageCandidates from '../../components/ImageCandidates'
import SendLetter from '../../components/SendLetter'
import './style.css'

interface Props {
  date: string
  onBack: () => void
}

const REWRITE_OPTIONS: { key: RewriteDirection; label: string }[] = [
  { key: 'warmer',  label: '更温暖' },
  { key: 'humor',   label: '更幽默' },
  { key: 'concise', label: '更简洁' },
  { key: 'poetic',  label: '更诗意' },
  { key: 'custom',  label: '自定义' },
]

export default function DiaryEditor({ date, onBack }: Props) {
  const toast = useToast()
  const [diary, setDiary] = useState<Diary | null>(null)
  const [text, setText] = useState('')
  const [savingFlag, setSavingFlag] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [aiFilling, setAiFilling] = useState(false)
  const [showOverwriteModal, setShowOverwriteModal] = useState(false)
  const [showRewriteSheet, setShowRewriteSheet] = useState(false)
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [customRewrite, setCustomRewrite] = useState('')
  const [emotionMode, setEmotionMode] = useState<EmotionMode>(
    (localStorage.getItem('emotionMode') as EmotionMode) || 'warm'
  )

  const [selectedParagraphs, setSelectedParagraphs] = useState<number[]>([])
  const [drawStyle, setDrawStyle] = useState<DrawStyle>(
    (localStorage.getItem('drawStyle') as DrawStyle) || 'ghibli'
  )
  const [customStyle, setCustomStyle] = useState(localStorage.getItem('customDraw') || '')
  const [imageCount, setImageCount] = useState<1 | 2 | 4>(4)
  const [candidates, setCandidates] = useState<DiaryImage[]>([])
  const [kept, setKept] = useState<number[]>([])
  const [generatingImages, setGeneratingImages] = useState(false)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const saveTimerRef = useRef<number | null>(null)

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
    if (text === (diary.draft_text ?? diary.text ?? '')) return
    setSavingFlag('saving')
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        const updated = await diaryApi.update(diary.id, { draft_text: text, text })
        setDiary(updated)
        setSavingFlag('saved')
        window.setTimeout(() => setSavingFlag('idle'), 1200)
      } catch {
        toast.error('草稿保存失败')
        setSavingFlag('idle')
      }
    }, 600)
    return () => { if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current) }
  }, [text, diary, toast])

  const requestAiFill = useCallback(() => {
    if (text.trim() && diary) {
      setShowOverwriteModal(true)
    } else {
      doAiFill()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, diary])

  const doAiFill = async () => {
    if (!diary) return
    setShowOverwriteModal(false)
    setAiFilling(true)
    try {
      const updated = await diaryApi.aiFill(diary.id, { emotion_mode: emotionMode })
      setDiary(updated)
      setText(updated.draft_text ?? updated.text ?? '')
      toast.success('✨ AI 已为你写好初稿')
    } catch (e: any) {
      toast.error(e?.message?.includes('当天没有') ? '当天没有任何记录，无法生成' : 'AI 生成失败')
    } finally {
      setAiFilling(false)
    }
  }

  const captureSelection = () => {
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
    if (!diary || !selection) return
    setShowRewriteSheet(false)
    const payload: { paragraph: string; direction: RewriteDirection; custom_prompt?: string } = {
      paragraph: selection.text,
      direction,
    }
    if (direction === 'custom') payload.custom_prompt = customRewrite
    try {
      const result = await diaryApi.aiRewrite(diary.id, payload)
      const before = text.slice(0, selection.start)
      const after = text.slice(selection.end)
      setText(before + result.rewritten + after)
      toast.success('✨ 已改写')
    } catch {
      toast.error('改写失败')
    } finally {
      setSelection(null)
    }
  }

  const generateImages = async () => {
    if (!diary) return
    const t = (diary.draft_text || diary.text || text).trim()
    if (!t) { toast.error('先写点内容再生成画面'); return }
    const paragraphs = (() => {
      const all = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean)
      if (selectedParagraphs.length === 0) return [] // whole diary
      return selectedParagraphs.map(i => all[i]).filter(Boolean)
    })()
    setGeneratingImages(true)
    try {
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

  const saveAndClose = async () => {
    if (!diary) return
    try {
      // flush latest text + confirm + keep selected images
      await diaryApi.update(diary.id, { text, draft_text: text, status: 'confirmed' })
      await imageApi.keep(diary.id, kept)
      toast.success('📖 今日日记已收入日记本')
      onBack()
    } catch (e: any) {
      toast.error(e?.message ?? '保存失败')
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
        <button className="back-btn" onClick={onBack}>← 返回</button>
        <div className="de-date">
          <div>{diary.date}</div>
          <div className="de-save-state">
            {savingFlag === 'saving' && '保存中…'}
            {savingFlag === 'saved' && '已保存'}
            {savingFlag === 'idle' && (diary.status === 'confirmed' ? '已收入日记本' : '草稿')}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {diary.status === 'confirmed' && (
            <SendLetter
              type="diary"
              id={diary.id}
              title={`📖 ${diary.date} 的家书`}
              body={text || diary.text || ''}
              onSent={(sentAt) => setDiary(d => d ? { ...d, last_sent_at: sentAt } : d)}
            />
          )}
          <button className="save-btn pressable" onClick={saveAndClose}>保存</button>
        </div>
      </header>

      <div className="de-toolbar">
        <button className="tool-btn pressable" onClick={requestAiFill} disabled={aiFilling}>
          {aiFilling ? '✨ 生成中...' : '✨ 一键生成'}
        </button>
        <button className="tool-btn pressable" onClick={captureSelection}>✍️ 改写选中</button>
      </div>

      <textarea
        ref={textareaRef}
        className="de-textarea"
        value={text}
        onChange={e => setText(e.target.value)}
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

        <button className="generate-images-btn pressable" onClick={generateImages} disabled={generatingImages}>
          {generatingImages ? '🎨 绘制中...' : '✨ 生成画面'}
        </button>
      </section>

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
    </div>
  )
}
