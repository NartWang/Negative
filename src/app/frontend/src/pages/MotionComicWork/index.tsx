import { useEffect, useState } from 'react'
import { ArrowLeft } from '../../components/Icon'
import { filmFolderApi } from '../../api/client'
import type { FilmFolderMotionComicDetail } from '../../types'
import './style.css'

export interface MotionComicWorkProps {
  videoJobId: number
  onBack(): void
}

/** 完成漫剧的只读播放页:不暴露生成或重试入口。 */
export default function MotionComicWork({ videoJobId, onBack }: MotionComicWorkProps) {
  const [detail, setDetail] = useState<FilmFolderMotionComicDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    filmFolderApi.motionComicDetail(videoJobId)
      .then(result => { if (!cancelled) setDetail(result) })
      .catch(() => { if (!cancelled) setError('漫剧暂时打不开') })
    return () => { cancelled = true }
  }, [videoJobId])

  return (
    <main className="app-reader-page">
      <button
        type="button"
        className="app-reader-back"
        onClick={onBack}
        aria-label="返回底片夹"
      >
        <ArrowLeft />
      </button>
      {detail ? (
        <div className="motion-comic-work">
          <header className="motion-comic-work-header">
            <div>
              <span className="motion-comic-work-kicker">漫剧放映</span>
              <h1 className="motion-comic-work-title">{detail.title}</h1>
            </div>
            {detail.duration_seconds && (
              <span className="motion-comic-work-duration">
                {Math.round(detail.duration_seconds)} 秒
              </span>
            )}
          </header>
          <div className="motion-comic-work-stage">
            <video
              className="motion-comic-work-player"
              src={detail.video_url}
              poster={detail.cover_url ?? undefined}
              controls
              playsInline
              preload="metadata"
              aria-label={`${detail.title}的视频`}
            />
          </div>
          <p className="motion-comic-work-note">程序员小马的一天 · 像素风案例</p>
        </div>
      ) : (
        <div className="app-loading" role={error ? 'alert' : 'status'}>
          <p>{error ?? '正在读取漫剧…'}</p>
        </div>
      )}
    </main>
  )
}
