import { useCallback, useEffect, useRef, useState } from 'react'
import { diaryApi } from '../../api/client'
import type { Diary, DiaryNotebookIndexEntry } from '../../types'
import SafeImage from '../../components/SafeImage'
import ImageViewer from '../../components/ImageViewer'
import { parseLocalDate, weekdayLabel } from '../../utils/date'
import './style.css'

export function nearestNotebookIndex(
  items: DiaryNotebookIndexEntry[],
  targetDate: string,
): number {
  if (items.length === 0) return -1
  const target = parseLocalDate(targetDate).getTime()
  let best = 0
  let bestDistance = Infinity
  for (let i = 0; i < items.length; i += 1) {
    const distance = Math.abs(parseLocalDate(items[i].date).getTime() - target)
    // Strict `<`: items are sorted date ASC, so equal distance keeps the
    // earlier (lower-index, earlier-date) entry.
    if (distance < bestDistance) {
      bestDistance = distance
      best = i
    }
  }
  return best
}

interface Props {
  initialDate: string
  onBack: () => void
}

const DAY_MS = 24 * 60 * 60 * 1000

function formatPageDate(date: string): string {
  const d = parseLocalDate(date)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${weekdayLabel(d)}`
}

export default function DiaryNotebook({ initialDate, onBack }: Props) {
  const [items, setItems] = useState<DiaryNotebookIndexEntry[]>([])
  const [total, setTotal] = useState(0)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [cache, setCache] = useState<Record<number, Diary>>({})
  const [indexLoading, setIndexLoading] = useState(true)
  const [indexError, setIndexError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [viewerSrc, setViewerSrc] = useState<string | null>(null)
  const [turnDirection, setTurnDirection] = useState<'next' | 'prev' | null>(null)

  const indexGenerationRef = useRef(0)
  const detailGenerationRef = useRef(0)
  const cacheRef = useRef<Record<number, Diary>>({})
  const itemsRef = useRef<DiaryNotebookIndexEntry[]>([])
  const touchStartRef = useRef<{ x: number; y: number } | null>(null)

  const fetchDetail = useCallback(async (id: number): Promise<Diary> => {
    const cached = cacheRef.current[id]
    if (cached) return cached
    const detail = await diaryApi.notebookDetail(id)
    cacheRef.current = { ...cacheRef.current, [id]: detail }
    setCache(cacheRef.current)
    return detail
  }, [])

  const prefetchNeighbors = useCallback((index: number, list: DiaryNotebookIndexEntry[]) => {
    const neighborIds = [index - 1, index + 1]
      .map(i => list[i]?.diary_id)
      .filter((id): id is number => typeof id === 'number')
      .filter(id => !cacheRef.current[id])
    if (neighborIds.length === 0) return
    // Prefetch failures must never affect the current page.
    void Promise.allSettled(neighborIds.map(id => fetchDetail(id)))
  }, [fetchDetail])

  const loadDetail = useCallback(async (index: number, list: DiaryNotebookIndexEntry[]) => {
    const item = list[index]
    if (!item) return
    const generation = ++detailGenerationRef.current
    setDetailError(null)
    if (cacheRef.current[item.diary_id]) {
      setCache({ ...cacheRef.current })
      prefetchNeighbors(index, list)
      return
    }
    setDetailLoading(true)
    try {
      await fetchDetail(item.diary_id)
      if (detailGenerationRef.current !== generation) return
      setDetailLoading(false)
      prefetchNeighbors(index, list)
    } catch {
      if (detailGenerationRef.current !== generation) return
      setDetailLoading(false)
      setDetailError('这篇日记暂时打不开，请重试')
    }
  }, [fetchDetail, prefetchNeighbors])

  const loadIndex = useCallback(async () => {
    const generation = ++indexGenerationRef.current
    setIndexLoading(true)
    setIndexError(null)
    try {
      const result = await diaryApi.notebookIndex()
      if (indexGenerationRef.current !== generation) return
      setItems(result.items)
      itemsRef.current = result.items
      setTotal(result.total)
      setIndexLoading(false)
      if (result.items.length > 0) {
        const startIndex = nearestNotebookIndex(result.items, initialDate)
        setActiveIndex(startIndex)
        void loadDetail(startIndex, result.items)
      }
    } catch {
      if (indexGenerationRef.current !== generation) return
      setIndexLoading(false)
      setIndexError('日记本暂时打不开，请重试')
    }
  }, [initialDate, loadDetail])

  useEffect(() => {
    void loadIndex()
  }, [loadIndex])

  const turnPage = useCallback((delta: -1 | 1) => {
    const list = itemsRef.current
    const next = activeIndex + delta
    if (next < 0 || next >= list.length) return
    setTurnDirection(delta === 1 ? 'next' : 'prev')
    setActiveIndex(next)
    void loadDetail(next, list)
  }, [activeIndex, loadDetail])

  const retryDetail = useCallback(() => {
    if (activeIndex < 0) return
    // Drop the failed id so the retry always re-fetches.
    const id = itemsRef.current[activeIndex]?.diary_id
    if (id !== undefined && cacheRef.current[id]) {
      const { [id]: _dropped, ...rest } = cacheRef.current
      cacheRef.current = rest
      setCache(rest)
    }
    void loadDetail(activeIndex, itemsRef.current)
  }, [activeIndex, loadDetail])

  const onTouchStart = (e: React.TouchEvent) => {
    const touch = e.touches[0]
    touchStartRef.current = { x: touch.clientX, y: touch.clientY }
  }

  const onTouchEnd = (e: React.TouchEvent) => {
    const start = touchStartRef.current
    touchStartRef.current = null
    if (!start) return
    const touch = e.changedTouches[0]
    const dx = touch.clientX - start.x
    const dy = touch.clientY - start.y
    if (Math.abs(dx) < 48 || Math.abs(dx) <= Math.abs(dy) * 1.4) return
    // Left swipe (dx < 0) → later page; right swipe → earlier page.
    turnPage(dx < 0 ? 1 : -1)
  }

  const activeEntry = activeIndex >= 0 ? items[activeIndex] : null
  const activeDiary = activeEntry ? cache[activeEntry.diary_id] : undefined
  const keptImages = (activeDiary?.images ?? []).filter(image => image.kept === 1)

  const renderPageBody = () => {
    if (detailError) {
      return (
        <div className="notebook-error" role="alert">
          <p>{detailError}</p>
          <button type="button" className="notebook-retry-btn" onClick={retryDetail}>
            重试
          </button>
        </div>
      )
    }
    if (detailLoading || !activeDiary) {
      return <p className="notebook-loading">翻页中…</p>
    }
    return (
      <>
        <h2 className="notebook-page-date">{formatPageDate(activeDiary.date)}</h2>
        <p className="notebook-page-text">{activeDiary.text}</p>
        {keptImages.length > 0 && (
          <div className="notebook-page-images">
            {keptImages.map(image => (
              <button
                key={image.id}
                type="button"
                className="notebook-page-image-btn"
                aria-label="查看完整照片"
                onClick={() => setViewerSrc(image.url)}
              >
                <SafeImage
                  className="notebook-page-image"
                  src={image.url}
                  alt=""
                />
              </button>
            ))}
          </div>
        )}
      </>
    )
  }

  return (
    <div className="notebook-page-shell">
      <header className="notebook-header">
        <button
          type="button"
          className="notebook-back-btn"
          aria-label="返回记录页"
          onClick={onBack}
        >
          ← 返回
        </button>
        <div className="notebook-title-group">
          <h1 className="notebook-title">我的日记本</h1>
          {!indexLoading && !indexError && total > 0 && (
            <span className="notebook-total">共 {total} 篇</span>
          )}
        </div>
        <span className="notebook-header-side" aria-hidden="true" />
      </header>

      {indexError ? (
        <div className="notebook-error notebook-index-error" role="alert">
          <p>{indexError}</p>
          <button type="button" className="notebook-retry-btn" onClick={() => void loadIndex()}>
            重试
          </button>
        </div>
      ) : indexLoading ? (
        <p className="notebook-loading">加载中…</p>
      ) : items.length === 0 ? (
        <div className="notebook-empty">
          <p className="notebook-empty-title">还没有正式日记</p>
          <p className="notebook-empty-hint">回到记录页，写下并确认你的第一篇日记吧</p>
          <button type="button" className="notebook-retry-btn" onClick={onBack}>
            回到记录页
          </button>
        </div>
      ) : (
        <>
          <div
            className="notebook-book"
            onTouchStart={onTouchStart}
            onTouchEnd={onTouchEnd}
          >
            <div className="notebook-coil" aria-hidden="true">
              {Array.from({ length: 12 }, (_, i) => (
                <span key={i} className="notebook-coil-ring" />
              ))}
            </div>
            <article
              key={activeEntry?.diary_id ?? 'page'}
              className={`notebook-paper${turnDirection ? ` notebook-turn-${turnDirection}` : ''}`}
              onAnimationEnd={() => setTurnDirection(null)}
            >
              {renderPageBody()}
            </article>
          </div>

          <footer className="notebook-footer">
            <button
              type="button"
              className="notebook-turn-btn"
              onClick={() => turnPage(-1)}
              disabled={activeIndex <= 0}
            >
              前一篇
            </button>
            <span className="notebook-indicator">第 {activeIndex + 1} / {total} 篇</span>
            <button
              type="button"
              className="notebook-turn-btn"
              onClick={() => turnPage(1)}
              disabled={activeIndex < 0 || activeIndex >= items.length - 1}
            >
              后一篇
            </button>
          </footer>
        </>
      )}

      {viewerSrc && (
        <ImageViewer src={viewerSrc} alt="日记照片" onClose={() => setViewerSrc(null)} />
      )}
    </div>
  )
}
