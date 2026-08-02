import { useState, useEffect, useCallback, useRef } from 'react'
import { schedulesApi, fragmentsApi, uploadApi } from '../../api/client'
import type { Schedule, Fragment } from '../../types'
import { useCurrentDate } from '../../contexts/DateContext'
import { useToast } from '../../contexts/ToastContext'
import DateBar from '../../components/DateBar'
import ScheduleCard from '../../components/ScheduleCard'
import FragmentItem from '../../components/FragmentItem'
import CheckinCalendar from '../../components/CheckinCalendar'
import BottomSheet from '../../components/BottomSheet'
import './style.css'

const MOODS = [
  { key: 'happy', emoji: '😊' },
  { key: 'calm', emoji: '😌' },
  { key: 'sad', emoji: '😢' },
  { key: 'anxious', emoji: '😰' },
  { key: 'angry', emoji: '😤' },
]

export default function Record() {
  const { currentDate } = useCurrentDate()
  const toast = useToast()
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [fragments, setFragments] = useState<Fragment[]>([])
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
      const [s, f] = await Promise.all([
        schedulesApi.list(currentDate),
        fragmentsApi.list(currentDate),
      ])
      setSchedules(s); setFragments(f)
    } catch { toast.error('加载失败') }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentDate])

  useEffect(() => { reload() }, [reload])

  const addSchedule = async () => {
    const title = newTitle.trim()
    if (!title) return
    try {
      const created = await schedulesApi.create({ date: currentDate, title, time: newTime || undefined })
      setSchedules(prev => [...prev, created])
      setNewTitle(''); setNewTime(''); setShowAddSchedule(false)
      toast.success('日程已添加')
    } catch { toast.error('添加失败') }
  }

  const toggleSchedule = async (id: number, completed: boolean) => {
    const snap = schedules
    setSchedules(prev => prev.map(s => s.id === id ? { ...s, completed } : s))
    try { await schedulesApi.update(id, { completed }) }
    catch { setSchedules(snap); toast.error('更新失败') }
  }

  const updateSchedule = async (id: number, data: { title?: string; time?: string; feeling?: string }) => {
    try { await schedulesApi.update(id, data); toast.success('已保存'); reload() }
    catch { toast.error('保存失败') }
  }

  const deleteSchedule = async (id: number) => {
    const snap = schedules
    setSchedules(prev => prev.filter(s => s.id !== id))
    try { await schedulesApi.delete(id); toast.success('已删除') }
    catch { setSchedules(snap); toast.error('删除失败') }
  }

  const handlePhoto = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
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
      setFragments(prev => [...prev, created])
      setFragmentInput(''); setMoodTag(null); setPendingPhoto(null)
      toast.success('已记下')
    } catch { toast.error('保存失败') }
  }

  const updateFragment = async (id: number, data: { content?: string; mood_tag?: string }) => {
    try { const updated = await fragmentsApi.update(id, data); setFragments(prev => prev.map(f => f.id === id ? updated : f)); toast.success('已保存') }
    catch { toast.error('保存失败') }
  }

  const deleteFragment = async (id: number) => {
    const snap = fragments
    setFragments(prev => prev.filter(f => f.id !== id))
    try { await fragmentsApi.delete(id); toast.success('已删除') }
    catch { setFragments(snap); toast.error('删除失败') }
  }

  const sortedFragments = [...fragments].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))

  return (
    <div className="page record-page">
      <DateBar />

      <div className="record-body">
        <section className="section">
          <h2 className="section-title">打卡</h2>
          <CheckinCalendar />
        </section>

        <section className="section">
          <div className="section-header">
            <h2 className="section-title">日程</h2>
            <button className="add-btn pressable" onClick={() => setShowAddSchedule(true)} aria-label="添加日程">+</button>
          </div>

          {schedules.length === 0 ? (
            <p className="muted">还没有日程，点击右上角 + 添加。</p>
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
              placeholder="此刻的想法..."
              value={fragmentInput}
              onChange={e => setFragmentInput(e.target.value)}
              rows={3}
            />
            {pendingPhoto && (
              <div className="pending-photo">
                <img src={pendingPhoto.url} alt="" />
                <button className="remove-photo-btn" onClick={() => setPendingPhoto(null)} aria-label="移除图片">×</button>
              </div>
            )}
            <div className="fragment-toolbar">
              <div className="mood-selector">
                {MOODS.map(m => (
                  <button
                    key={m.key}
                    className={`mood-btn ${moodTag === m.key ? 'active' : ''}`}
                    onClick={() => setMoodTag(moodTag === m.key ? null : m.key)}
                  >{m.emoji}</button>
                ))}
              </div>
              <button
                className="photo-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >{uploading ? '⏳' : '📷'}</button>
              <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handlePhoto}/>
            </div>
            <button
              className="submit-btn"
              onClick={addFragment}
              disabled={!fragmentInput.trim() && !pendingPhoto}
            >记录</button>
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
      </div>

      <BottomSheet open={showAddSchedule} onClose={() => setShowAddSchedule(false)} title="添加日程">
        <div className="add-sched-form">
          <label>时间</label>
          <input type="time" value={newTime} onChange={e => setNewTime(e.target.value)} />
          <label>标题</label>
          <input
            type="text"
            placeholder="日程内容"
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addSchedule()}
            autoFocus
          />
          <button className="btn-primary" onClick={addSchedule} disabled={!newTitle.trim()}>添加</button>
        </div>
      </BottomSheet>
    </div>
  )
}
