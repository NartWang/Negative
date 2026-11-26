import type { DrawStyle } from '../../types'
import './style.css'

// The four picturebook styles. Each one owns a pair of author-written prompts
// (diary -> story, story -> nine page prompts) under engine/prompts/<key>/.
const STYLES: { key: DrawStyle; label: string; ariaLabel: string; desc: string; image: string }[] = [
  { key: 'crayon', label: '蜡笔', ariaLabel: '蜡笔童趣', desc: '童趣浓郁', image: '/style-covers/crayon.png' },
  { key: 'watercolor', label: '水彩', ariaLabel: '水彩温柔', desc: '温柔通透', image: '/style-covers/watercolor.png' },
  { key: 'sketch', label: '素描', ariaLabel: '素描观察', desc: '细腻观察', image: '/style-covers/sketch.png' },
  { key: 'pixel', label: '像素', ariaLabel: '像素游戏', desc: '复古游戏感', image: '/style-covers/pixel.png' },
]

interface Props {
  value: DrawStyle
  onChange: (v: DrawStyle) => void
  disabled?: boolean
}

export default function StyleSelector({ value, onChange, disabled = false }: Props) {
  return (
    <div className="style-selector">
      <div className="ss-grid">
        {STYLES.map(s => (
          <button
            key={s.key}
            type="button"
            className={`ss-chip ${value === s.key ? 'active' : ''}`}
            aria-label={s.ariaLabel}
            aria-pressed={value === s.key}
            disabled={disabled}
            onClick={() => onChange(s.key)}
          >
            <span className="ss-cover-wrap">
              <img className="ss-cover" src={s.image} alt="" />
              {value === s.key && <span className="ss-selected" aria-hidden="true">✓</span>}
            </span>
            <span className="ss-copy">
              <span className="ss-label">{s.label}</span>
              <span className="ss-desc">{s.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
