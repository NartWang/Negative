import { useEffect, useState } from 'react'
import type { DrawStyle } from '../../types'
import { thisWeekRange, previousWeekRange } from '../../utils/week'
import BottomSheet from '../BottomSheet'
import StyleSelector from '../StyleSelector'
import { getUserPreference, setUserPreference } from '../../utils/userPreferences'
import './style.css'

interface Props {
  userId?: number
  open: boolean
  onClose: () => void
  onSubmit: (args: {
    week_start: string
    week_end: string
    style: DrawStyle
    custom_style_prompt?: string
  }) => void
  generating: boolean
}

type Preset = 'this' | 'prev' | 'custom'

export default function GenerateSheet({ userId, open, onClose, onSubmit, generating }: Props) {
  const [preset, setPreset] = useState<Preset>('this')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [style, setStyle] = useState<DrawStyle>(
    (getUserPreference(userId, 'drawStyle') as DrawStyle) || 'ghibli'
  )
  const [customStylePrompt, setCustomStylePrompt] = useState(
    getUserPreference(userId, 'customDraw') || ''
  )

  useEffect(() => {
    if (!open) return
    if (preset === 'this') {
      const r = thisWeekRange(); setStart(r.start); setEnd(r.end)
    } else if (preset === 'prev') {
      const r = previousWeekRange(); setStart(r.start); setEnd(r.end)
    }
  }, [open, preset])

  const submit = () => {
    if (!start || !end) return
    onSubmit({
      week_start: start,
      week_end: end,
      style,
      custom_style_prompt: style === 'custom' ? customStylePrompt : undefined,
    })
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="生成本周漫画">
      <div className="wc-sheet-body">
        <div className="wc-section-label">时间范围</div>
        <div className="wc-preset-row">
          {([
            { k: 'this', label: '本周' },
            { k: 'prev', label: '上周' },
            { k: 'custom', label: '自选' },
          ] as { k: Preset; label: string }[]).map(p => (
            <button
              key={p.k}
              className={`wc-preset-chip ${preset === p.k ? 'active' : ''}`}
              onClick={() => setPreset(p.k)}
            >
              {p.label}
            </button>
          ))}
        </div>
        {preset === 'custom' ? (
          <div className="wc-date-row">
            <input type="date" value={start} onChange={e => setStart(e.target.value)} />
            <span className="wc-tilde">→</span>
            <input type="date" value={end} onChange={e => setEnd(e.target.value)} />
          </div>
        ) : (
          <div className="wc-date-display">{start} → {end}</div>
        )}

        <div className="wc-section-label">风格</div>
        <StyleSelector
          value={style}
          onChange={(v) => { setStyle(v); setUserPreference(userId, 'drawStyle', v) }}
          customPrompt={customStylePrompt}
          onCustomChange={(v) => {
            setCustomStylePrompt(v)
            setUserPreference(userId, 'customDraw', v)
          }}
        />

        <div className="wc-actions">
          <button className="wc-btn wc-btn-secondary" onClick={onClose} disabled={generating}>
            取消
          </button>
          <button
            className="wc-btn wc-btn-primary pressable"
            onClick={submit}
            disabled={generating || !start || !end}
          >
            {generating ? '生成中…' : '开始生成'}
          </button>
        </div>
      </div>
    </BottomSheet>
  )
}
