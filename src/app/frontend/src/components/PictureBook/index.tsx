import { useEffect, useState } from 'react'
import type { PicturebookJob } from '../../types'
import './style.css'

interface Props {
  job: PicturebookJob
  onRetry: () => void
}

const STAGE_ORDER = ['character', 'story', 'prompts', 'rendering'] as const
const STAGE_TEXT: Record<string, string> = {
  character: '读取小主角',
  story: '改写成故事',
  prompts: '设计画面',
  rendering: '逐页作画',
}

/**
 * Shows only the finished artwork. The story JSON and the nine generated prompts
 * stay server-side — the reader sees a book, not a pipeline.
 */
export default function PictureBook({ job, onRetry }: Props) {
  const ready = job.pages.filter(page => page.status === 'ready' && page.image_url)
  const failed = job.pages.filter(page => page.status === 'failed')
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (index > ready.length - 1) setIndex(Math.max(0, ready.length - 1))
  }, [ready.length, index])

  const current = ready[index]
  const reachedStage = STAGE_ORDER.indexOf(job.stage as typeof STAGE_ORDER[number])

  return (
    <div className="picturebook">
      {job.status === 'running' && (
        <div className="pb-progress" role="status" aria-live="polite">
          <strong>{job.stage_label}</strong>
          <ol className="pb-stages">
            {STAGE_ORDER.map((stage, order) => (
              <li key={stage} className={order <= reachedStage ? 'done' : ''}>
                {STAGE_TEXT[stage]}
              </li>
            ))}
          </ol>
          <div className="pb-bar">
            <span style={{ width: `${(job.ready_pages / Math.max(1, job.total_pages)) * 100}%` }} />
          </div>
          <small>
            已完成 {job.ready_pages} / {job.total_pages} 页 · 整本大约需要几分钟，可以先去做别的
          </small>
        </div>
      )}

      {job.status === 'failed' && (
        <div className="pb-failed" role="alert">
          <strong>{job.error || '生成失败'}</strong>
          {/* A key/balance problem cannot be retried away — say so plainly. */}
          {/(HTTP 40[123])|余额|balance|密钥|API key/i.test(job.error || '') ? (
            <small>这是生图/文本服务的账户问题，重试也不会成功，需要先处理好密钥或余额。</small>
          ) : (
            <button type="button" className="pb-retry pressable" onClick={onRetry}>
              重试没成功的页
            </button>
          )}
        </div>
      )}

      {ready.length > 0 && (
        <div className="pb-viewer">
          <div className="pb-frame">
            <img
              src={current.image_url!}
              alt={current.caption || (current.page_index === 0 ? '封面' : `第 ${current.page_index} 页`)}
            />
          </div>
          <div className="pb-caption">
            {current.page_index === 0 ? '封面' : `第 ${current.page_index} 页`}
            {current.caption ? ` · ${current.caption}` : ''}
          </div>
          <div className="pb-controls">
            <button
              type="button"
              className="pb-nav"
              disabled={index === 0}
              onClick={() => setIndex(value => Math.max(0, value - 1))}
              aria-label="上一页"
            >‹</button>
            <span className="pb-counter">{index + 1} / {ready.length}</span>
            <button
              type="button"
              className="pb-nav"
              disabled={index >= ready.length - 1}
              onClick={() => setIndex(value => Math.min(ready.length - 1, value + 1))}
              aria-label="下一页"
            >›</button>
          </div>
          <div className="pb-strip">
            {ready.map((page, order) => (
              <button
                key={page.page_index}
                type="button"
                className={`pb-thumb ${order === index ? 'active' : ''}`}
                onClick={() => setIndex(order)}
                aria-label={page.page_index === 0 ? '封面' : `第 ${page.page_index} 页`}
              >
                <img src={page.image_url!} alt="" />
              </button>
            ))}
          </div>
        </div>
      )}

      {failed.length > 0 && job.status !== 'failed' && (
        <p className="pb-note">有 {failed.length} 页还没画成，稍后可以重试。</p>
      )}
    </div>
  )
}
