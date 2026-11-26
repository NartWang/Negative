import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowLeft, ChevronRight, ImageIcon } from '../Icon'
import type { ReadablePicturebookPage } from '../../types'
import './style.css'

interface PictureBookReaderProps {
  pages: ReadablePicturebookPage[]
  title?: string
  onReloadImage?: (page: ReadablePicturebookPage) => void
}

const DRAG_THRESHOLD_PX = 72

function safeImageSrc(url: string | null): string | null {
  if (!url) return null

  try {
    const parsed = new URL(url, window.location.origin)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return url
    }
  } catch {
    return null
  }

  return null
}

function pageLabel(page: ReadablePicturebookPage, bodyPageCount: number) {
  if (page.page_index === 0) return '封面'
  return `第 ${page.page_index} 页，共 ${bodyPageCount} 页`
}

function imageAlt(page: ReadablePicturebookPage) {
  if (page.caption) return page.caption
  return page.page_index === 0 ? '封面' : `第 ${page.page_index} 页`
}

export default function PictureBookReader({
  pages,
  title = '绘本阅读器',
  onReloadImage,
}: PictureBookReaderProps) {
  const orderedPages = useMemo(
    () => [...pages].sort((left, right) => left.page_index - right.page_index),
    [pages],
  )
  const [currentIndex, setCurrentIndex] = useState(0)
  const dragStartX = useRef<number | null>(null)
  const [imageErrors, setImageErrors] = useState<Record<number, boolean>>({})
  const [reloadVersions, setReloadVersions] = useState<Record<number, number>>({})

  useEffect(() => {
    setCurrentIndex(index => Math.min(index, Math.max(0, orderedPages.length - 1)))
  }, [orderedPages.length])

  useEffect(() => {
    const knownPages = new Set(orderedPages.map(page => page.page_index))
    setImageErrors(errors =>
      Object.fromEntries(
        Object.entries(errors).filter(([pageIndex]) => knownPages.has(Number(pageIndex))),
      ),
    )
  }, [orderedPages])

  const currentPage = orderedPages[currentIndex]
  const bodyPageCount = Math.max(
    orderedPages.filter(page => page.page_index > 0).length,
    ...orderedPages.map(page => page.page_index),
    0,
  )
  const canGoPrevious = currentIndex > 0
  const canGoNext = currentIndex < orderedPages.length - 1

  const goPrevious = () => {
    setCurrentIndex(index => Math.max(0, index - 1))
  }

  const goNext = () => {
    setCurrentIndex(index => Math.min(orderedPages.length - 1, index + 1))
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      goPrevious()
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      goNext()
    }
  }

  const handlePointerUp = (clientX: number) => {
    if (dragStartX.current === null) return

    const distance = clientX - dragStartX.current
    dragStartX.current = null
    if (Math.abs(distance) < DRAG_THRESHOLD_PX) return

    if (distance < 0) {
      goNext()
    } else {
      goPrevious()
    }
  }

  const handleReloadImage = () => {
    if (!currentPage) return

    setImageErrors(errors => ({ ...errors, [currentPage.page_index]: false }))
    setReloadVersions(versions => ({
      ...versions,
      [currentPage.page_index]: (versions[currentPage.page_index] || 0) + 1,
    }))
    onReloadImage?.(currentPage)
  }

  if (!currentPage) {
    return (
      <section className="picturebook-reader picturebook-reader-empty" aria-label={title} role="region">
        <p>还没有可阅读的绘本页。</p>
      </section>
    )
  }

  const safeSrc = safeImageSrc(currentPage.image_url)
  const hasImageError = imageErrors[currentPage.page_index] || !safeSrc
  const reloadVersion = reloadVersions[currentPage.page_index] || 0
  const progressLabel = pageLabel(currentPage, bodyPageCount)

  return (
    <section
      className="picturebook-reader"
      aria-label={title}
      role="region"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className="picturebook-reader-toolbar" aria-live="polite">
        <span className="picturebook-reader-progress">{progressLabel}</span>
      </div>

      <div
        className="picturebook-reader-stage"
        data-testid="picturebook-reader-stage"
        onPointerDown={event => {
          dragStartX.current = event.clientX
        }}
        onPointerCancel={() => {
          dragStartX.current = null
        }}
        onPointerUp={event => handlePointerUp(event.clientX)}
      >
        {safeSrc && !hasImageError ? (
          <img
            key={`${currentPage.page_index}-${reloadVersion}`}
            className="picturebook-reader-image"
            src={safeSrc}
            alt={imageAlt(currentPage)}
            draggable={false}
            onError={() =>
              setImageErrors(errors => ({ ...errors, [currentPage.page_index]: true }))
            }
          />
        ) : (
          <div className="picturebook-reader-image-fallback" role="status">
            <ImageIcon className="picturebook-reader-fallback-icon" />
            <span>图片暂时没有加载出来</span>
            <button
              type="button"
              className="picturebook-reader-reload"
              onClick={handleReloadImage}
              aria-label="重新加载图片"
            >
              <ImageIcon />
            </button>
          </div>
        )}
      </div>

      <p className="picturebook-reader-caption">{currentPage.caption || progressLabel}</p>

      <div className="picturebook-reader-controls">
        <button
          type="button"
          className="picturebook-reader-nav"
          onClick={goPrevious}
          disabled={!canGoPrevious}
          aria-label="上一页"
        >
          <ArrowLeft />
        </button>
        <button
          type="button"
          className="picturebook-reader-nav"
          onClick={goNext}
          disabled={!canGoNext}
          aria-label="下一页"
        >
          <ChevronRight />
        </button>
      </div>
    </section>
  )
}
