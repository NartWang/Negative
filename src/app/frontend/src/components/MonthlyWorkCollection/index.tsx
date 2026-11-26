import type { FilmFolderItem } from '../../types'
import { Trash2 } from '../Icon'
import './style.css'

export interface MonthlyWorkCollectionProps {
  items: FilmFolderItem[]
  /** 卡片点击回调;绘本传 source 键,漫剧传 video_job_id。 */
  onOpen: (item: FilmFolderItem) => void
  onDelete?: (item: FilmFolderItem) => void
  onPublish?: (item: FilmFolderItem) => void
  publishingId?: number | null
  emptyHint: string
}

interface MonthGroup {
  month: string
  items: FilmFolderItem[]
}

export function groupByMonth(items: FilmFolderItem[]): MonthGroup[] {
  const groups = new Map<string, FilmFolderItem[]>()
  for (const item of items) {
    const month = item.display_end_date.slice(0, 7)
    const bucket = groups.get(month)
    if (bucket) bucket.push(item)
    else groups.set(month, [item])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a < b ? 1 : -1))
    .map(([month, group]) => ({
      month,
      items: [...group].sort((a, b) => {
        if (a.completed_at !== b.completed_at) {
          return a.completed_at < b.completed_at ? 1 : -1
        }
        return b.id - a.id
      }),
    }))
}

export function formatItemDate(item: FilmFolderItem): string {
  if (item.display_start_date === item.display_end_date) {
    return item.display_start_date
  }
  return `${item.display_start_date} ~ ${item.display_end_date}`
}

export function formatMonthLabel(month: string): string {
  const [year, m] = month.split('-')
  return `${year}年${Number(m)}月`
}

export default function MonthlyWorkCollection({
  items,
  onOpen,
  onDelete,
  onPublish,
  publishingId = null,
  emptyHint,
}: MonthlyWorkCollectionProps) {
  if (!items.length) {
    return <p className="monthly-collection-empty">{emptyHint}</p>
  }
  // 示例(demo seed)作品:不按月份折叠,单独置顶成一组,
  // 避免作为示例的固定内容被时间排序淹没在旧月份里。
  const demoItems = items.filter(item => item.is_demo_seed)
  const ownItems = items.filter(item => !item.is_demo_seed)
  const renderCard = (item: FilmFolderItem) => (
    <li className="monthly-work-item" key={`${item.source_kind}-${item.id}`}>
      <div className="monthly-work-card">
        <div className="monthly-work-cover-shell">
          <button
            type="button"
            className="monthly-work-cover-button"
            onClick={() => onOpen(item)}
            aria-label={`${item.title},${formatItemDate(item)}`}
          >
            <span className={`monthly-work-cover ${item.source_kind === 'video_job' ? 'is-motion-comic' : ''}`}>
          {item.cover_url ? (
            <img src={item.cover_url} alt="" loading="lazy" />
          ) : (
            <span className="monthly-work-cover-fallback" aria-hidden="true" />
          )}
            </span>
          </button>
          {item.is_demo_seed && (
            <span className="monthly-work-demo-badge" aria-label="示例作品">示例</span>
          )}
          {onDelete && item.source_kind !== 'video_job' && !item.is_demo_seed && (
            <button
              type="button"
              className="monthly-work-delete"
              aria-label={`删除《${item.title}》`}
              onClick={() => onDelete(item)}
            >
              <Trash2 width={15} height={15} />
            </button>
          )}
        </div>
        <div className="monthly-work-meta">
          <button
            type="button"
            className="monthly-work-title"
            onClick={() => onOpen(item)}
            aria-label={`打开《${item.title}》`}
          >
            {item.title}
          </button>
          {onPublish && item.source_kind === 'canonical_work' && !item.is_demo_seed && (
            item.published ? (
              <span className="monthly-work-published">已发布到回响</span>
            ) : (
              <button
                type="button"
                className="monthly-work-publish"
                disabled={publishingId === item.id}
                onClick={() => onPublish(item)}
              >
                {publishingId === item.id ? '发布中…' : '发布到回响'}
              </button>
            )
          )}
        </div>
      </div>
    </li>
  )
  return (
    <div className="monthly-collection">
      {demoItems.length > 0 && (
        <section className="monthly-collection-month monthly-collection-demo">
          <h3 className="monthly-collection-heading">示例 · 置顶</h3>
          <ul className="monthly-collection-grid">
            {demoItems.map(renderCard)}
          </ul>
        </section>
      )}
      {groupByMonth(ownItems).map(group => (
        <section key={group.month} className="monthly-collection-month">
          <h3 className="monthly-collection-heading">
            {formatMonthLabel(group.month)}
          </h3>
          <ul className="monthly-collection-grid">
            {group.items.map(renderCard)}
          </ul>
        </section>
      ))}
    </div>
  )
}
