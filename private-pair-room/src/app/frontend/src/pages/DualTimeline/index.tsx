import { useEffect, useMemo, useState, useCallback } from 'react'
import type { DualTimelinePayload, TimelineEvent, DrawStyle, DualTimelineComic } from '../../types'
import { dualTimelineApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import { useCurrentDate } from '../../contexts/DateContext'
import { getLocalDateStr, addDays, weekdayLabel, parseLocalDate } from '../../utils/date'
import SummaryBar from '../../components/DualTimeline/SummaryBar'
import TimelineColumn, { eventKey } from '../../components/DualTimeline/TimelineColumn'
import StyleSheet from '../../components/DualTimeline/StyleSheet'
import ResultModal from '../../components/DualTimeline/ResultModal'
import './style.css'

const MAX_SELECT = 6

interface Props {
  userId?: number
  onBack: () => void
}

export default function DualTimeline({ userId, onBack }: Props) {
  const toast = useToast()
  const { currentDate, setCurrentDate } = useCurrentDate()
  const [date, setDate] = useState(currentDate)
  const [data, setData] = useState<DualTimelinePayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [showStyle, setShowStyle] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [showResult, setShowResult] = useState<DualTimelineComic | null>(null)
  const [lastStyle, setLastStyle] = useState<{ style: DrawStyle; custom_style_prompt?: string } | null>(null)

  const load = useCallback(async (d: string) => {
    setLoading(true)
    try {
      const payload = await dualTimelineApi.get(d)
      setData(payload)
      setSelected(new Set())
    } catch {
      toast.error('加载失败')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => { load(date) }, [load, date])

  const toggleEvent = (side: 'a' | 'b', e: TimelineEvent) => {
    setSelected(prev => {
      const k = eventKey(side, e)
      const next = new Set(prev)
      if (next.has(k)) {
        next.delete(k)
      } else {
        if (next.size >= MAX_SELECT) {
          toast.info(`最多选 ${MAX_SELECT} 个时刻`)
          return prev
        }
        next.add(k)
      }
      return next
    })
  }

  const selectedEvents = useMemo(() => {
    const a: TimelineEvent[] = []
    const b: TimelineEvent[] = []
    if (!data) return { a, b }
    for (const e of data.events_a) {
      if (selected.has(eventKey('a', e))) a.push(e)
    }
    for (const e of data.events_b) {
      if (selected.has(eventKey('b', e))) b.push(e)
    }
    return { a, b }
  }, [data, selected])

  const totalSelected = selectedEvents.a.length + selectedEvents.b.length

  const goPrev = () => setDate(d => addDays(d, -1))
  const goNext = () => setDate(d => addDays(d, 1))
  const goToday = () => setDate(getLocalDateStr())

  // Sync DateContext on close so other tabs reflect the date the user navigated to.
  const handleBack = () => {
    setCurrentDate(date)
    onBack()
  }

  const submitGenerate = async (args: { style: DrawStyle; custom_style_prompt?: string }) => {
    if (!data) return
    setLastStyle(args)
    setGenerating(true)
    toast.info('正在画两个人的同一天，30-60 秒…')
    try {
      const c = await dualTimelineApi.generate({
        date: data.date,
        selected_a: selectedEvents.a,
        selected_b: selectedEvents.b,
        style: args.style,
        custom_style_prompt: args.custom_style_prompt,
      })
      setShowStyle(false)
      setShowResult(c)
      toast.success('生成完成 ✨')
    } catch (e) {
      toast.error((e as Error)?.message || '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const retry = async () => {
    if (!lastStyle) return
    setShowResult(null)
    await submitGenerate(lastStyle)
  }

  const share = () => toast.info('长按图片可保存到相册分享 ✨')

  const remove = async () => {
    if (!showResult) return
    const id = showResult.id
    setShowResult(null)
    try { await dualTimelineApi.delete(id); toast.success('已删除') }
    catch { toast.error('删除失败') }
  }

  const canSelectMore = totalSelected < MAX_SELECT

  return (
    <div className="page dt-page">
      <header className="dt-header">
        <button className="dt-back pressable" onClick={handleBack} aria-label="返回">‹</button>
        <div className="dt-header-mid">
          <div className="dt-header-title">双时间线</div>
          <div className="dt-header-date">
            <button className="dt-date-arrow" onClick={goPrev}>‹</button>
            <span>{date} · {weekdayLabel(parseLocalDate(date))}</span>
            <button className="dt-date-arrow" onClick={goNext}>›</button>
            {date !== getLocalDateStr() && (
              <button className="dt-today-btn" onClick={goToday}>今天</button>
            )}
          </div>
        </div>
      </header>

      <SummaryBar summary={data?.summary ?? null} loading={loading} />

      <div className="dt-columns">
        <TimelineColumn
          title={data?.user_a.nickname || '我'}
          side="left"
          events={data?.events_a ?? []}
          selectedIds={selected}
          onToggle={(e) => toggleEvent('a', e)}
          canSelectMore={canSelectMore}
        />
        <div className="dt-divider" />
        <TimelineColumn
          title={data?.user_b?.nickname || '家人'}
          side="right"
          events={data?.events_b ?? []}
          selectedIds={selected}
          onToggle={(e) => toggleEvent('b', e)}
          canSelectMore={canSelectMore}
        />
      </div>

      <div className="dt-sticky-bar">
        <div className="dt-sticky-count">已选 {totalSelected}/{MAX_SELECT}</div>
        <button
          className="dt-sticky-btn pressable"
          disabled={totalSelected === 0 || generating}
          onClick={() => setShowStyle(true)}
        >
          把这些时刻变成一张漫画 ▸
        </button>
      </div>

      <StyleSheet
        userId={userId}
        open={showStyle}
        onClose={() => setShowStyle(false)}
        generating={generating}
        onSubmit={submitGenerate}
        selectedCount={totalSelected}
      />

      <ResultModal
        comic={showResult}
        onClose={() => setShowResult(null)}
        onRetry={retry}
        onShare={share}
        onDelete={remove}
      />
    </div>
  )
}
