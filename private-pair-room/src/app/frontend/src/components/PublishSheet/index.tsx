import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useRoom } from '../../contexts/RoomContext'
import './style.css'

export interface PublishPreviewImage {
  id: number
  url: string
  alt?: string
}

interface Props {
  open: boolean
  kind: 'diary' | 'weekly_comic'
  title: string
  summary: string
  images: PublishPreviewImage[]
  selectedImageIds?: number[]
  onClose: () => void
  onConfirm: (imageIds: number[]) => Promise<void> | void
  onRestoreFocus?: () => void
}

const EMPTY_SELECTION: number[] = []

export default function PublishSheet({
  open,
  kind,
  title,
  summary,
  images,
  selectedImageIds,
  onClose,
  onConfirm,
  onRestoreFocus,
}: Props) {
  const { room } = useRoom()
  const headingId = useId()
  const initialSelection = selectedImageIds ?? EMPTY_SELECTION
  const [selected, setSelected] = useState<number[]>(initialSelection)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const paired = room?.state === 'paired' && Boolean(room.partner)

  useEffect(() => {
    if (!open) return
    setSelected(initialSelection)
    setPublishing(false)
    setError(null)
  }, [open, initialSelection])

  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const focusTimer = window.setTimeout(() => cancelRef.current?.focus(), 0)
    return () => {
      window.clearTimeout(focusTimer)
      window.setTimeout(() => {
        if (onRestoreFocus) onRestoreFocus()
        else if (previousFocus?.isConnected) previousFocus.focus()
      }, 0)
    }
  }, [open, onRestoreFocus])

  useEffect(() => {
    if (!open) return
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !publishing) {
        event.preventDefault()
        event.stopPropagation()
        event.stopImmediatePropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [])].filter(element => !element.hasAttribute('hidden'))
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !dialogRef.current?.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !dialogRef.current?.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleKey, true)
    return () => window.removeEventListener('keydown', handleKey, true)
  }, [open, publishing, onClose])

  if (!open) return null

  const toggleImage = (id: number) => {
    setSelected(current => current.includes(id)
      ? current.filter(imageId => imageId !== id)
      : [...current, id])
  }

  const confirm = async () => {
    if (!paired || publishing) return
    setPublishing(true)
    setError(null)
    try {
      const exactSelection = images
        .filter(image => selected.includes(image.id))
        .map(image => image.id)
      await onConfirm(kind === 'diary' ? exactSelection : [])
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发布失败，请稍后重试')
      setPublishing(false)
    }
  }

  return createPortal(
    <div className="publish-backdrop" onClick={() => !publishing && onClose()}>
      <section
        ref={dialogRef}
        className="publish-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onClick={event => event.stopPropagation()}
      >
        <div className="publish-handle" aria-hidden="true" />
        <div className="publish-kicker">只分享这一次</div>
        <h2 id={headingId}>发布给{room?.partner?.nickname ?? '对方'}</h2>
        {!paired && (
          <p className="publish-warning" role="status">先与对方建立双人房间，才能发布。</p>
        )}

        <div className="publish-preview">
          <div className="publish-preview-meta">
            <span>{kind === 'diary' ? '日记' : '一周漫画'}</span>
            <strong>{title}</strong>
          </div>
          <p>{summary || '（暂无文字）'}</p>
          {images.length > 0 && (
            <div className={`publish-images ${kind === 'weekly_comic' ? 'single' : ''}`}>
              {images.map((image, index) => {
                const checked = kind === 'weekly_comic' || selected.includes(image.id)
                if (kind === 'weekly_comic') {
                  return <img key={image.id} src={image.url} alt={image.alt ?? title} />
                }
                return (
                  <label key={image.id} className={`publish-image-choice ${checked ? 'selected' : ''}`}>
                    <img src={image.url} alt={image.alt ?? `日记画面 ${index + 1}`} />
                    <input
                      type="checkbox"
                      aria-label={`选择画面 ${index + 1}`}
                      checked={checked}
                      onChange={() => toggleImage(image.id)}
                    />
                    <span aria-hidden="true">{checked ? '✓' : ''}</span>
                  </label>
                )
              })}
            </div>
          )}
        </div>

        <p className="publish-privacy">
          {kind === 'diary'
            ? '日记仍默认私密；只有这次确认的文字与画面会进入「我们」。'
            : '原漫画仍保存在你的回忆里；确认后，对方会在「我们」看到这张快照。'}
        </p>
        {error && <p className="publish-error" role="alert">{error}</p>}
        <div className="publish-actions">
          <button ref={cancelRef} type="button" className="publish-cancel" onClick={onClose} disabled={publishing}>
            暂不分享
          </button>
          <button type="button" className="publish-confirm" onClick={confirm} disabled={!paired || publishing}>
            {publishing ? '正在发布…' : '确认发布'}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  )
}
