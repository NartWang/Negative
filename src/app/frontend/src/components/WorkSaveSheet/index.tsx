import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import './style.css'

export interface WorkSaveImage {
  id: number
  url: string
  asset_id?: string | null
  alt?: string
}

interface Props {
  open: boolean
  kind: 'diary' | 'weekly_comic'
  title: string
  summary: string
  images: WorkSaveImage[]
  selectedImageIds?: number[]
  onClose: () => void
  onConfirm: (imageIds: number[]) => Promise<void> | void
  onRestoreFocus?: () => void
}

const EMPTY_SELECTION: number[] = []

export default function WorkSaveSheet({
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
  const headingId = useId()
  const initialSelection = selectedImageIds ?? EMPTY_SELECTION
  const [selected, setSelected] = useState<number[]>(initialSelection)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    setSelected(initialSelection)
    setSaving(false)
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
      if (event.key === 'Escape' && !saving) {
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
  }, [open, saving, onClose])

  if (!open) return null

  const toggleImage = (id: number) => {
    setSelected(current => current.includes(id)
      ? current.filter(imageId => imageId !== id)
      : [...current, id])
  }

  const confirm = async () => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const exactSelection = images
        .filter(image => selected.includes(image.id) && image.asset_id)
        .map(image => image.id)
      await onConfirm(kind === 'diary' ? exactSelection : [])
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存失败，请稍后重试')
      setSaving(false)
    }
  }

  return createPortal(
    <div className="work-save-backdrop" onClick={() => !saving && onClose()}>
      <section
        ref={dialogRef}
        className="work-save-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onClick={event => event.stopPropagation()}
      >
        <div className="work-save-handle" aria-hidden="true" />
        <div className="work-save-kicker">保存作品</div>
        <h2 id={headingId}>放入故事架</h2>

        <div className="work-save-preview">
          <div className="work-save-preview-meta">
            <span>{kind === 'diary' ? '日记作品' : '周度故事'}</span>
            <strong>{title}</strong>
          </div>
          <p>{summary || '暂无文字'}</p>
          {images.length > 0 && (
            <div className={`work-save-images ${kind === 'weekly_comic' ? 'single' : ''}`}>
              {images.map((image, index) => {
                const disabled = kind === 'diary' && !image.asset_id
                const checked = kind === 'weekly_comic' || selected.includes(image.id)
                if (kind === 'weekly_comic') {
                  return <img key={image.id} src={image.url} alt={image.alt ?? title} />
                }
                return (
                  <label
                    key={image.id}
                    className={`work-save-image-choice ${checked ? 'selected' : ''} ${disabled ? 'disabled' : ''}`}
                  >
                    <img src={image.url} alt={image.alt ?? `日记画面 ${index + 1}`} />
                    <input
                      type="checkbox"
                      aria-label={disabled ? `画面 ${index + 1} 暂不可作为作品素材` : `选择画面 ${index + 1}`}
                      checked={checked && !disabled}
                      disabled={disabled}
                      onChange={() => toggleImage(image.id)}
                    />
                    <span aria-hidden="true">{checked && !disabled ? '✓' : ''}</span>
                    {disabled && <em>需重新生成后可加入作品</em>}
                  </label>
                )
              })}
            </div>
          )}
        </div>

        <p className="work-save-note">
          作品会先保存在你的故事架，默认仅自己可见。保存后可以单独设置可见范围。
        </p>
        {error && <p className="work-save-error" role="alert">{error}</p>}
        <div className="work-save-actions">
          <button ref={cancelRef} type="button" className="work-save-cancel" onClick={onClose} disabled={saving}>
            暂不保存
          </button>
          <button type="button" className="work-save-confirm" onClick={confirm} disabled={saving}>
            {saving ? '正在保存' : '保存到故事'}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  )
}
