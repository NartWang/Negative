import './style.css'

interface Props {
  onGenerate: () => void
}

export default function Banner({ onGenerate }: Props) {
  return (
    <div className="wc-banner slide-up">
      <div className="wc-banner-text">
        <div className="wc-banner-title">📖 本周漫画</div>
        <div className="wc-banner-sub">把这一周的日子，缝成一张画</div>
      </div>
      <button className="wc-banner-btn pressable" onClick={onGenerate}>
        生成 ▸
      </button>
    </div>
  )
}
