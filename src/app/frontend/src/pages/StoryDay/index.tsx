import { useEffect, useMemo, useRef, useState } from 'react'
import { exportApi, storyApi } from '../../api/client'
import PublishSheet from '../../components/PublishSheet'
import VisibilitySheet from '../../components/VisibilitySheet'
import { ArrowLeft, Download, Eye } from '../../components/Icon'
import { downloadBlob } from '../../utils/downloadBlob'
import type {
  CompletedPicturebook,
  Diary,
  ReadablePicturebookPage,
  StoryDayDetail,
  StoryDayTimelineEntry,
  StoryWork,
  StoryWorkAsset,
} from '../../types'
import './style.css'

interface Props {
  date: string
  onBack: () => void
  onOpenPicturebook?: (title: string, pages: ReadablePicturebookPage[]) => void
}

const CONTENT_LABELS: Record<StoryDayDetail['content_types'][number], string> = {
  photo: '照片',
  text: '文字',
  diary: '日记',
  picturebook: '绘本',
  story: '故事',
}

const MEDIUM_LABELS: Record<StoryWork['medium'], string> = {
  picture_book: '绘本',
  comic: '漫画',
  motion_comic: '漫剧',
  weekly: '周度故事',
}

function formatDate(date: string): string {
  const [year, month, day] = date.split('-')
  return `${year}年${Number(month)}月${Number(day)}日`
}

function textAsset(assets: StoryWorkAsset[]): StoryWorkAsset | undefined {
  return assets.find(asset => asset.asset_type === 'text' && asset.text)
}

function firstImageAsset(assets: StoryWorkAsset[]): StoryWorkAsset | undefined {
  return assets.find(asset => asset.asset_type === 'image' && asset.url)
}

function diaryBody(diary: Diary): string {
  return diary.status === 'draft'
    ? (diary.draft_text || diary.text)
    : (diary.text || diary.draft_text || '')
}

function usesDraftText(diary: Diary): boolean {
  return diary.status === 'draft' || (!diary.text && Boolean(diary.draft_text))
}

function PicturebookSummary({
  book,
  onOpenPicturebook,
}: {
  book: CompletedPicturebook
  onOpenPicturebook?: (title: string, pages: ReadablePicturebookPage[]) => void
}) {
  const pages = [...book.pages].sort((a, b) => a.page_index - b.page_index)
  const cover = pages.find(page => page.page_index === 0) ?? pages[0]
  const title = book.title || cover?.caption || `${book.total_pages || pages.length} 页绘本`
  const pageCount = book.total_pages || pages.length
  const openBook = () => {
    if (pages.length === 0) return
    onOpenPicturebook?.(title, pages)
  }

  return (
    <article className="story-day-picturebook" aria-label={`绘本 ${title}`}>
      <button
        type="button"
        className="story-day-picturebook-cover-button"
        onClick={openBook}
        disabled={!onOpenPicturebook || pages.length === 0}
        aria-label={`打开绘本 ${title}`}
      >
        {cover?.image_url ? (
          <img className="story-day-picturebook-cover" src={cover.image_url} alt={title} />
        ) : (
          <div className="story-day-picturebook-cover empty" aria-hidden="true">{title.slice(0, 2)}</div>
        )}
      </button>
      <div className="story-day-picturebook-body">
        <span>完成绘本</span>
        <h3>{title}</h3>
        <p>{pageCount} 页 · {book.style || '绘本'}</p>
        <button
          type="button"
          onClick={openBook}
          disabled={!onOpenPicturebook || pages.length === 0}
        >
          打开绘本
        </button>
      </div>
    </article>
  )
}

function TimelineItem({ item }: { item: StoryDayTimelineEntry }) {
  const clockLabel = item.clock || '未定'
  const dateTime = item.clock ? `${item.date}T${item.clock}` : item.date

  if (item.kind === 'schedule') {
    return (
      <li className="story-day-timeline-item">
        <time dateTime={dateTime}>{clockLabel}</time>
        <div>
          <span className="story-day-item-kind">日程</span>
          <h3>{item.title}</h3>
          <p>{item.completed ? '已完成' : '未完成'}{item.feeling ? ` · ${item.feeling}` : ''}</p>
        </div>
      </li>
    )
  }

  const imageAlt = item.content || '片段照片'
  return (
    <li className="story-day-timeline-item">
      <time dateTime={dateTime}>{clockLabel}</time>
      <div>
        <span className="story-day-item-kind">片段</span>
        {item.content && <p className="story-day-fragment-text">{item.content}</p>}
        {item.photo_url && <img className="story-day-fragment-photo" src={item.photo_url} alt={imageAlt} />}
        {item.mood_tag && <span className="story-day-mood">{item.mood_tag}</span>}
      </div>
    </li>
  )
}

function WorkSummary({
  work,
  onVisibility,
  onPublish,
}: {
  work: StoryWork
  onVisibility: (work: StoryWork, trigger: HTMLButtonElement) => void
  onPublish: (work: StoryWork, trigger: HTMLButtonElement) => void
}) {
  const text = textAsset(work.assets)
  const image = firstImageAsset(work.assets)

  return (
    <article className={`story-day-work ${image ? '' : 'no-image'}`} aria-label={`故事作品 ${work.title}`}>
      {image?.url && <img src={image.url} alt={work.title} />}
      <div className="story-day-work-main">
        <span>{MEDIUM_LABELS[work.medium] ?? work.medium} · {work.style}</span>
        <h3>{work.title}</h3>
        {text?.text && <p>{text.text}</p>}
      </div>
      {work.status === 'ready' && (
        <button
          type="button"
          className="story-day-publish"
          onClick={event => onPublish(work, event.currentTarget)}
        >
          发布到回响
        </button>
      )}
      {work.status === 'published' && (
        <button
          type="button"
          className="story-day-visibility"
          onClick={event => onVisibility(work, event.currentTarget)}
        >
          <Eye />
          已发布 · 可见范围
        </button>
      )}
    </article>
  )
}

export default function StoryDay({ date, onBack, onOpenPicturebook }: Props) {
  const [detail, setDetail] = useState<StoryDayDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [visibilityWork, setVisibilityWork] = useState<StoryWork | null>(null)
  const [publishWork, setPublishWork] = useState<StoryWork | null>(null)
  const visibilityTriggerRef = useRef<HTMLButtonElement | null>(null)
  const publishTriggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    storyApi.day(date)
      .then(result => {
        if (!cancelled) setDetail(result)
      })
      .catch(() => {
        if (!cancelled) setError('暂时没有读到这一天的故事')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [date])

  const timeline = useMemo(() => detail?.timeline ?? [], [detail])

  const openVisibility = (work: StoryWork, trigger: HTMLButtonElement) => {
    visibilityTriggerRef.current = trigger
    setVisibilityWork(work)
  }

  const closeVisibility = () => {
    setVisibilityWork(null)
    window.setTimeout(() => visibilityTriggerRef.current?.focus(), 0)
  }

  const openPublish = (work: StoryWork, trigger: HTMLButtonElement) => {
    publishTriggerRef.current = trigger
    setPublishWork(work)
  }

  const closePublish = () => {
    setPublishWork(null)
    window.setTimeout(() => publishTriggerRef.current?.focus(), 0)
  }

  const handlePublished = (workId: number, status: 'ready' | 'published') => {
    setDetail(current =>
      current
        ? {
            ...current,
            story_works: current.story_works.map(item =>
              item.id === workId ? { ...item, status } : item),
          }
        : current,
    )
  }

  const exportDayPdf = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const blob = await exportApi.downloadDayPdf(date)
      downloadBlob(blob, `zhiji-${date}.pdf`)
    } catch {
      setExportError('导出失败，请稍后再试')
    } finally {
      setExporting(false)
    }
  }

  if (loading) {
    return (
      <main className="story-day-page">
        <button type="button" className="story-day-back" onClick={onBack} aria-label="返回故事列表">
          <ArrowLeft />
        </button>
        <div className="story-day-state" role="status">正在读取这一天…</div>
      </main>
    )
  }

  if (error || !detail) {
    return (
      <main className="story-day-page">
        <button type="button" className="story-day-back" onClick={onBack} aria-label="返回故事列表">
          <ArrowLeft />
        </button>
        <div className="story-day-state error" role="alert">
          <strong>{error ?? '故事不存在'}</strong>
          <button type="button" onClick={onBack}>回到故事列表</button>
        </div>
      </main>
    )
  }

  return (
    <main className="story-day-page">
      <header className="story-day-hero">
        <div className="story-day-topbar">
          <button type="button" className="story-day-back" onClick={onBack} aria-label="返回故事列表">
            <ArrowLeft />
          </button>
          <button
            type="button"
            className="story-day-export"
            onClick={exportDayPdf}
            disabled={exporting}
            aria-label="导出这一天为 PDF"
          >
            <Download />
            {exporting ? '导出中' : '导出 PDF'}
          </button>
        </div>
        {detail.cover_url ? (
          <img className="story-day-cover" src={detail.cover_url} alt={detail.title} />
        ) : (
          <div className="story-day-cover empty" aria-hidden="true">{formatDate(detail.date)}</div>
        )}
        <div className="story-day-hero-copy">
          <time dateTime={detail.date}>{formatDate(detail.date)}</time>
          <h1>{detail.title}</h1>
          <p>{detail.summary}</p>
          <div className="story-day-labels" aria-label="内容类型">
            {detail.content_types.map(type => (
              <span key={type}>{CONTENT_LABELS[type] ?? type}</span>
            ))}
          </div>
          {exportError && <p className="story-day-export-error" role="alert">{exportError}</p>}
        </div>
      </header>

      <section className="story-day-section" aria-labelledby="story-day-timeline-title">
        <div className="story-day-section-heading">
          <p>DAYLINE</p>
          <h2 id="story-day-timeline-title">当天时间线</h2>
        </div>
        {timeline.length === 0 ? (
          <p className="story-day-empty">这一天还没有可整理的时间线。</p>
        ) : (
          <ol className="story-day-timeline" aria-label="当天时间线">
            {timeline.map(item => (
              <TimelineItem key={`${item.kind}-${item.id}-${item.clock}`} item={item} />
            ))}
          </ol>
        )}
      </section>

      <section className="story-day-section" aria-labelledby="story-day-diary-title">
        <div className="story-day-section-heading">
          <p>DIARY</p>
          <h2 id="story-day-diary-title">日记</h2>
        </div>
        {detail.diaries.length === 0 ? (
          <p className="story-day-empty">这一天还没有确认日记。</p>
        ) : detail.diaries.map(diary => (
          <article className="story-day-diary" key={diary.id} aria-label={`日记 ${diary.date}`}>
            <div>
              <time dateTime={diary.date}>{formatDate(diary.date)}</time>
              {usesDraftText(diary) && <span>草稿</span>}
            </div>
            <p>{diaryBody(diary)}</p>
          </article>
        ))}
      </section>

      <section className="story-day-section" aria-labelledby="story-day-picturebook-title">
        <div className="story-day-section-heading">
          <p>PICTUREBOOK</p>
          <h2 id="story-day-picturebook-title">绘本</h2>
        </div>
        {detail.picturebooks.length === 0 ? (
          <p className="story-day-empty">这一天还没有完成绘本。</p>
        ) : detail.picturebooks.map(book => (
          <PicturebookSummary
            key={`${book.source_kind}-${book.source_id}`}
            book={book}
            onOpenPicturebook={onOpenPicturebook}
          />
        ))}
      </section>

      <section className="story-day-section" aria-labelledby="story-day-works-title">
        <div className="story-day-section-heading">
          <p>WORKS</p>
          <h2 id="story-day-works-title">故事作品</h2>
        </div>
        {detail.story_works.length === 0 ? (
          <p className="story-day-empty">这一天还没有可分享作品。</p>
        ) : detail.story_works.map(work => (
          <WorkSummary
            key={work.id}
            work={work}
            onVisibility={openVisibility}
            onPublish={openPublish}
          />
        ))}
      </section>

      <PublishSheet
        open={Boolean(publishWork)}
        work={publishWork}
        onClose={closePublish}
        onPublished={state => handlePublished(state.id, state.status)}
      />
      {visibilityWork?.status === 'published' && (
        <VisibilitySheet
          open={Boolean(visibilityWork)}
          work={visibilityWork}
          onClose={closeVisibility}
        />
      )}
    </main>
  )
}
