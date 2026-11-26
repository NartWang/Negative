import { useEffect, useMemo, useState } from 'react'
import type { CharacterProfile } from '../../types'
import {
  actionUrl,
  presetMainUrl,
  type ActionKey,
} from '../../pages/Mine/characterPresets'
import './style.css'

const DEFAULT_CHARACTER = '/characters/main/p01.webp'
const ACTIONS: ActionKey[] = ['idle', 'think', 'happy', 'read']

export interface CharacterProgressProps {
  /** 0–100 之间的视觉进度;组件内自行收敛,永不显示文字。 */
  percent: number
  character: CharacterProfile | null
  /** 辅助技术读到的状态,例如「绘本生成中」。 */
  accessibleLabel: string
}

function resolveImage(character: CharacterProfile | null): string {
  if (!character) return DEFAULT_CHARACTER
  const presetId = character.source_type === 'preset'
    ? (character.reference_image_url ?? '').match(/\/characters\/main\/(\w+)\.webp$/)?.[1]
    : undefined
  if (presetId && character.display_action) {
    const action = character.display_action as ActionKey
    if (ACTIONS.includes(action)) return actionUrl(presetId, action)
  }
  if (presetId) return presetMainUrl(presetId)
  if (character.reference_image_url) return character.reference_image_url
  return DEFAULT_CHARACTER
}

export default function CharacterProgress({
  percent,
  character,
  accessibleLabel,
}: CharacterProgressProps) {
  const clamped = Math.max(0, Math.min(100, percent))
  const [imageError, setImageError] = useState(false)
  // 角色变化时重新尝试其形象,不被上一次降级卡死。
  useEffect(() => { setImageError(false) }, [character])
  const src = useMemo(
    () => (imageError ? DEFAULT_CHARACTER : resolveImage(character)),
    [character, imageError],
  )

  return (
    <div
      className="character-progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
    >
      <span className="sr-only">{accessibleLabel}</span>
      <span className="character-progress-track">
        <span
          className="character-progress-fill"
          style={{ width: `${clamped}%` }}
        />
        <img
          className="character-progress-avatar"
          src={src}
          alt=""
          style={{ left: `${clamped}%` }}
          onError={() => setImageError(true)}
        />
      </span>
    </div>
  )
}
