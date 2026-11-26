import { useState } from 'react'
import type { Fragment, FragmentUpdatePayload } from '../../types'
import { fragmentClockTime, readableClockTime } from '../../utils/recordTime'
import FragmentEditorSheet from '../FragmentEditorSheet'
import ImageViewer from '../ImageViewer'
import SafeImage from '../SafeImage'
import { Pencil } from '../Icon'
import './style.css'

interface Props {
  fragment: Fragment
  onUpdate: (id: number, data: FragmentUpdatePayload) => Promise<void>
  onDelete: (id: number) => Promise<void>
}

export default function FragmentItem({ fragment, onUpdate, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [viewing, setViewing] = useState(false)
  const clockTime = fragmentClockTime(fragment)

  return (
    <article className="fragment-item">
      <div className="fragment-time-col">
        <span className="fragment-time-period">{readableClockTime(clockTime).split(' ')[0]}</span>
        <span className="fragment-time">{readableClockTime(clockTime).split(' ')[1] ?? clockTime}</span>
      </div>
      <div className="fragment-body">
        {fragment.content && <p className="fragment-text">{fragment.content}</p>}
        {fragment.photo_url && (
          <button
            type="button"
            className="fragment-photo-btn"
            aria-label="查看完整照片"
            onClick={() => setViewing(true)}
          >
            <SafeImage
              src={fragment.photo_url}
              alt={fragment.photo_description ?? '随记照片'}
              className="fragment-photo-preview"
            />
          </button>
        )}
        <button
          type="button"
          className="fragment-edit-btn"
          aria-label="编辑随记"
          onClick={() => setEditing(true)}
        ><Pencil /></button>
      </div>

      {viewing && fragment.photo_url && (
        <ImageViewer
          src={fragment.photo_url}
          alt={fragment.photo_description ?? '随记照片'}
          onClose={() => setViewing(false)}
        />
      )}

      <FragmentEditorSheet
        open={editing}
        fragment={fragment}
        onClose={() => setEditing(false)}
        onUpdate={onUpdate}
        onDelete={onDelete}
      />
    </article>
  )
}
