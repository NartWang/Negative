import { ReactNode, useEffect } from 'react'
import './style.css'

interface Props {
  open: boolean
  onClose: () => void
  title?: string
  description?: string
  confirmText?: string
  cancelText?: string
  onConfirm?: () => void
  danger?: boolean
  children?: ReactNode
}

export default function Modal({
  open,
  onClose,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  onConfirm,
  danger,
  children,
}: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="modal-backdrop fade-in" onClick={onClose}>
      <div className="modal-card pop" onClick={e => e.stopPropagation()}>
        {title && <div className="modal-title">{title}</div>}
        {description && <div className="modal-desc">{description}</div>}
        {children}
        {onConfirm && (
          <div className="modal-actions">
            <button className="modal-btn modal-btn-secondary" onClick={onClose}>
              {cancelText}
            </button>
            <button
              className={`modal-btn ${danger ? 'modal-btn-danger' : 'modal-btn-primary'}`}
              onClick={() => {
                onConfirm()
                onClose()
              }}
            >
              {confirmText}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
