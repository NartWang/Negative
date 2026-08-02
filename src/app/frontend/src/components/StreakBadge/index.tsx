import './style.css'

interface Props {
  streak: number
  todayRecorded: boolean
  monthCheckins?: number
  monthDays?: number
}

export default function StreakBadge({ streak, todayRecorded, monthCheckins, monthDays }: Props) {
  return (
    <div className="streak-badge slide-up">
      <div className="streak-main">
        <div className="streak-number">
          {streak > 0 ? `🔥 ${streak}` : '🌱'}
        </div>
        <div className="streak-meta">
          <div className="streak-label">{todayRecorded ? '今天已记录' : '今天还没记录'}</div>
          {monthCheckins !== undefined && monthDays !== undefined && (
            <div className="streak-month">本月打卡 {monthCheckins} / {monthDays} 天</div>
          )}
        </div>
      </div>
    </div>
  )
}
