import type { StoryChapter } from '../../types'
import './style.css'

interface Props {
  chapters: StoryChapter[]
  onOpenDay?: (date: string) => void
  onOpenRangeWork?: (sourceKind: Extract<StoryChapter, { kind: 'range_work' }>['source_kind'], sourceId: number) => void
}

type StoryChapterContentType = StoryChapter['content_types'][number]
type NormalizedStoryChapter = StoryChapter & {
  displayDate: string
}

const contentLabels: Record<StoryChapterContentType, string> = {
  photo: '照片',
  text: '文字',
  diary: '日记',
  picturebook: '绘本',
  story: '故事',
}

const isoDatePattern = /^\d{4}-\d{2}-\d{2}$/

function isIsoDate(value: unknown): value is string {
  if (typeof value !== 'string' || !isoDatePattern.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function normalizeChapter(chapter: StoryChapter): NormalizedStoryChapter | null {
  const chapterDate = chapter.kind === 'day' ? chapter.date : undefined
  const endDate = isIsoDate(chapter.end_date)
    ? chapter.end_date
    : isIsoDate(chapterDate) ? chapterDate : isIsoDate(chapter.start_date) ? chapter.start_date : null
  if (!endDate) return null
  const startDate = isIsoDate(chapter.start_date) ? chapter.start_date : endDate
  const displayDate = isIsoDate(chapterDate) ? chapterDate : endDate
  return { ...chapter, start_date: startDate, end_date: endDate, displayDate }
}

function formatMonth(monthKey: string): string {
  const [year, month] = monthKey.split('-')
  return `${year}年${Number(month)}月`
}

function formatDay(date: string): string {
  const [, month, day] = date.split('-')
  return `${Number(month)}月${Number(day)}日`
}

function formatChapterDate(chapter: NormalizedStoryChapter): string {
  if (chapter.kind === 'range_work' && chapter.start_date !== chapter.end_date) {
    return `${formatDay(chapter.start_date)} - ${formatDay(chapter.end_date)}`
  }
  return formatDay(chapter.displayDate)
}

function chapterKey(chapter: NormalizedStoryChapter): string {
  if (chapter.kind === 'range_work') return `${chapter.source_kind}-${chapter.source_id}`
  return chapter.displayDate
}

function canOpenChapter(
  chapter: NormalizedStoryChapter,
  onOpenDay?: (date: string) => void,
  onOpenRangeWork?: Props['onOpenRangeWork'],
): boolean {
  if (chapter.kind === 'range_work') return Boolean(onOpenRangeWork)
  return Boolean(onOpenDay)
}

function groupChapters(chapters: StoryChapter[]) {
  const sorted = chapters.flatMap(chapter => {
    const normalized = normalizeChapter(chapter)
    return normalized ? [normalized] : []
  }).sort((a, b) => {
    const byEnd = b.end_date.localeCompare(a.end_date)
    if (byEnd !== 0) return byEnd
    return b.start_date.localeCompare(a.start_date)
  })
  const groups: Array<{ monthKey: string; items: NormalizedStoryChapter[] }> = []

  for (const chapter of sorted) {
    const monthKey = chapter.end_date.slice(0, 7)
    const last = groups[groups.length - 1]
    if (last?.monthKey === monthKey) {
      last.items.push(chapter)
    } else {
      groups.push({ monthKey, items: [chapter] })
    }
  }

  return groups
}

export default function StoryChapterList({ chapters, onOpenDay, onOpenRangeWork }: Props) {
  const groups = groupChapters(chapters)

  return (
    <div className="story-chapter-list">
      {groups.map(group => (
        <section className="story-month-section" key={group.monthKey} aria-labelledby={`story-month-${group.monthKey}`}>
          <div className="story-month-heading">
            <h2 id={`story-month-${group.monthKey}`}>{formatMonth(group.monthKey)}</h2>
            <span>{group.items.length} 章</span>
          </div>

          <div className="story-month-days">
            {group.items.map(chapter => {
              const key = chapterKey(chapter)
              const titleId = `story-chapter-title-${chapter.kind}-${key}`
              const summaryId = `story-chapter-summary-${chapter.kind}-${key}`
              const cardContent = (
                <>
                  <div className="story-chapter-cover" aria-hidden={!chapter.cover_url}>
                    {chapter.cover_url ? (
                      <img src={chapter.cover_url} alt={chapter.title} />
                    ) : (
                      <div className="story-chapter-text-cover">
                        <span>{formatChapterDate(chapter)}</span>
                        <strong>{chapter.title}</strong>
                      </div>
                    )}
                  </div>
                  <div className="story-chapter-body">
                    <time dateTime={chapter.displayDate}>{formatChapterDate(chapter)}</time>
                    <h3 id={titleId}>{chapter.title}</h3>
                    <p id={summaryId}>{chapter.summary}</p>
                    <div className="story-chapter-labels" aria-label="内容类型">
                      {chapter.content_types.map(type => {
                        const label = contentLabels[type] ?? type
                        return label ? <span key={`${type}-${label}`}>{label}</span> : null
                      })}
                    </div>
                  </div>
                </>
              )

              return (
                <article className="story-chapter-card" key={`${chapter.kind}-${key}`}>
                  <div className="story-chapter-surface">
                    {cardContent}
                  </div>
                  {canOpenChapter(chapter, onOpenDay, onOpenRangeWork) && (
                    <button
                      type="button"
                      className="story-chapter-open"
                      onClick={() => {
                        if (chapter.kind === 'range_work') {
                          onOpenRangeWork?.(chapter.source_kind, chapter.source_id)
                        } else {
                          onOpenDay?.(chapter.displayDate)
                        }
                      }}
                      aria-labelledby={titleId}
                      aria-describedby={summaryId}
                    />
                  )}
                </article>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}
