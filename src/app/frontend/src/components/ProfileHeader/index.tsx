import { useRef, useState } from 'react'
import type { Profile } from '../../types'
import { uploadApi, profileApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import BottomSheet from '../BottomSheet'
import './style.css'

interface Props {
  profile: Profile
  joinedDays: number
  onUpdate: (p: Profile) => void
}

export default function ProfileHeader({ profile, joinedDays, onUpdate }: Props) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [nickname, setNickname] = useState(profile.nickname)
  const [signature, setSignature] = useState(profile.signature)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const saveEdit = async () => {
    try {
      const updated = await profileApi.update({ nickname: nickname.trim(), signature: signature.trim() })
      onUpdate(updated)
      setEditing(false)
      toast.success('已保存')
    } catch {
      toast.error('保存失败')
    }
  }

  const handleAvatar = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const { url } = await uploadApi.upload(file)
      const updated = await profileApi.update({ avatar_url: url })
      onUpdate(updated)
      toast.success('头像已更新')
    } catch {
      toast.error('上传失败')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <>
      <div className="profile-header">
        <button className="avatar-btn pressable" onClick={() => fileInputRef.current?.click()} aria-label="更换头像">
          {profile.avatar_url
            ? <img src={profile.avatar_url} alt="" />
            : <div className="avatar-fallback">🌿</div>}
          <div className="avatar-edit-badge">📷</div>
        </button>
        <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleAvatar} />
        <button className="profile-info pressable" onClick={() => setEditing(true)}>
          <div className="profile-nickname">{profile.nickname}</div>
          <div className="profile-joined">记录今天 第 {joinedDays} 天</div>
          <div className="profile-signature">{profile.signature}</div>
        </button>
      </div>

      <BottomSheet open={editing} onClose={() => setEditing(false)} title="编辑资料">
        <div className="profile-edit">
          <label>昵称</label>
          <input value={nickname} onChange={e => setNickname(e.target.value)} maxLength={24} />
          <label>签名</label>
          <textarea value={signature} onChange={e => setSignature(e.target.value)} maxLength={80} rows={3} />
          <button className="btn-primary" onClick={saveEdit} disabled={!nickname.trim()}>保存</button>
        </div>
      </BottomSheet>
    </>
  )
}
