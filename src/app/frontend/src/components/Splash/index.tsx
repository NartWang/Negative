import { useEffect, useState } from 'react'
import './style.css'

interface Props {
  onDone: () => void
}

export default function Splash({ onDone }: Props) {
  const [exiting, setExiting] = useState(false)

  useEffect(() => {
    // 1500ms: 触发 fade-out 类（CSS transition 200ms）
    // 1700ms: 通知父组件卸载，确保动画播完
    const fadeT = window.setTimeout(() => setExiting(true), 1500)
    const doneT = window.setTimeout(onDone, 1700)
    return () => {
      window.clearTimeout(fadeT)
      window.clearTimeout(doneT)
    }
  }, [onDone])

  return (
    <div className={`splash ${exiting ? 'splash-exit' : ''}`}>
      <div className="splash-emoji">👨‍👩‍👧</div>
      <div className="splash-title">底片</div>
      <div className="splash-sub">把零散日常，冲洗成有人追更的人生剧</div>
    </div>
  )
}
