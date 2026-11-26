import { useEffect, useState } from 'react'
import PictureBookReader from '../../components/PictureBookReader'
import { ArrowLeft } from '../../components/Icon'
import { filmFolderApi } from '../../api/client'
import type { FilmFolderPicturebookDetail } from '../../types'

export interface PicturebookWorkReaderProps {
  sourceKind: 'canonical_work' | 'historical_job'
  sourceId: number
  onBack(): void
}

/** 按底片夹摘要键读取完整绘本,再交给现有阅读器。 */
export default function PicturebookWorkReader({
  sourceKind,
  sourceId,
  onBack,
}: PicturebookWorkReaderProps) {
  const [detail, setDetail] = useState<FilmFolderPicturebookDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    filmFolderApi.picturebookDetail(sourceKind, sourceId)
      .then(result => { if (!cancelled) setDetail(result) })
      .catch(() => { if (!cancelled) setError('绘本暂时打不开') })
    return () => { cancelled = true }
  }, [sourceKind, sourceId])

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
        <PictureBookReader pages={detail.pages} title={detail.title} />
      ) : (
        <div className="app-loading" role={error ? 'alert' : 'status'}>
          <p>{error ?? '正在读取绘本…'}</p>
        </div>
      )}
    </main>
  )
}
