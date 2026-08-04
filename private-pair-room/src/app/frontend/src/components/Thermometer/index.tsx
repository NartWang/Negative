import type { Thermometer as ThermometerData } from '../../types'
import './style.css'

interface Props {
  data: ThermometerData | null
}

const BAR_WIDTH = 280
const BAR_HEIGHT = 24

export default function Thermometer({ data }: Props) {
  if (!data) {
    return (
      <div className="thermo loading">
        <div className="thermo-row">
          <span className="thermo-score">--</span>
          <span className="thermo-label">读取中…</span>
        </div>
        <div className="thermo-track" />
      </div>
    )
  }

  const fillWidth = Math.max(0, Math.min(BAR_WIDTH, Math.round((data.score / 100) * BAR_WIDTH)))

  return (
    <div className="thermo slide-up">
      <div className="thermo-row">
        <span className="thermo-icon" aria-hidden>🌡</span>
        <span className="thermo-score" style={{ color: data.color }}>{data.score}°</span>
        <span className="thermo-label" style={{ color: data.color }}>{data.label}</span>
      </div>
      <svg
        className="thermo-bar"
        width={BAR_WIDTH}
        height={BAR_HEIGHT}
        viewBox={`0 0 ${BAR_WIDTH} ${BAR_HEIGHT}`}
        aria-label={`温度 ${data.score}`}
      >
        <defs>
          <linearGradient id="thermo-grad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%"   stopColor="#9CC5E0" />
            <stop offset="40%"  stopColor="#E8C8A0" />
            <stop offset="75%"  stopColor="#E89D7B" />
            <stop offset="100%" stopColor="#E67862" />
          </linearGradient>
          <clipPath id="thermo-clip">
            <rect x="0" y="0" width={fillWidth} height={BAR_HEIGHT} rx={BAR_HEIGHT / 2} />
          </clipPath>
        </defs>
        <rect
          x="0" y="0"
          width={BAR_WIDTH} height={BAR_HEIGHT}
          rx={BAR_HEIGHT / 2}
          fill="rgba(184,169,201,0.18)"
        />
        <rect
          x="0" y="0"
          width={BAR_WIDTH} height={BAR_HEIGHT}
          rx={BAR_HEIGHT / 2}
          fill="url(#thermo-grad)"
          clipPath="url(#thermo-clip)"
        />
      </svg>
      <div className="thermo-comment">{data.comment}</div>
    </div>
  )
}
