import type { DrawStyle } from '../../types'
import './style.css'

const STYLES: { key: DrawStyle; label: string; emoji: string }[] = [
  { key: 'ghibli', label: '治愈插画', emoji: '🏡' },
  { key: 'watercolor', label: '水彩日记', emoji: '🎨' },
  { key: 'grid4', label: '四宫格', emoji: '📐' },
  { key: 'comic', label: '叙事漫画', emoji: '💬' },
  { key: 'pixel', label: '像素复古', emoji: '👾' },
  { key: 'custom', label: '自定义', emoji: '✏️' },
]

interface Props {
  value: DrawStyle
  onChange: (v: DrawStyle) => void
  customPrompt: string
  onCustomChange: (v: string) => void
}

export default function StyleSelector({ value, onChange, customPrompt, onCustomChange }: Props) {
  return (
    <div className="style-selector">
      <div className="ss-grid">
        {STYLES.map(s => (
          <button
            key={s.key}
            className={`ss-chip ${value === s.key ? 'active' : ''}`}
            onClick={() => onChange(s.key)}
          >
            <span className="ss-emoji">{s.emoji}</span>
            <span className="ss-label">{s.label}</span>
          </button>
        ))}
      </div>
      {value === 'custom' && (
        <input
          className="ss-custom"
          placeholder="描述你想要的画面感..."
          value={customPrompt}
          onChange={e => onCustomChange(e.target.value)}
        />
      )}
    </div>
  )
}
