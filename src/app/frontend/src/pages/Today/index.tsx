import { useEffect, useState, useCallback } from 'react'
import { schedulesApi, fragmentsApi, thermometerApi } from '../../api/client'
import type { Schedule, Fragment, Thermometer as ThermometerData } from '../../types'
import { useCurrentDate } from '../../contexts/DateContext'
import { useToast } from '../../contexts/ToastContext'
import { useUser } from '../../contexts/UserContext'
import { recomputeLocal } from '../../utils/thermometer'
import DateBar from '../../components/DateBar'
import Thermometer from '../../components/Thermometer'
import ScheduleCard from '../../components/ScheduleCard'
import FragmentItem from '../../components/FragmentItem'
import EmptyState from '../../components/EmptyState'
import EmptyToday from '../../components/illustrations/EmptyToday'
import './style.css'

interface Props {
  onOpenEditor: (date: string) => void
}

export default function Today({ onOpenEditor }: Props) {
  const { currentDate, isToday } = useCurrentDate()
  const { currentUserId } = useUser()
  const toast = useToast()
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [fragments, setFragments] = useState<Fragment[]>([])
  const [thermo, setThermo] = useState<ThermometerData | null>(null)
  const [quickInput, setQuickInput] = useState('')

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
  }, [currentDate, currentUserId])

  useEffect(() => { reload() }, [reload])

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

  const quickAdd = async () => {
    const text = quickInput.trim()
    if (!text) return
    setQuickInput('')
    try {
      const created = await fragmentsApi.create({ date: currentDate, content: text })
      const next = [...fragments, created]
      applyOptimistic(schedules, next)
      toast.success('已记下')
    } catch { toast.error('保存失败'); setQuickInput(text) }
  }

  const hasContent = schedules.length > 0 || fragments.length > 0
  const sortedFragments = [...fragments].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))

  return (
    <div className="page today-page">
      <DateBar />

      <div className="today-body">
        <Thermometer data={thermo} />

        <section className="section">
          <h2 className="section-title">日程</h2>
          {schedules.length === 0 ? (
            <EmptyState
              illustration={<EmptyToday />}
              title={isToday ? '今天还没有日程' : `${currentDate} 没有日程`}
              description='切到"记录"添加吧'
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
          <div className="quick-input">
            <input
              type="text"
              placeholder="记一笔..."
              value={quickInput}
              onChange={e => setQuickInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && quickAdd()}
            />
            <button onClick={quickAdd} disabled={!quickInput.trim()}>发送</button>
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
    </div>
  )
}
