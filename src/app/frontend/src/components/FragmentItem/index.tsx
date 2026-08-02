import { useState } from 'react'
import type { Fragment } from '../../types'
import BottomSheet from '../BottomSheet'
import { relativeTime } from '../../utils/relativeTime'
import './style.css'

const MOOD_EMOJI: Record<string, string> = {
  happy: '😊', calm: '😌', sad: '😢', anxious: '😰', angry: '😤',
}

interface Props {
  fragment: Fragment
  onUpdate: (id: number, data: { content?: string; mood_tag?: string }) => void
  onDelete: (id: number) => void
}

export default function FragmentItem({ fragment, onUpdate, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(fragment.content ?? '')

  return (
    <>
      <button className="fragment-item pressable" onClick={() => setEditing(true)}>
        <div className="fragment-meta">
          {fragment.mood_tag && (
            <span className="mood-emoji">{MOOD_EMOJI[fragment.mood_tag] || '💭'}</span>
          )}
          <span className="fragment-time">{relativeTime(fragment.created_at)}</span>
        </div>
        <div className="fragment-content">
          {fragment.content && <p>{fragment.content}</p>}
          {fragment.photo_url && (
            <img src={fragment.photo_url} alt="" className="fragment-photo" />
          )}
        </div>
      </button>

      <BottomSheet open={editing} onClose={() => setEditing(false)} title="编辑碎片">
        <div className="frag-edit">
          <textarea value={text} onChange={e => setText(e.target.value)} rows={4} placeholder="想法..."/>
          <div className="frag-edit-actions">
            <button className="btn-danger" onClick={() => { onDelete(fragment.id); setEditing(false) }}>删除</button>
            <button
              className="btn-primary"
              onClick={() => { onUpdate(fragment.id, { content: text.trim() }); setEditing(false) }}
              disabled={!text.trim()}
            >保存</button>
          </div>
        </div>
      </BottomSheet>
    </>
  )
}
