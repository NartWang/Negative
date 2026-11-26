import { useRef, useState } from 'react'
import type { Fragment, FragmentUpdatePayload } from '../../types'
import { fragmentClockTime } from '../../utils/recordTime'
import { uploadApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import BottomSheet from '../BottomSheet'
import SafeImage from '../SafeImage'
import WarmTimePicker from '../WarmTimePicker'
import './style.css'

interface PendingPhoto {
  assetId: string
  url: string
  description?: string | null
}

interface Props {
  open: boolean
  fragment: Fragment
  onClose: () => void
  onUpdate: (id: number, data: FragmentUpdatePayload) => Promise<void>
  onDelete: (id: number) => Promise<void>
}

export default function FragmentEditorSheet({ open, fragment, onClose, onUpdate, onDelete }: Props) {
  const toast = useToast()
  const [text, setText] = useState(fragment.content ?? '')
  const [time, setTime] = useState(() => fragmentClockTime(fragment))
  const [retainedPhotoUrl, setRetainedPhotoUrl] = useState<string | null>(fragment.photo_url)
  const [pendingPhoto, setPendingPhoto] = useState<PendingPhoto | null>(null)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const hasPhoto = Boolean(pendingPhoto || retainedPhotoUrl)
  const canSave = Boolean(text.trim() || pendingPhoto || retainedPhotoUrl)

  const handleFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const result = await uploadApi.upload(file, { describe: true })
      setPendingPhoto({
        assetId: result.asset_id,
        url: result.url,
        description: result.photo_description,
      })
      setRetainedPhotoUrl(null)
      toast.success('图片已附加')
    } catch {
      toast.error('上传失败，请重新选择照片')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const removePhoto = () => {
    setRetainedPhotoUrl(null)
    setPendingPhoto(null)
  }

  const handleSave = async () => {
    if (!canSave || saving) return
    setSaving(true)
    const payload: FragmentUpdatePayload = {
      content: text.trim(),
      record_time: time || undefined,
    }
    if (pendingPhoto) {
      payload.photo_asset_id = pendingPhoto.assetId
      payload.photo_url = pendingPhoto.url
      if (pendingPhoto.description != null) {
        payload.photo_description = pendingPhoto.description
      }
    } else if (fragment.photo_url && !retainedPhotoUrl) {
      payload.photo_asset_id = null
      payload.photo_url = null
    }
    try {
      await onUpdate(fragment.id, payload)
      onClose()
    } catch {
      toast.error('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirmingDelete) {
      setConfirmingDelete(true)
      return
    }
    if (deleting) return
    setDeleting(true)
    try {
      await onDelete(fragment.id)
      onClose()
    } catch {
      toast.error('删除失败，请重试')
      setConfirmingDelete(false)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="编辑随记">
      <div className="fragment-editor">
        <textarea
          aria-label="随记内容"
          value={text}
          onChange={e => setText(e.target.value)}
          rows={4}
          placeholder="想法或感受..."
        />
        <div className="fragment-editor-time">
          <span>记录时间</span>
          <WarmTimePicker
            value={time}
            onChange={setTime}
            className="fragment-editor-time-picker"
            portalAbove
          />
        </div>

        <div className="fragment-editor-photo">
          {hasPhoto ? (
            <div className="fragment-editor-photo-preview">
              <SafeImage src={pendingPhoto?.url ?? retainedPhotoUrl ?? ''} alt="随记照片" />
              <div className="fragment-editor-photo-actions">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                >{uploading ? '上传中…' : '替换照片'}</button>
                <button type="button" onClick={removePhoto} disabled={uploading}>移除照片</button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="fragment-editor-add-photo"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >{uploading ? '上传中…' : '添加照片'}</button>
          )}
          <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleFile} />
        </div>

        <div className="fragment-editor-actions">
          <button
            type="button"
            className="btn-danger"
            onClick={handleDelete}
            disabled={deleting}
          >{confirmingDelete ? (deleting ? '删除中…' : '确认删除') : '删除'}</button>
          <button
            type="button"
            className="btn-primary"
            onClick={handleSave}
            disabled={!canSave || saving}
          >{saving ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </BottomSheet>
  )
}
