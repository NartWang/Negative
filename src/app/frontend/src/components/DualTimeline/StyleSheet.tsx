import { useState } from 'react'
import type { DrawStyle } from '../../types'
import BottomSheet from '../BottomSheet'
import StyleSelector from '../StyleSelector'
import './style.css'

interface Props {
  open: boolean
  onClose: () => void
  generating: boolean
  onSubmit: (args: { style: DrawStyle; custom_style_prompt?: string }) => void
  selectedCount: number
}

export default function StyleSheet({ open, onClose, generating, onSubmit, selectedCount }: Props) {
  const [style, setStyle] = useState<DrawStyle>(
    (localStorage.getItem('drawStyle') as DrawStyle) || 'ghibli'
  )
  const [custom, setCustom] = useState(localStorage.getItem('customDraw') || '')

  return (
    <BottomSheet open={open} onClose={() => !generating && onClose()} title={`生成漫画（已选 ${selectedCount}）`}>
      <div className="dt-style-body">
        <StyleSelector
          value={style}
          onChange={(v) => { setStyle(v); localStorage.setItem('drawStyle', v) }}
          customPrompt={custom}
          onCustomChange={(v) => { setCustom(v); localStorage.setItem('customDraw', v) }}
        />
        <div className="dt-style-actions">
          <button className="dt-btn dt-btn-secondary" onClick={onClose} disabled={generating}>
            取消
          </button>
          <button
            className="dt-btn dt-btn-primary pressable"
            onClick={() => onSubmit({ style, custom_style_prompt: style === 'custom' ? custom : undefined })}
            disabled={generating}
          >
            {generating ? '生成中…' : '开始生成'}
          </button>
        </div>
      </div>
    </BottomSheet>
  )
}
