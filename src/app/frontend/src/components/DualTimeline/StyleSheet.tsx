import { useState } from 'react'
import type { DrawStyle } from '../../types'
import BottomSheet from '../BottomSheet'
import StyleSelector from '../StyleSelector'
import { getDrawStylePreference, setUserPreference } from '../../utils/userPreferences'
import './style.css'

interface Props {
  userId?: number
  open: boolean
  onClose: () => void
  generating: boolean
  onSubmit: (args: { style: DrawStyle; custom_style_prompt?: string }) => void
  selectedCount: number
}

export default function StyleSheet({ userId, open, onClose, generating, onSubmit, selectedCount }: Props) {
  const [style, setStyle] = useState<DrawStyle>(() => getDrawStylePreference(userId))

  return (
    <BottomSheet open={open} onClose={() => !generating && onClose()} title={`生成漫画（已选 ${selectedCount}）`}>
      <div className="dt-style-body">
        <StyleSelector
          value={style}
          onChange={(v) => { setStyle(v); setUserPreference(userId, 'drawStyle', v) }}
        />
        <div className="dt-style-actions">
          <button className="dt-btn dt-btn-secondary" onClick={onClose} disabled={generating}>
            取消
          </button>
          <button
            className="dt-btn dt-btn-primary pressable"
            onClick={() => onSubmit({ style })}
            disabled={generating}
          >
            {generating ? '生成中…' : '开始生成'}
          </button>
        </div>
      </div>
    </BottomSheet>
  )
}
