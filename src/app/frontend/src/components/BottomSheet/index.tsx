import { ReactNode, useEffect } from 'react'
import { createPortal } from 'react-dom'
import './style.css'

interface Props {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
}

export default function BottomSheet({ open, onClose, title, children }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div className="bs-backdrop fade-in" onClick={onClose}>
      <div
        className="bs-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={e => e.stopPropagation()}
      >
        <div className="bs-handle" />
        {title && <div className="bs-title">{title}</div>}
        <div className="bs-body">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
