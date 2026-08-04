import { useEffect, useState, useCallback, useRef } from 'react'
import { schedulesApi, fragmentsApi, thermometerApi, uploadApi } from '../../api/client'
import type { Schedule, Fragment, Thermometer as ThermometerData } from '../../types'
import { useCurrentDate } from '../../contexts/DateContext'
import { useToast } from '../../contexts/ToastContext'
import { recomputeLocal } from '../../utils/thermometer'
import DateBar from '../../components/DateBar'
import Thermometer from '../../components/Thermometer'
import CheckinCalendar from '../../components/CheckinCalendar'
import BottomSheet from '../../components/BottomSheet'
import ScheduleCard from '../../components/ScheduleCard'
import FragmentItem from '../../components/FragmentItem'
import EmptyState from '../../components/EmptyState'
import EmptyToday from '../../components/illustrations/EmptyToday'
import './style.css'

interface Props {
  onOpenEditor: (date: string) => void
}

const MOODS = [
  { key: 'happy', emoji: '😊', label: '开心' },
  { key: 'calm', emoji: '😌', label: '平静' },
  { key: 'sad', emoji: '😢', label: '难过' },
  { key: 'anxious', emoji: '😰', label: '焦虑' },
  { key: 'angry', emoji: '😤', label: '生气' },
]

export default function Today({ onOpenEditor }: Props) {
  const { currentDate, isToday } = useCurrentDate()
  const toast = useToast()
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [fragments, setFragments] = useState<Fragment[]>([])
  const [thermo, setThermo] = useState<ThermometerData | null>(null)
  const [showAddSchedule, setShowAddSchedule] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newTime, setNewTime] = useState('')
  const [fragmentInput, setFragmentInput] = useState('')
  const [moodTag, setMoodTag] = useState<string | null>(null)
  const [pendingPhoto, setPendingPhoto] = useState<{ url: string; description: string | null } | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const reload = useCallback(async () => {
    try {
      const [s, f, t] = await Promise.all([
        schedulesApi.list(currentDate),
        fragmentsApi.list(currentDate),
        thermometerApi.get(currentDate),
      ])
      setSchedules(s); setFragments(f); setThermo(t)
    } catch {
      toast.error('加载失败，请重试')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentDate])

  useEffect(() => { reload() }, [reload])

  const addSchedule = async () => {
    const title = newTitle.trim()
    if (!title) return
    try {
      const created = await schedulesApi.create({
        date: currentDate,
        title,
        time: newTime || undefined,
      })
      const next = [...schedules, created]
      applyOptimistic(next, fragments)
      setNewTitle('')
      setNewTime('')
      setShowAddSchedule(false)
      toast.success('日程已添加')
    } catch { toast.error('添加失败') }
  }

  // Recompute the quantitative part locally after any mutation; preserve AI score.
  const applyOptimistic = (nextSchedules: Schedule[], nextFragments: Fragment[]) => {
    setSchedules(nextSchedules)
    setFragments(nextFragments)
    setThermo(prev => (prev ? recomputeLocal(prev, nextSchedules, nextFragments) : prev))
  }

  const toggleSchedule = async (id: number, completed: boolean) => {
    const snapshot = schedules
    const next = schedules.map(s => s.id === id ? { ...s, completed } : s)
    applyOptimistic(next, fragments)
    try {
      await schedulesApi.update(id, { completed })
      toast.success(completed ? '完成 ✓' : '已取消勾选')
    } catch {
      applyOptimistic(snapshot, fragments)
      toast.error('更新失败')
    }
  }

  const updateSchedule = async (id: number, data: { title?: string; time?: string; feeling?: string }) => {
    try { await schedulesApi.update(id, data); toast.success('已保存'); reload() }
    catch { toast.error('保存失败') }
  }

  const deleteSchedule = async (id: number) => {
    const snapshot = schedules
    const next = schedules.filter(s => s.id !== id)
    applyOptimistic(next, fragments)
    try { await schedulesApi.delete(id); toast.success('已删除') }
    catch { applyOptimistic(snapshot, fragments); toast.error('删除失败') }
  }

  const updateFragment = async (id: number, data: { content?: string; mood_tag?: string }) => {
    try {
      const updated = await fragmentsApi.update(id, data)
      const next = fragments.map(f => f.id === id ? updated : f)
      applyOptimistic(schedules, next)
      toast.success('已保存')
    } catch {
      toast.error('保存失败')
    }
  }

  const deleteFragment = async (id: number) => {
    const snapshot = fragments
    const next = fragments.filter(f => f.id !== id)
    applyOptimistic(schedules, next)
    try { await fragmentsApi.delete(id); toast.success('已删除') }
    catch { applyOptimistic(schedules, snapshot); toast.error('删除失败') }
  }

  const handlePhoto = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const result = await uploadApi.upload(file)
      setPendingPhoto({ url: result.url, description: result.photo_description })
      toast.success('图片已附加')
    } catch { toast.error('上传失败') }
    finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const addFragment = async () => {
    const content = fragmentInput.trim()
    if (!content && !pendingPhoto) return
    try {
      const created = await fragmentsApi.create({
        date: currentDate,
        content: content || undefined,
        photo_url: pendingPhoto?.url,
        photo_description: pendingPhoto?.description || undefined,
        mood_tag: moodTag || undefined,
      })
      const next = [...fragments, created]
      applyOptimistic(schedules, next)
      setFragmentInput('')
      setMoodTag(null)
      setPendingPhoto(null)
      toast.success('已记下')
    } catch { toast.error('保存失败') }
  }

  const hasContent = schedules.length > 0 || fragments.length > 0
  const sortedFragments = [...fragments].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))

  return (
    <div className="page today-page">
      <DateBar />

      <div className="today-body">
        <header className="private-record-intro">
          <span>PRIVATE JOURNAL</span>
          <h1>记录，只属于我</h1>
          <p>日程、碎片和草稿默认私密；只有你主动确认发布的快照，才会进入「我们」。</p>
        </header>

        <section className="section record-calendar-section">
          <h2 className="section-title">打卡</h2>
          <CheckinCalendar />
        </section>

        <Thermometer data={thermo} />

        <section className="section">
          <div className="section-header">
            <h2 className="section-title">日程</h2>
            <button className="add-btn pressable" onClick={() => setShowAddSchedule(true)} aria-label="添加日程">+</button>
          </div>
          {schedules.length === 0 ? (
            <EmptyState
              illustration={<EmptyToday />}
              title={isToday ? '今天还没有日程' : `${currentDate} 没有日程`}
              description="点右上角添加第一项"
            />
          ) : (
            <div className="schedule-list">
              {schedules.map(s => (
                <ScheduleCard
                  key={s.id}
                  schedule={s}
                  onToggle={toggleSchedule}
                  onUpdate={updateSchedule}
                  onDelete={deleteSchedule}
                />
              ))}
            </div>
          )}
        </section>

        <section className="section">
          <h2 className="section-title">碎片</h2>
          <div className="fragment-form">
            <textarea
              aria-label="记录此刻的碎片"
              placeholder="此刻的想法…"
              value={fragmentInput}
              onChange={event => setFragmentInput(event.target.value)}
              rows={3}
            />
            {pendingPhoto && (
              <div className="pending-photo">
                <img src={pendingPhoto.url} alt="待记录的照片" />
                <button className="remove-photo-btn" onClick={() => setPendingPhoto(null)} aria-label="移除图片">×</button>
              </div>
            )}
            <div className="fragment-toolbar">
              <div className="mood-selector" aria-label="选择心情">
                {MOODS.map(mood => (
                  <button
                    key={mood.key}
                    className={`mood-btn ${moodTag === mood.key ? 'active' : ''}`}
                    onClick={() => setMoodTag(moodTag === mood.key ? null : mood.key)}
                    aria-label={mood.label}
                    aria-pressed={moodTag === mood.key}
                  >{mood.emoji}</button>
                ))}
              </div>
              <button
                className="photo-btn"
                aria-label="添加照片"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >{uploading ? '上传中' : '照片'}</button>
              <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handlePhoto} />
            </div>
            <button
              className="submit-btn"
              onClick={addFragment}
              disabled={!fragmentInput.trim() && !pendingPhoto}
            >记下这一刻</button>
          </div>
          <div className="fragment-list">
            {sortedFragments.map(f => (
              <FragmentItem
                key={f.id}
                fragment={f}
                onUpdate={updateFragment}
                onDelete={deleteFragment}
              />
            ))}
          </div>
        </section>

        {hasContent && (
          <button className="generate-btn pressable" onClick={() => onOpenEditor(currentDate)}>
            ✨ {isToday ? '生成今日日记' : `打开 ${currentDate} 的日记`}
          </button>
        )}
      </div>

      <BottomSheet open={showAddSchedule} onClose={() => setShowAddSchedule(false)} title="添加日程">
        <div className="add-sched-form">
          <label htmlFor="schedule-time">时间</label>
          <input id="schedule-time" type="time" value={newTime} onChange={event => setNewTime(event.target.value)} />
          <label htmlFor="schedule-title">标题</label>
          <input
            id="schedule-title"
            type="text"
            placeholder="日程内容"
            value={newTitle}
            onChange={event => setNewTitle(event.target.value)}
            onKeyDown={event => event.key === 'Enter' && addSchedule()}
          />
          <button className="btn-primary" onClick={addSchedule} disabled={!newTitle.trim()}>添加</button>
        </div>
      </BottomSheet>
    </div>
  )
}
