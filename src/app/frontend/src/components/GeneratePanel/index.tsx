import type { EmotionMode, DrawStyle } from '../../types'
import './style.css'

const EMOTION_MODES: { key: EmotionMode; label: string; emoji: string }[] = [
  { key: 'real', label: '真实传达', emoji: '🎯' },
  { key: 'warm', label: '温暖滤镜', emoji: '☀️' },
  { key: 'humor', label: '幽默轻松', emoji: '😄' },
  { key: 'poetic', label: '诗意文艺', emoji: '🌙' },
  { key: 'custom', label: '自定义', emoji: '✏️' },
]

const DRAW_STYLES: { key: DrawStyle; label: string; emoji: string }[] = [
  { key: 'ghibli', label: '治愈插画', emoji: '🏡' },
  { key: 'watercolor', label: '水彩日记', emoji: '🎨' },
  { key: 'grid4', label: '四宫格', emoji: '📐' },
  { key: 'comic', label: '叙事漫画', emoji: '💬' },
  { key: 'pixel', label: '像素复古', emoji: '👾' },
  { key: 'custom', label: '自定义', emoji: '✏️' },
]

interface Props {
  emotionMode: EmotionMode
  drawStyle: DrawStyle
  customEmotion: string
  customDraw: string
  onEmotionChange: (mode: EmotionMode) => void
  onDrawStyleChange: (style: DrawStyle) => void
  onCustomEmotionChange: (val: string) => void
  onCustomDrawChange: (val: string) => void
  onGenerate: () => void
  loading: boolean
}

export default function GeneratePanel({
  emotionMode, drawStyle, customEmotion, customDraw,
  onEmotionChange, onDrawStyleChange, onCustomEmotionChange, onCustomDrawChange,
  onGenerate, loading,
}: Props) {
  return (
    <div className="generate-panel">
      <div className="panel-section">
        <h3>情感模式</h3>
        <div className="pill-list">
          {EMOTION_MODES.map(m => (
            <button
              key={m.key}
              className={`pill ${emotionMode === m.key ? 'active' : ''}`}
              onClick={() => onEmotionChange(m.key)}
            >
              {m.emoji} {m.label}
            </button>
          ))}
        </div>
        {emotionMode === 'custom' && (
          <input
            className="custom-input"
            placeholder="描述你想要的情感风格..."
            value={customEmotion}
            onChange={e => onCustomEmotionChange(e.target.value)}
          />
        )}
      </div>

      <div className="panel-section">
        <h3>绘图风格</h3>
        <div className="pill-list">
          {DRAW_STYLES.map(s => (
            <button
              key={s.key}
              className={`pill ${drawStyle === s.key ? 'active' : ''}`}
              onClick={() => onDrawStyleChange(s.key)}
            >
              {s.emoji} {s.label}
            </button>
          ))}
        </div>
        {drawStyle === 'custom' && (
          <input
            className="custom-input"
            placeholder="描述你想要的画面感..."
            value={customDraw}
            onChange={e => onCustomDrawChange(e.target.value)}
          />
        )}
      </div>

      <button
        className="generate-action-btn"
        onClick={onGenerate}
        disabled={loading}
      >
        {loading ? '生成中...' : '✨ 开始生成'}
      </button>
    </div>
  )
}
