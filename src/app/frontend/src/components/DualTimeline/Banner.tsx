import './style.css'

interface Props {
  onOpen: () => void
}

export default function Banner({ onOpen }: Props) {
  return (
    <div className="dt-banner slide-up">
      <div className="dt-banner-text">
        <div className="dt-banner-title">🌿 双时间线</div>
        <div className="dt-banner-sub">我和家人的同一天</div>
      </div>
      <button className="dt-banner-btn pressable" onClick={onOpen}>打开 ▸</button>
    </div>
  )
}
