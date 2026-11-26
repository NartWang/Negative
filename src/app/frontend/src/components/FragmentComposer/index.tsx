import { useEffect, useRef, useState } from 'react'
import { fragmentsApi, uploadApi } from '../../api/client'
import type { Fragment } from '../../types'
import { currentShanghaiClock, readableClockTime } from '../../utils/recordTime'
import WarmTimePicker from '../WarmTimePicker'
import './style.css'

interface Props {
  date: string
  onCreated: (fragment: Fragment) => void
}

interface PendingPhoto {
  url: string
  assetId: string
  description: string | null
}

export default function FragmentComposer({ date, onCreated }: Props) {
  const [text, setText] = useState('')
  const [recordTime, setRecordTime] = useState(() => currentShanghaiClock())
  const [pendingPhoto, setPendingPhoto] = useState<PendingPhoto | null>(null)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploadHint, setUploadHint] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setText('')
    setPendingPhoto(null)
    setUploadHint(null)
    setSaveError(null)
    setRecordTime(currentShanghaiClock())
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [date])

  const handlePhoto = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadHint(null)
    try {
      const result = await uploadApi.upload(file, { describe: true })
      setPendingPhoto({
        url: result.url,
        assetId: result.asset_id,
        description: result.photo_description,
      })
    } catch {
      setPendingPhoto(null)
      setUploadHint('请重新选择照片')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const removePhoto = () => {
    setPendingPhoto(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const canSubmit = !saving && !uploading && (text.trim() !== '' || pendingPhoto !== null)

  const submit = async () => {
    const content = text.trim()
    if (!content && !pendingPhoto) return
    setSaving(true)
    setSaveError(null)
    try {
      const created = await fragmentsApi.create({
        date,
        content,
        record_time: recordTime,
        ...(pendingPhoto
          ? {
              photo_url: pendingPhoto.url,
              photo_asset_id: pendingPhoto.assetId,
              photo_description: pendingPhoto.description || undefined,
            }
          : {}),
      })
      setText('')
      setPendingPhoto(null)
      setRecordTime(currentShanghaiClock())
      if (fileInputRef.current) fileInputRef.current.value = ''
      onCreated(created)
    } catch {
      setSaveError('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fragment-composer">
      <textarea
        aria-label="记录此刻的随记"
        placeholder="想到什么，就先放在这里…"
        value={text}
        onChange={event => setText(event.target.value)}
        rows={3}
      />
      {pendingPhoto && (
        <div className="composer-pending-photo">
          <img src={pendingPhoto.url} alt="待保存的照片" />
          <button
            type="button"
            className="composer-remove-photo"
            aria-label="移除照片"
            onClick={removePhoto}
          >×</button>
        </div>
      )}
      <div className="composer-toolbar">
        <div className="composer-time-field">
          <span className="composer-time-caption">记录时间</span>
          <span className="composer-time-controls">
            <WarmTimePicker
              value={recordTime}
              onChange={setRecordTime}
            />
            <span className="composer-time-readable">{readableClockTime(recordTime)}</span>
          </span>
        </div>
        <button
          type="button"
          className="composer-photo-btn"
          aria-label="添加照片"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >{uploading ? '上传中…' : '照片'}</button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={handlePhoto}
        />
      </div>
      {uploadHint && <p className="composer-hint" role="status">{uploadHint}</p>}
      {saveError && <p className="composer-hint" role="alert">{saveError}</p>}
      <button
        type="button"
        className="composer-submit"
        disabled={!canSubmit}
        onClick={submit}
      >{saving ? '保存中…' : '记下这一刻'}</button>
    </div>
  )
}
