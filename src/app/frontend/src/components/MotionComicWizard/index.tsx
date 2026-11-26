import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ChevronRight, ImageIcon } from '../Icon'
import PicturebookVideo from '../PicturebookVideo'
import { filmFolderApi } from '../../api/client'
import type {
  CompletedPicturebook,
  MotionComicDraft,
  PicturebookVideoSource,
  ReadablePicturebookPage,
} from '../../types'
import './style.css'

type Loader = () => Promise<CompletedPicturebook[] | { items: CompletedPicturebook[] }>

interface Props {
  sources?: CompletedPicturebook[]
  loadPicturebooks?: Loader
  onBack: () => void
  /** 恢复既有草稿:来源与页序从草稿读,开始后把草稿关联到视频任务。 */
  draftId?: number
  writeSpies?: Record<string, (...args: any[]) => void>
}

type Step = 'source' | 'edit' | 'preview'

function sourceKey(source: CompletedPicturebook): string {
  return `${source.source_kind}-${source.source_id}`
}

function hasCompletePages(source: CompletedPicturebook): boolean {
  if (source.total_pages !== 9) return false
  if (source.ready_pages !== undefined && source.ready_pages < 9) return false

  const pages = new Map(source.pages.map(item => [item.page_index, item]))
  for (let index = 0; index <= 8; index += 1) {
    const page = pages.get(index)
    if (!page?.image_url) return false
  }
  return Array.from({ length: 8 }, (_, offset) => offset + 1).every(index => pages.has(index))
}

function bodyPages(source: CompletedPicturebook): ReadablePicturebookPage[] {
  return source.pages
    .filter(page => page.page_index >= 1 && page.page_index <= 8 && page.image_url)
    .sort((left, right) => left.page_index - right.page_index)
}

function formatDateRange(source: CompletedPicturebook): string {
  return `${source.source_start_date} - ${source.source_end_date}`
}

function normalizeLoaded(result: CompletedPicturebook[] | { items: CompletedPicturebook[] }) {
  return Array.isArray(result) ? result : result.items
}

export default function MotionComicWizard({ sources, loadPicturebooks, onBack, draftId }: Props) {
  const [loadedSources, setLoadedSources] = useState<CompletedPicturebook[]>(sources ?? [])
  const [loading, setLoading] = useState(!sources && Boolean(loadPicturebooks))
  const [error, setError] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [selectedPages, setSelectedPages] = useState<number[]>([])
  const [step, setStep] = useState<Step>('source')
  const [draft, setDraft] = useState<MotionComicDraft | null>(null)
  // 最新写胜出:快速连点时旧响应不得覆盖新页序。
  const saveQueue = useRef(Promise.resolve())

  useEffect(() => {
    if (sources) {
      setLoadedSources(sources)
      setLoading(false)
      return
    }
    if (!loadPicturebooks) return

    let cancelled = false
    setLoading(true)
    setError(null)
    loadPicturebooks()
      .then(result => {
        if (!cancelled) setLoadedSources(normalizeLoaded(result))
      })
      .catch(() => {
        if (!cancelled) setError('绘本暂时加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadPicturebooks, sources])

  const completeSources = useMemo(
    () => loadedSources.filter(hasCompletePages),
    [loadedSources],
  )
  const selectedSource = useMemo(
    () => completeSources.find(source => sourceKey(source) === selectedKey) ?? null,
    [completeSources, selectedKey],
  )
  const pages = useMemo(
    () => selectedSource ? bodyPages(selectedSource) : [],
    [selectedSource],
  )
  const previewPages = useMemo(
    () => selectedPages
      .map(pageIndex => pages.find(page => page.page_index === pageIndex))
      .filter((page): page is ReadablePicturebookPage => Boolean(page)),
    [pages, selectedPages],
  )
  // 正式作品按work 取片，历史任务按 picturebook job 取片。
  const videoSource = useMemo<PicturebookVideoSource | null>(
    () => selectedSource
      ? {
          kind: selectedSource.source_kind === 'canonical_work' ? 'work' : 'job',
          id: selectedSource.source_id,
        }
      : null,
    [selectedSource],
  )

  const completeSourcesForRestore = useMemo(
    () => loadedSources.filter(hasCompletePages),
    [loadedSources],
  )

  // 打开既有草稿:恢复来源与页序,直接进入编辑。
  useEffect(() => {
    if (!draftId || draft) return
    if (!completeSourcesForRestore.length) return
    let cancelled = false
    filmFolderApi.getMotionDraft(draftId)
      .then(saved => {
        if (cancelled) return
        setDraft(saved)
        const key = `${saved.source_kind === 'work' ? 'canonical_work' : 'historical_job'}-${saved.source_id}`
        const matched = completeSourcesForRestore.find(
          source => sourceKey(source) === key,
        )
        if (matched) {
          setSelectedKey(key)
          setSelectedPages(saved.page_sequence)
          setStep('edit')
        }
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [draftId, draft, completeSourcesForRestore])

  const persistSequence = (next: number[]) => {
    if (!draft || draft.video_job_id !== null) return
    const id = draft.id
    saveQueue.current = saveQueue.current
      .catch(() => undefined)
      .then(() => filmFolderApi.updateMotionDraft(id, { page_sequence: next }))
      .then(updated => setDraft(updated))
      .catch(() => undefined)
  }

  // 创建请求在飞期间不允许第二次创建,防止快速连点产生多条草稿。
  const creatingDraftRef = useRef(false)

  const chooseSource = (source: CompletedPicturebook) => {
    const nextPages = bodyPages(source).map(page => page.page_index)
    setSelectedKey(sourceKey(source))
    setSelectedPages(nextPages)
    // 选中来源即创建草稿;页序之后再随编辑自动保存。
    if (!draft && !creatingDraftRef.current) {
      creatingDraftRef.current = true
      const sourceKind = source.source_kind === 'canonical_work' ? 'work' : 'job'
      filmFolderApi.createMotionDraft({
        source_kind: sourceKind,
        source_id: source.source_id,
        title: source.title,
        page_sequence: nextPages,
      })
        .then(created => setDraft(created))
        .catch(() => undefined)
        .finally(() => { creatingDraftRef.current = false })
    }
  }

  const togglePage = (pageIndex: number) => {
    setSelectedPages(current => {
      const next = current.includes(pageIndex)
        ? (current.length <= 1 ? current : current.filter(item => item !== pageIndex))
        : [...current, pageIndex].sort((left, right) => left - right)
      if (next !== current) persistSequence(next)
      return next
    })
  }

  const movePage = (pageIndex: number, direction: -1 | 1) => {
    setSelectedPages(current => {
      const index = current.indexOf(pageIndex)
      const nextIndex = index + direction
      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return current
      const next = [...current]
      const [item] = next.splice(index, 1)
      next.splice(nextIndex, 0, item)
      persistSequence(next)
      return next
    })
  }

  if (loading) {
    return (
      <main className="motion-comic-wizard">
        <button type="button" className="mcw-back" onClick={onBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div className="mcw-state" role="status">正在读取绘本…</div>
      </main>
    )
  }

  if (step === 'preview' && selectedSource) {
    return (
      <main className="motion-comic-wizard">
        <header className="mcw-header">
          <button type="button" className="mcw-back" onClick={() => setStep('edit')} aria-label="返回编辑">
            <ArrowLeft />
          </button>
          <div>
            <h1>漫剧准备</h1>
            <p>{selectedSource.title}</p>
          </div>
        </header>

        <ol className="mcw-preview-list" aria-label="漫剧片段预览">
          {previewPages.map((page, index) => (
            <li className="mcw-preview-item" key={page.page_index}>
              <img
                src={page.image_url ?? ''}
                alt={`序号 ${index + 1}：${page.caption}`}
              />
              <div>
                <span>序号 {index + 1}</span>
                <h2>第 {page.page_index} 页</h2>
                <p>{page.caption}</p>
              </div>
            </li>
          ))}
        </ol>

        <footer className="mcw-footer">
          {videoSource && previewPages.length >= 2 ? (
            <PicturebookVideo
              source={videoSource}
              // 相邻两页配成一段，所以段序完全跟随这里的页序。
              pageIndexes={previewPages.map(page => page.page_index)}
              title={selectedSource.title}
              draftId={draft?.id}
            />
          ) : (
            <p className="mcw-status">
              至少选两页才能接成一段漫剧，回上一步再多选一页。
            </p>
          )}
        </footer>
      </main>
    )
  }

  if (step === 'edit' && selectedSource) {
    return (
      <main className="motion-comic-wizard">
        <header className="mcw-header">
          <button type="button" className="mcw-back" onClick={() => setStep('source')} aria-label="返回选择绘本">
            <ArrowLeft />
          </button>
          <div>
            <h1>漫剧准备</h1>
            <p>{selectedSource.title}</p>
          </div>
        </header>

        <section className="mcw-section" aria-labelledby="mcw-pages-title">
          <h2 id="mcw-pages-title">正文页</h2>
          <div className="mcw-page-grid">
            {pages.map(page => {
              const active = selectedPages.includes(page.page_index)
              const locked = active && selectedPages.length <= 1
              return (
                <button
                  type="button"
                  className={`mcw-page-option${active ? ' active' : ''}`}
                  role="checkbox"
                  aria-checked={active}
                  disabled={locked}
                  key={page.page_index}
                  onClick={() => togglePage(page.page_index)}
                >
                  <img src={page.image_url ?? ''} alt="" />
                  <span className="mcw-page-badge">第 {page.page_index} 页</span>
                  <span>{page.caption}</span>
                </button>
              )
            })}
          </div>
        </section>

        <section className="mcw-section" aria-labelledby="mcw-order-title">
          <h2 id="mcw-order-title">序列</h2>
          <ol className="mcw-order-list" aria-label="已选页面顺序">
            {previewPages.map((page, index) => (
              <li className="mcw-order-item" key={page.page_index}>
                <img src={page.image_url ?? ''} alt="" />
                <div>
                  <span>第 {page.page_index} 页</span>
                  <p>{page.caption}</p>
                </div>
                <div className="mcw-order-actions">
                  <button
                    type="button"
                    aria-label={`将第 ${page.page_index} 页左移`}
                    title={`将第 ${page.page_index} 页左移`}
                    disabled={index === 0}
                    onClick={() => movePage(page.page_index, -1)}
                  >
                    <ArrowLeft />
                  </button>
                  <button
                    type="button"
                    aria-label={`将第 ${page.page_index} 页右移`}
                    title={`将第 ${page.page_index} 页右移`}
                    disabled={index === previewPages.length - 1}
                    onClick={() => movePage(page.page_index, 1)}
                  >
                    <ChevronRight />
                  </button>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <footer className="mcw-footer">
          <button
            type="button"
            className="mcw-primary"
            onClick={() => setStep('preview')}
          >
            预览序列
          </button>
        </footer>
      </main>
    )
  }

  return (
    <main className="motion-comic-wizard">
      <header className="mcw-header">
        <button type="button" className="mcw-back" onClick={onBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div>
          <h1>漫剧准备</h1>
          <p>选择已完成绘本</p>
        </div>
      </header>

      {error && <p className="mcw-error">{error}</p>}
      {completeSources.length === 0 ? (
        <div className="mcw-state" role="status">暂无可用绘本</div>
      ) : (
        <section className="mcw-source-list" aria-label="可用绘本">
          {completeSources.map(source => {
            const active = sourceKey(source) === selectedKey
            return (
              <button
                type="button"
                className={`mcw-source${active ? ' active' : ''}`}
                key={sourceKey(source)}
                data-testid={`source-${sourceKey(source)}`}
                onClick={() => chooseSource(source)}
              >
                {source.cover_url ? (
                  <img src={source.cover_url} alt={`${source.title} 封面`} />
                ) : (
                  <span className="mcw-cover-fallback" aria-hidden="true">
                    <ImageIcon />
                  </span>
                )}
                <span className="mcw-source-copy">
                  <strong>{source.title}</strong>
                  <span>{formatDateRange(source)}</span>
                  <span>{source.style}</span>
                </span>
              </button>
            )
          })}
        </section>
      )}

      <footer className="mcw-footer">
        <button
          type="button"
          className="mcw-primary"
          disabled={!selectedSource}
          onClick={() => setStep('edit')}
        >
          下一步
        </button>
      </footer>
    </main>
  )
}
