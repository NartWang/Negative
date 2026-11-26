import { useCallback, useEffect, useRef, useState } from 'react'
import type { WeeklyComic } from '../../types'
import { storyApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import Modal from '../Modal'
import WorkSaveSheet from '../WorkSaveSheet'
import './style.css'

interface Props {
  comic: WeeklyComic | null
  onClose: () => void
  onRetry: () => void
  onShare: () => void
  onDelete: () => void
  readOnly?: boolean
}

export default function ResultModal({ comic, onClose, onRetry, onShare, onDelete, readOnly = false }: Props) {
  const toast = useToast()
  const [showWorkSave, setShowWorkSave] = useState(false)
  const saveButtonRef = useRef<HTMLButtonElement>(null)
  const restoreSaveFocus = useCallback(() => {
    saveButtonRef.current?.focus()
  }, [])
  useEffect(() => setShowWorkSave(false), [comic?.id])
  if (!comic) return null

  const saveStoryDraft = async () => {
    await storyApi.createWork({
      source_diary_id: null,
      source_weekly_comic_ids: [comic.id],
      selected_segments: [comic.caption || `${comic.week_start} — ${comic.week_end}`],
      medium: 'weekly',
      narrative_mode: 'true_record',
      style: comic.style || 'weekly',
      title: comic.caption || `${comic.week_start} — ${comic.week_end}`,
    })
    toast.success('已保存到故事，可继续整理成周度连载')
  }

  return (
    <>
      {!showWorkSave && <Modal open={true} onClose={onClose} title={comic.caption || '本周漫画'}>
        <img className="wc-result-img" src={comic.url} alt={comic.caption || ''} />
        <div className="wc-result-meta">
          {comic.week_start} — {comic.week_end}
        </div>
        {!readOnly && (
          <div className="wc-result-actions">
            <button ref={saveButtonRef} className="wc-btn wc-btn-primary" onClick={() => setShowWorkSave(true)}>
              保存到故事
            </button>
            <button className="wc-btn wc-btn-secondary" onClick={onRetry}>重新生成</button>
            <button className="wc-btn wc-btn-secondary" onClick={onShare}>保存分享</button>
            <button className="wc-btn wc-btn-danger" onClick={onDelete}>删除</button>
          </div>
        )}
      </Modal>}
      <WorkSaveSheet
        open={showWorkSave}
        kind="weekly_comic"
        title={`${comic.week_start} — ${comic.week_end}`}
        summary={comic.caption || '这一周，我把日子折叠成一张画。'}
        images={[{ id: comic.id, url: comic.url, alt: comic.caption || '本周漫画' }]}
        onClose={() => setShowWorkSave(false)}
        onConfirm={saveStoryDraft}
        onRestoreFocus={restoreSaveFocus}
      />
    </>
  )
}
