import { useState } from 'react'
import type { Schedule } from '../../types'
import BottomSheet from '../BottomSheet'
import './style.css'

interface Props {
  schedule: Schedule
  onToggle: (id: number, completed: boolean) => void
  onUpdate: (id: number, data: { title?: string; time?: string; feeling?: string }) => void
  onDelete: (id: number) => void
}

export default function ScheduleCard({ schedule, onToggle, onUpdate, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(schedule.title)
  const [time, setTime] = useState(schedule.time ?? '')
  const [feeling, setFeeling] = useState(schedule.feeling ?? '')

  const save = () => {
    onUpdate(schedule.id, { title: title.trim(), time: time || undefined, feeling: feeling.trim() || undefined })
    setEditing(false)
  }

  return (
    <>
      <div className={`schedule-card pressable ${schedule.completed ? 'completed' : ''}`}>
        <button
          className="check-btn"
          onClick={(e) => { e.stopPropagation(); onToggle(schedule.id, !schedule.completed) }}
          aria-label={schedule.completed ? '标记未完成' : '标记完成'}
        >
          {schedule.completed ? '✅' : '⬜'}
        </button>
        <button className="schedule-content" onClick={() => setEditing(true)}>
          <div className="schedule-title">
            {schedule.time && <span className="schedule-time">{schedule.time}</span>}
            {schedule.title}
          </div>
          {schedule.feeling && (
            <div className="schedule-feeling">💭 {schedule.feeling}</div>
          )}
        </button>
      </div>

      <BottomSheet open={editing} onClose={() => setEditing(false)} title="编辑日程">
        <div className="sched-edit">
          <label>时间</label>
          <input type="time" value={time} onChange={e => setTime(e.target.value)} />
          <label>标题</label>
          <input type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="日程内容"/>
          <label>感受</label>
          <textarea value={feeling} onChange={e => setFeeling(e.target.value)} rows={2} placeholder="此刻的感受..."/>
          <div className="sched-edit-actions">
            <button className="btn-danger" onClick={() => { onDelete(schedule.id); setEditing(false) }}>删除</button>
            <button className="btn-primary" onClick={save} disabled={!title.trim()}>保存</button>
          </div>
        </div>
      </BottomSheet>
    </>
  )
}
