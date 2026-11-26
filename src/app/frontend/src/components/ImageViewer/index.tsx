import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import SafeImage from '../SafeImage'
import './style.css'

interface Props {
  src: string
  alt?: string
  onClose: () => void
}

export default function ImageViewer({ src, alt = '', onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div
      className="image-viewer-backdrop"
      role="dialog"
      aria-label="完整照片"
      onClick={onClose}
    >
      <SafeImage className="image-viewer-image" src={src} alt={alt} />
      <button
        type="button"
        className="image-viewer-close"
        aria-label="关闭"
        onClick={e => {
          e.stopPropagation()
          onClose()
        }}
      >×</button>
    </div>,
    document.body,
  )
}
