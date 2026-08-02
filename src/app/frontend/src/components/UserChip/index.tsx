import { useState } from 'react'
import { useUser } from '../../contexts/UserContext'
import BottomSheet from '../BottomSheet'
import './style.css'

export default function UserChip() {
  const { currentUser, users, setCurrentUserId } = useUser()
  const [open, setOpen] = useState(false)

  if (!currentUser) return null

  const choose = (id: number) => {
    setCurrentUserId(id)
    setOpen(false)
    // Force a full reload so every page re-fetches under the new user.
    // This is the cheapest correct option for v3 MVP.
    setTimeout(() => window.location.reload(), 80)
  }

  return (
    <>
      <button className="user-chip pressable" onClick={() => setOpen(true)} aria-label="切换用户">
        <span className="user-chip-icon">👤</span>
        <span className="user-chip-name">{currentUser.nickname}</span>
        <span className="user-chip-chev">▾</span>
      </button>
      <BottomSheet open={open} onClose={() => setOpen(false)} title="切换视角">
        <div className="user-list">
          {users.map(u => (
            <button
              key={u.id}
              className={`user-row ${u.id === currentUser.id ? 'active' : ''}`}
              onClick={() => choose(u.id)}
            >
              <span className="user-row-avatar">👤</span>
              <div className="user-row-meta">
                <div className="user-row-name">{u.nickname}</div>
                <div className="user-row-sig">{u.signature}</div>
              </div>
              {u.id === currentUser.id && <span className="user-row-check">✓</span>}
            </button>
          ))}
        </div>
      </BottomSheet>
    </>
  )
}
