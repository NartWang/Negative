import { useEffect, useMemo, useState } from 'react'
import BottomSheet from '../BottomSheet'
import { exportApi, filmFolderApi } from '../../api/client'
import type { FilmFolderItem, FilmFolderMedium } from '../../types'
import { downloadBlob } from '../../utils/downloadBlob'
import './style.css'

export interface PdfExportSheetProps {
  open: boolean
  medium: FilmFolderMedium
  onClose: () => void
}

function safeFilename(title: string): string {
  const normalized = title.replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, ' ').trim()
  return normalized || '底片作品'
}

export default function PdfExportSheet({ open, medium, onClose }: PdfExportSheetProps) {
  const [items, setItems] = useState<FilmFolderItem[] | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isPicturebook = medium === 'picturebook'

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setItems(null)
    setSelectedKey(null)
    setError(null)
    const load = isPicturebook ? filmFolderApi.picturebooks() : filmFolderApi.motionComics()
    load
      .then(result => { if (!cancelled) setItems(result.items) })
      .catch(() => { if (!cancelled) setItems([]) })
    return () => { cancelled = true }
  }, [open, isPicturebook])

  const selected = useMemo(
    () => items?.find(item => `${item.source_kind}-${item.id}` === selectedKey) ?? null,
    [items, selectedKey],
  )

  const handleExport = async () => {
    if (!selected || busy) return
    setBusy(true)
    setError(null)
    try {
      if (isPicturebook) {
        if (selected.source_kind === 'video_job') return
        const blob = await exportApi.downloadPicturebookPdf(selected.source_kind, selected.id)
        downloadBlob(blob, `${safeFilename(selected.title)}.pdf`)
      } else {
        const blob = await exportApi.downloadMotionComic(selected.id)
        downloadBlob(blob, `${safeFilename(selected.title)}.mp4`)
      }
      onClose()
    } catch {
      setError(isPicturebook ? '绘本导出失败，请重试' : '漫剧导出失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title={isPicturebook ? '导出绘本' : '导出漫剧'}
    >
      <div className="pdf-export">
        <p className="pdf-export-intro">
          {isPicturebook
            ? '选择一本绘本，插画和对应文字会逐页保存为 PDF。'
            : '选择一部漫剧，视频会以 MP4 格式下载到本地。'}
        </p>

        <div className="pdf-export-work-list">
          {items === null ? (
            <p className="pdf-export-hint">正在读取…</p>
          ) : items.length === 0 ? (
            <p className="pdf-export-hint">
              {isPicturebook ? '还没有可以导出的绘本' : '还没有可以导出的漫剧'}
            </p>
          ) : items.map(item => {
            const key = `${item.source_kind}-${item.id}`
            return (
              <label key={key} className={`pdf-export-work ${selectedKey === key ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="export-work"
                  checked={selectedKey === key}
                  onChange={() => setSelectedKey(key)}
                />
                <span className="pdf-export-work-cover">
                  {item.cover_url ? <img src={item.cover_url} alt="" /> : <span />}
                </span>
                <span className="pdf-export-work-copy">
                  <strong>{item.title}</strong>
                  <small>{item.display_start_date}</small>
                </span>
              </label>
            )
          })}
        </div>

        {error && <p className="pdf-export-error" role="alert">{error}</p>}
        <button
          type="button"
          className="pdf-export-submit"
          disabled={!selected || busy}
          onClick={() => void handleExport()}
        >
          {busy
            ? '正在导出…'
            : isPicturebook ? '下载绘本 PDF' : '下载漫剧视频'}
        </button>
      </div>
    </BottomSheet>
  )
}
