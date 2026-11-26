import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, picturebookVideoApi } from '../../api/client'
import { Sparkle } from '../Icon'
import type { PicturebookVideoJob, PicturebookVideoSource } from '../../types'
import './style.css'

const POLL_INTERVAL_MS = 5000

interface PicturebookVideoProps {
  /** The finished picturebook this film is built from. */
  source: PicturebookVideoSource
  /** Explicit page order; omit to use the whole book. */
  pageIndexes?: number[]
  title?: string
  /** 底片夹草稿 id;旧调用方省略时请求体保持原样。 */
  draftId?: number
}

/**
 * The page order a finished job actually used, read back from its segments:
 * segment k spans (page k, page k+1), so the chain is the first page plus every
 * segment's tail.
 */
function jobPageSequence(job: PicturebookVideoJob): number[] {
  if (!job.segments.length) return []
  return [
    job.segments[0].first_page_index,
    ...job.segments.map(segment => segment.last_page_index),
  ]
}

function sameSequence(left: number[], right: number[]): boolean {
  return left.length === right.length && left.every((value, at) => value === right[at])
}

function progressLabel(job: PicturebookVideoJob): string {
  if (job.total_segments <= 0) return job.stage_label
  return `${job.stage_label} · ${job.ready_segments}/${job.total_segments} 段`
}

function durationLabel(job: PicturebookVideoJob): string | null {
  if (!job.duration_seconds) return null
  return `约 ${Math.round(job.duration_seconds)} 秒`
}

export default function PicturebookVideo({
  source,
  pageIndexes,
  title = '绘本视频',
  draftId,
}: PicturebookVideoProps) {
  const [job, setJob] = useState<PicturebookVideoJob | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 后端没配生成服务时返回 503，这时不该给出一个必然失败的按钮。
  const [unavailable, setUnavailable] = useState(false)
  const cancelled = useRef(false)

  // 页序是数组，直接进依赖会每次渲染都变；用它的内容做key。
  const sequenceKey = useMemo(
    () => (pageIndexes && pageIndexes.length ? pageIndexes.join(',') : ''),
    [pageIndexes],
  )

  useEffect(() => {
    cancelled.current = false
    return () => { cancelled.current = true }
  }, [])

  useEffect(() => {
    let dropped = false
    setLoading(true)
    setJob(null)
    setError(null)
    picturebookVideoApi.latest(source)
      .then(result => {
        if (dropped) return
        // 用户可能改了选页或顺序，那条旧片子就不是"当前这条"了。
        if (result && sequenceKey) {
          const used = jobPageSequence(result)
          const wanted = sequenceKey.split(',').map(Number)
          if (!sameSequence(used, wanted)) {
            setJob(null)
            return
          }
        }
        setJob(result)
      })
      .catch(() => {
        // 没有历史视频不是错误，静默当作"还没生成"。
        if (!dropped) setJob(null)
      })
      .finally(() => {
        if (!dropped) setLoading(false)
      })
    return () => { dropped = true }
  }, [source.kind, source.id, sequenceKey])

  // 渲染要跑几分钟，所以进度靠轮询推进，而不是把请求挂在那里等。
  useEffect(() => {
    if (!job || job.status !== 'running') return

    let dropped = false
    const timer = window.setTimeout(() => {
      picturebookVideoApi.get(job.id)
        .then(result => {
          if (!dropped) setJob(result)
        })
        .catch(() => {
          // 单次轮询失败不该打断进度，下一轮会再试。
        })
    }, POLL_INTERVAL_MS)

    return () => {
      dropped = true
      window.clearTimeout(timer)
    }
  }, [job])

  const handleFailure = useCallback((cause: unknown, fallback: string) => {
    if (cause instanceof ApiError) {
      if (cause.status === 503) {
        setUnavailable(true)
        setError('视频生成服务还没开启')
        return
      }
      if (cause.status === 409) {
        setError('绘本还没画完，画完再来生成视频')
        return
      }
      setError(cause.message || fallback)
      return
    }
    setError(fallback)
  }, [])

  const start = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const options: { page_indexes?: number[]; draft_id?: number } = {}
      if (pageIndexes && pageIndexes.length) options.page_indexes = pageIndexes
      if (draftId !== undefined) options.draft_id = draftId
      setJob(await picturebookVideoApi.start(source, options))
    } catch (cause) {
      handleFailure(cause, '视频没能开始生成')
    } finally {
      if (!cancelled.current) setBusy(false)
    }
  }

  const retry = async () => {
    if (!job || busy) return
    setBusy(true)
    setError(null)
    try {
      setJob(await picturebookVideoApi.retry(job.id))
    } catch (cause) {
      handleFailure(cause, '重试没能开始')
    } finally {
      if (!cancelled.current) setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="picturebook-video picturebook-video-state" role="status">
        正在读取视频…
      </div>
    )
  }

  if (job?.status === 'done' && job.video_url) {
    return (
      <div className="picturebook-video">
        <video
          className="picturebook-video-player"
          src={job.video_url}
          controls
          playsInline
          preload="metadata"
          aria-label={`${title}的视频`}
        />
        <div className="picturebook-video-meta">
          <span>{job.total_segments} 段接成一条</span>
          {durationLabel(job) && <span>{durationLabel(job)}</span>}
          <a
            className="picturebook-video-download"
            href={job.video_url}
            download={`${title}.mp4`}
          >
            保存视频
          </a>
        </div>
      </div>
    )
  }

  if (job?.status === 'running') {
    const percent = job.total_segments
      ? Math.round((job.ready_segments / job.total_segments) * 100)
      : 0
    return (
      <div className="picturebook-video">
        <div className="picturebook-video-progress" role="status" aria-live="polite">
          <p>{progressLabel(job)}</p>
          <div
            className="picturebook-video-bar"
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span style={{ width: `${percent}%` }} />
          </div>
          <p className="picturebook-video-hint">
            每两页之间生成一段动画，全部并行进行，通常几分钟就好。可以先去做别的。
          </p>
        </div>
      </div>
    )
  }

  if (job?.status === 'failed') {
    return (
      <div className="picturebook-video">
        <div className="picturebook-video-state error" role="alert">
          <strong>{job.error ?? '视频生成失败了'}</strong>
          <p className="picturebook-video-hint">
            已经画好的段会保留，重试只补没成的那几段。
          </p>
          <button type="button" onClick={retry} disabled={busy || unavailable}>
            {busy ? '正在重试' : '重试没成的段'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="picturebook-video">
      <div className="picturebook-video-empty">
        <button
          type="button"
          className="picturebook-video-start"
          onClick={start}
          disabled={busy || unavailable}
        >
          <Sparkle width={18} height={18} aria-hidden="true" />
          {busy ? '正在开始' : '生成绘本视频'}
        </button>
        {error && <p className="picturebook-video-error" role="alert">{error}</p>}
      </div>
    </div>
  )
}
