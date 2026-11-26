import { useEffect, useState } from 'react'
import { filmFolderApi } from '../../api/client'
import Modal from '../../components/Modal'
import { Trash2 } from '../../components/Icon'
import type {
  FilmFolderMedium,
  UnfinishedMotionComic,
  UnfinishedPicturebook,
} from '../../types'
import './style.css'

export interface UnfinishedWorksProps {
  medium: FilmFolderMedium
  onBack(): void
  /** 绘本:canonical 作品按 work_id 打开向导。 */
  onOpenPicturebook(item: UnfinishedPicturebook): void
  /** 绘本:历史失败任务按 job_id 重试;成功/槽位冲突由调用方负责跳转。 */
  onRetryPicturebook(item: UnfinishedPicturebook): Promise<void>
  /** 漫剧:未关联任务的草稿继续编辑。 */
  onOpenMotionDraft(item: UnfinishedMotionComic): void
  /** 漫剧:失败任务按 video_job_id 重试;成功/槽位冲突由调用方负责跳转。 */
  onRetryMotionComic(item: UnfinishedMotionComic): Promise<void>
}

const RETRY_FAILURE_MESSAGE = '重试没能开始，请稍后再试'

const STYLE_LABELS: Record<string, string> = {
  crayon: '蜡笔风', watercolor: '水彩风', sketch: '素描风', pixel: '像素风',
}

const dateLabel = (start?: string | null, end?: string | null) => {
  if (!start) return ''
  return !end || start === end ? start : `${start} 至 ${end}`
}

export default function UnfinishedWorks({
  medium,
  onBack,
  onOpenPicturebook,
  onRetryPicturebook,
  onOpenMotionDraft,
  onRetryMotionComic,
}: UnfinishedWorksProps) {
  const [picturebooks, setPicturebooks] = useState<UnfinishedPicturebook[] | null>(null)
  const [motionComics, setMotionComics] = useState<UnfinishedMotionComic[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 单飞:一次只允许一个重试在途;失败只给出稳定安全文案。
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<
    { medium: FilmFolderMedium; id: number; sourceKind?: 'canonical_work' | 'historical_job'; title: string } | null
  >(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    setActionError(null)
    setBusyKey(null)
    const load = medium === 'picturebook'
      ? filmFolderApi.unfinishedPicturebooks()
      : filmFolderApi.unfinishedMotionComics()
    load
      .then(result => {
        if (cancelled) return
        if (medium === 'picturebook') {
          setPicturebooks((result as { items: UnfinishedPicturebook[] }).items)
        } else {
          setMotionComics((result as { items: UnfinishedMotionComic[] }).items)
        }
      })
      .catch(() => {
        if (!cancelled) setError('加载失败,请重试')
      })
    return () => { cancelled = true }
  }, [medium])

  const runRetry = async (key: string, action: () => Promise<void>) => {
    if (busyKey !== null) return
    setBusyKey(key)
    setActionError(null)
    try {
      await action()
    } catch {
      setActionError(RETRY_FAILURE_MESSAGE)
    } finally {
      setBusyKey(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || busyKey !== null) return
    const target = deleteTarget
    const key = `delete-${target.medium}-${target.id}`
    setBusyKey(key)
    setActionError(null)
    try {
      if (target.medium === 'picturebook') {
        await filmFolderApi.deletePicturebook(target.sourceKind!, target.id)
        setPicturebooks(current => current?.filter(item => !(
          item.id === target.id && item.source_kind === target.sourceKind
        )) ?? current)
      } else {
        await filmFolderApi.deleteMotionDraft(target.id)
        setMotionComics(current => current?.filter(item => item.id !== target.id) ?? current)
      }
      setDeleteTarget(null)
    } catch {
      setActionError('删除失败，请稍后重试')
    } finally {
      setBusyKey(null)
    }
  }

  const items = medium === 'picturebook' ? picturebooks : motionComics

  return (
    <main className="unfinished-works">
      <header className="unfinished-works-header">
        <button type="button" className="unfinished-works-back" onClick={onBack}>
          返回
        </button>
        <h1>{medium === 'picturebook' ? '继续创作绘本' : '继续创作漫剧'}</h1>
      </header>

      {error && (
        <p className="unfinished-works-error" role="alert">{error}</p>
      )}
      {actionError && (
        <p className="unfinished-works-action-error" role="alert">{actionError}</p>
      )}
      {items === null && !error && (
        <p className="unfinished-works-loading">正在读取…</p>
      )}
      {items !== null && items.length === 0 && (
        <p className="unfinished-works-empty">没有未完成的作品</p>
      )}

      {medium === 'picturebook' && picturebooks && (
        <ul className="unfinished-works-list">
          {picturebooks.map(item => {
            const key = `picturebook-${item.source_kind}-${item.id}`
            const busy = busyKey === key
            return (
              <li key={key}>
                <article className="unfinished-row">
                  <div className="unfinished-row-copy">
                    <span className="unfinished-row-tags">
                      <b>绘本</b>
                      <b>{item.work_kind === 'time_story' ? '时光故事' : '当日绘本'}</b>
                      {item.style && <b>{STYLE_LABELS[item.style] || item.style}</b>}
                    </span>
                    <span className="unfinished-row-title">{item.title}</span>
                    {dateLabel(item.display_start_date, item.display_end_date) && (
                      <span className="unfinished-row-date">{dateLabel(item.display_start_date, item.display_end_date)}</span>
                    )}
                    {item.error && (
                      <span className="unfinished-row-error">{item.error}</span>
                    )}
                  </div>
                  <div className="unfinished-row-actions">
                  {item.source_kind === 'canonical_work' ? (
                    <button
                      type="button"
                      className="unfinished-row-action"
                      disabled={busyKey !== null}
                      onClick={() => onOpenPicturebook(item)}
                    >
                      继续创作
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="unfinished-row-action"
                      disabled={busyKey !== null}
                      onClick={() => void runRetry(key, () => onRetryPicturebook(item))}
                    >
                      {busy ? '正在重试' : '重试绘本'}
                    </button>
                  )}
                    <button
                      type="button"
                      className="unfinished-row-delete"
                      aria-label={`删除《${item.title}》`}
                      disabled={busyKey !== null}
                      onClick={() => setDeleteTarget({
                        medium: 'picturebook', id: item.id,
                        sourceKind: item.source_kind, title: item.title,
                      })}
                    >
                      <Trash2 width={14} height={14} />
                    </button>
                  </div>
                </article>
              </li>
            )
          })}
        </ul>
      )}

      {medium === 'motion_comic' && motionComics && (
        <ul className="unfinished-works-list">
          {motionComics.map(item => {
            const key = `motion-${item.id}`
            const busy = busyKey === key
            const retryable = item.status === 'failed' && item.video_job_id !== null
            return (
              <li key={key}>
                <article className="unfinished-row">
                  <div className="unfinished-row-copy">
                    <span className="unfinished-row-tags">
                      <b>漫剧</b>
                      <b>{item.status === 'failed' ? '生成失败' : '未完成'}</b>
                      {item.style && <b>{STYLE_LABELS[item.style] || item.style}</b>}
                    </span>
                    <span className="unfinished-row-title">
                      {item.title || '未命名漫剧'}
                    </span>
                    {dateLabel(item.display_start_date, item.display_end_date) && (
                      <span className="unfinished-row-date">{dateLabel(item.display_start_date, item.display_end_date)}</span>
                    )}
                    {item.error && (
                      <span className="unfinished-row-error">{item.error}</span>
                    )}
                  </div>
                  <div className="unfinished-row-actions">
                  {retryable ? (
                    <button
                      type="button"
                      className="unfinished-row-action"
                      disabled={busyKey !== null}
                      onClick={() => void runRetry(key, () => onRetryMotionComic(item))}
                    >
                      {busy ? '正在重试' : '重试漫剧'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="unfinished-row-action"
                      disabled={busyKey !== null}
                      onClick={() => onOpenMotionDraft(item)}
                    >
                      继续编辑
                    </button>
                  )}
                    <button
                      type="button"
                      className="unfinished-row-delete"
                      aria-label={`删除《${item.title || '未命名漫剧'}》`}
                      disabled={busyKey !== null}
                      onClick={() => setDeleteTarget({
                        medium: 'motion_comic', id: item.id,
                        title: item.title || '未命名漫剧',
                      })}
                    >
                      <Trash2 width={14} height={14} />
                    </button>
                  </div>
                </article>
              </li>
            )
          })}
        </ul>
      )}
      <Modal
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title="删除这条创作？"
        description={deleteTarget ? `确认删除《${deleteTarget.title}》的未完成记录吗？` : ''}
        confirmText="确认删除"
        cancelText="取消"
        danger
        onConfirm={() => { void confirmDelete() }}
      />
    </main>
  )
}
