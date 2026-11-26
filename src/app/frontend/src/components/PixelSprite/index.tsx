import { useEffect, useState } from 'react'
import './style.css'

interface Props {
  src?: string | null
  alt: string
  className?: string
  /** Eager-load the hero sprite; grids stay lazy. */
  eager?: boolean
}

/**
 * Renders a Q-pixel character sprite. Falls back to a neutral silhouette when the
 * asset is missing or fails to load, so a broken image never reaches the user.
 */
export default function PixelSprite({ src, alt, className = '', eager = false }: Props) {
  const [failed, setFailed] = useState(false)

  useEffect(() => { setFailed(false) }, [src])

  if (!src || failed) {
    return (
      <span className={`pixel-sprite pixel-sprite-empty ${className}`} role="img" aria-label={alt}>
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="8" r="4" />
          <path d="M20 21a8 8 0 0 0-16 0" />
        </svg>
      </span>
    )
  }

  return (
    <img
      className={`pixel-sprite ${className}`}
      src={src}
      alt={alt}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      onError={() => setFailed(true)}
    />
  )
}
